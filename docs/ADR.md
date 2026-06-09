# Architecture Decision Record

Status: accepted. Context: Distributed Job Orchestrator, a vertical slice of an asynchronous job
processing system. Users submit jobs through an API, jobs run on a worker fleet, and users are
notified on completion or failure. The full architecture proposal is in `DESIGN.md`; this is the
one-page summary.

## 1. Most important decisions

### The database is the source of truth; the queue is a delivery mechanism

Job state lives in PostgreSQL as a state machine (`pending`, `queued`, `running`, `retrying`,
`succeeded`, `failed`, `cancelling`, `cancelled`, `expired`). A Redis message is a signal to
execute a job, never the only record of it. This is what makes the four stated requirements
possible: status queries (a queue cannot be queried by arbitrary job id), cancellation (a specific
in-flight message cannot be reliably found and mutated, a database row can), retries (attempt
count, last error, and next attempt time need durable structured storage), and crash recovery
(after a failure the system is reconstructed from the database, not from ephemeral queue contents).

### At-least-once delivery with idempotent processing, never exactly-once

Exactly-once execution across distributed workers and external dependencies is not a realistic
guarantee, so the system is designed to tolerate duplicates instead of pretending to prevent them.
A worker claims a job with a conditional UPDATE (`... WHERE status IN ('queued','retrying')`) and a
row-count check, so a duplicate delivery or a second worker simply updates zero rows and stops. The
dual-write between the database and the queue is handled by a transactional outbox: the job row and
a dispatch-outbox row are written in one transaction, and the scheduler publishes to Redis after
commit, with a stuck-queued reaper as the database-backed backstop. Submission carries an
optional Idempotency-Key scoped per user, backed by a partial unique index, so client retries do
not create duplicate jobs.

### Cooperative best-effort cancellation with lease-based crash recovery

Cancellation cannot always interrupt work instantly, so it is defined as best-effort and
cooperative. A queued or waiting job is cancelled immediately and the worker skips it if a stale
message is later delivered. A running job is marked `cancelling`; the worker checks the flag at
handler checkpoints and finalizes to `cancelled` at a safe point, and may finish first
(`cancelling -> succeeded`). Workers hold a time-boxed lease and a heartbeat thread extends it; if a
worker crashes, a scheduler reaper detects the expired lease and requeues the job (or fails it if
retries are exhausted). Cancelling a terminal job returns 409.

## 2. Unclear requirements and the assumptions I made

The brief deliberately leaves several things open. Where it did, I chose and recorded a default.

- Peak submission rate and job duration are unspecified. I sized the design around buffering spikes
  in the queue and scaling workers horizontally, and I made the lease duration and heartbeat
  interval configuration so they can be tuned to the real job-duration distribution.
- "Real time" status is defined here as near-real-time, not hard real-time. The dashboard polls
  every one to two seconds and the database is always authoritative. Hard real-time was not a
  stated requirement and would add connection-management cost for little benefit at this scale.
- Authentication is out of scope, but ownership is not. Caller identity comes from an `X-User-Id`
  header and every read and cancel is scoped to the owner; an unknown owner gets a 404.
- Notification delivery has no stated SLA, so it is best-effort: written through an outbox in the
  same transaction as the terminal state change, retried with backoff, and deduplicated per
  (job, event) so a user is never notified twice.
- Jobs are assumed to run trusted server-side handlers, not arbitrary user code. Untrusted-code
  execution would change the security model entirely (sandboxing, isolation) and is called out as a
  separate, larger problem.
- Result and payload sizes are assumed small and are stored inline as JSONB; large artifacts would
  move to object storage referenced by id.

## 3. What would change at significant scale

"Significant" here means thousands of submissions per second, millions of live jobs, many tenants
that need isolation and fairness, or strict notification SLAs. In that world:

- The Redis list queue moves to a managed broker (SQS, Google Pub/Sub) or a partitioned log, and
  the single scheduler becomes multiple partitioned scheduler instances with leader election so the
  outbox, retry, and reaper loops scale and stay highly available.
- The `jobs` table is partitioned (by time or tenant) with archival of terminal jobs, and the
  status summary stops being a live `GROUP BY` and becomes a cached or maintained counter.
- Cancellation and status push move to Server-Sent Events, and notification delivery moves to a
  claim-then-deliver pattern so a slow webhook never holds a database transaction.
- Fairness becomes real: weighted fair queueing and per-tenant quotas and concurrency caps replace
  the simple three-level priority lists, so one large customer cannot starve the rest during a
  spike.
- A full observability stack (OpenTelemetry traces, Prometheus metrics, dashboards, alerts on DLQ
  growth and queue age) and real authentication and authorization are added.

## 4. Deliberately left out

Authentication, untrusted-code sandboxing, object storage for large artifacts, Server-Sent Events,
weighted fair scheduling, a managed broker, OpenTelemetry and Prometheus, multi-region failover,
and a third-party task framework (Celery, RQ). Each is either explicitly out of scope or a scale
concern that would be premature for a vertical slice, and including it would trade correctness and
clarity for unused machinery. The custom worker loop is deliberate: it keeps the lease, heartbeat,
conditional-transition, and outbox mechanics explicit and provable by tests rather than hidden in a
framework. Observability beyond structured logs was left out of v1 for the same reason and is the
first thing listed above to add.
