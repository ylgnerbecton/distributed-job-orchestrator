# Distributed Job Orchestrator - Architecture Proposal

A system that accepts user-submitted jobs over an API, runs them asynchronously on a worker fleet, survives crashes and duplicate delivery, lets users watch and cancel work, and notifies them when a job reaches a terminal state. Written for a healthcare and financial-services context, so durability, auditability, and tenant isolation are treated as first-class constraints rather than afterthoughts.

This document carries the reasoning and the trade-offs in the main body (sections 1 to 31) and pushes exhaustive detail (full schema, every endpoint, the outbox flow, Flask wiring, the metrics catalog, the full transition matrix) into the appendices (A to F). It maps directly onto the accompanying reference implementation: Flask plus flask-smorest API, PostgreSQL 16 as the source of truth, Redis as a durable delivery queue, and separate worker and scheduler processes.

A note on language used throughout: this system is at-least-once with idempotent processing. It never claims exactly-once execution, because that is not a guarantee any honest distributed system can make across crashing workers and external dependencies.

---

## 1. Executive Summary

The core idea is to separate four concerns that are usually tangled together: submission, state, execution, and notification.

- The API accepts a job, validates it, and writes it to the database. It never runs the job inline. It returns 202 immediately.
- PostgreSQL is the single source of truth for job state, modeled as an explicit state machine. Every transition is a guarded conditional UPDATE, so concurrent or duplicate actors cannot corrupt state.
- Redis is the delivery mechanism, not the source of truth. A queue message is a signal to execute a job that already exists in the database, not the only record of it.
- A worker fleet consumes job ids, claims each job with a conditional UPDATE that doubles as a distributed lock, runs the handler outside any database transaction, heartbeats to hold its lease, and finalizes the job.
- A scheduler process runs the periodic control loops: publish from the outbox, promote due retries, reap expired leases, re-publish stuck jobs, expire stale jobs, and deliver notifications.
- Notifications go through a transactional outbox, written in the same transaction as the terminal state change, so a user is notified exactly when the job actually finished and never twice.

The dual-write problem between database and queue is solved with a transactional outbox: the API writes the job and an outbox row in one transaction; the scheduler reads the outbox and publishes to Redis. A stuck-queued reaper is the liveness backstop if a publish is lost after commit.

The three genuinely hard problems are not the endpoints. They are: correct state transitions under at-least-once delivery, cancellation of running jobs, and absorbing spikes without hurting reliability or fairness. Sections 26, 13, and 16 address each one directly.

---

## 2. Requirements Interpretation

Each stated requirement translates into concrete engineering consequences.

High submission volume with unpredictable spikes:
- The submission path must be fast and must never execute a job inline. The API writes one job row plus one outbox row and returns 202. That is the entire critical path.
- The queue absorbs spikes; workers scale independently of the API. A burst of submissions grows queue depth, not API latency.
- The API must protect itself and its downstreams. Payload size is capped, input is validated, and admission control belongs at the edge.

Long-running jobs (seconds to minutes):
- Workers need a lease with heartbeats so a slow but healthy job is not mistaken for a dead one and redelivered prematurely.
- Cancellation must be cooperative. You cannot interrupt a minute-long operation instantly and safely, so the worker checks a flag at checkpoints.
- Progress is persisted so a status read reflects reality during execution, not just at the end.

Retry logic:
- Failures are classified as retryable or non-retryable. Not every failure should be retried; retrying a validation error just wastes capacity and delays the inevitable failure.
- Backoff is exponential with jitter, attempts are capped, and exhausted jobs are dead-lettered.
- Because delivery is at-least-once, handlers must be safe to run more than once.

Real-time status:
- Status is a database read. Polling is the v1 mechanism and is good enough for most products. Server-Sent Events is the documented next step when users actively watch long jobs.
- Workers emit progress so the status is meaningful mid-flight.

Cancellation:
- You cannot always kill work instantly. The API marks the job, the worker observes and stops at a safe point.
- The terminal state is cancelled, but a job may finish first. Cancelling an already-terminal job is a conflict, not a silent success.

---

## 3. Assumptions

1. Users are authenticated. The auth mechanism is out of scope for this exercise, but ownership checks are in scope and enforced on every read and cancel.
2. Each job belongs to one user (a tenant). Multi-tenancy and isolation matter because of the regulated domain.
3. Jobs produce small metadata results inline, and optionally large artifacts that would live in object storage and be referenced by id.
4. Completion in seconds to minutes is acceptable. This is not a hard real-time system.
5. Execution is at-least-once, not exactly-once.
6. Job handlers are idempotent or protected by idempotency keys, because at-least-once means a handler can run more than once.
7. Some jobs are cancellable, but not every job can be interrupted instantly.
8. Users need near-real-time status, not hard real-time guarantees.
9. Notifications are best-effort but retried with tracking, and never delivered twice for the same job and event.
10. Reliability and auditability are favored over ultra-low latency, consistent with healthcare and financial use.
11. Payloads have a maximum size (65536 bytes in the reference). Anything larger goes to object storage and is referenced by id.
12. Multi-region is not required for v1. Single-region high availability is acceptable for initial production.
13. Job handlers run trusted server-side code, not arbitrary user code. Untrusted code execution is a separate, much larger problem (section 19).
14. The system may carry PHI or PII, so it is designed SOC2 and HIPAA aware even though the exact compliance scope is unconfirmed.

---

## 4. Open Questions I Would Clarify With the Team

These are decisions to confirm, not blockers. A senior engineer raises them before committing capacity.

- Expected peak submission rate and the average plus 95th-percentile job duration. These two numbers size the worker fleet, the lease duration, and the queue-depth alert thresholds. Everything downstream is guesswork without them.
- Whether any job will ever execute user-provided or untrusted code. This changes the security model from "trusted handlers" to "sandboxed execution" and is a different project.
- Data sensitivity. Is PHI or PII present in payloads, results, or error messages, and what are the retention and residency requirements? This drives encryption, redaction, and the purge schedule.
- Notification SLA. How fast must a user learn of completion, and is delivery contractually guaranteed or best-effort? This decides how aggressive the outbox dispatcher and its alerting must be.
- Whether multi-step or dependent jobs (workflows) are in scope now or later. A DAG of jobs is a different data model; I would not build it speculatively.
- Tenant fairness expectations. During a spike, can one customer consume most of the capacity, or is fairness a hard requirement? This decides whether v1 needs more than per-priority queues.
- Result size distribution. This sets the threshold for storing a result inline in the database versus in object storage.

---

## 5. High-Level Architecture

The architecture is a pipeline of small, independently scalable parts connected by a database that holds the truth and a queue that moves work.

The API service is stateless. It validates a submission, writes the job and a dispatch-outbox row in one transaction, and returns 202. It does not touch the queue on the request path; that decoupling is what keeps submission fast and the dual-write safe.

PostgreSQL holds every job as a row in a state machine. State only ever changes through guarded conditional UPDATEs, so two actors racing on the same job cannot both win. The database also holds the per-attempt audit, the append-only event timeline, and both outboxes.

Redis is the durable queue. It has three lists (high, normal, low) consumed by a single blocking pop in priority order, so a high-priority job jumps ahead of normal and low work without a separate consumer. The queue carries job ids only; the payload stays in the database.

Workers are stateless processes. Each one blocking-pops a job id, claims the job with a conditional UPDATE that is simultaneously the state transition and the distributed lock, runs the handler outside any transaction, heartbeats on a background thread to extend its lease, and finalizes the job in a short transaction that also enqueues the terminal notification.

The scheduler is one lightweight process running six control loops on a fixed interval. It is the system's liveness engine: it publishes from the outbox, promotes due retries, reaps expired leases (crashed workers), re-publishes stuck queued jobs, expires stale jobs, and delivers notifications.

The status channel is polling for v1. The React dashboard polls GET /jobs and GET /jobs/{id}. SSE is the documented upgrade.

---

## 6. Architecture Diagram

```
                  +-------------------+
                  |      Clients      |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  | API Gateway / LB  |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  | Job API (Flask)   |
                  +----+---------+----+
                       |         |
                       |         v
                       |   +-------------+
                       |   | Job DB      |
                       |   | Source of   |
                       |   | Truth (PG)  |
                       |   +------+------+
                       |          ^
                       |          | (outbox -> publish,
                       |          |  retries, lease reaper,
                       |          |  expiry, notifications)
                       |   +------+------+
                       |   |  Scheduler  |
                       |   +------+------+
                       |          |
                       v          v
                  +-------------------+
                  |  Durable Queue    |
                  |  (Redis: high/    |
                  |   normal/low)     |
                  +---------+---------+
                            |
                            v
                  +-------------------+
                  |   Worker Fleet    |
                  +----+---------+----+
                       |         |
                       |         v
                       |   +-------------+
                       |   | Result /    |
                       |   | Object Store|
                       |   +-------------+
                       |
                       v
                  +-------------------+
                  | Notification Svc  |
                  | (outbox-backed)   |
                  +-------------------+

                  +-------------------+
                  | Status API / SSE  |
                  +-------------------+
```

Each edge, briefly:
- API -> Job DB: the job and its outbox row are written in one transaction. This is the only write on the submission path.
- Scheduler -> Queue: the scheduler, not the API, publishes job ids to Redis after the database commit (commit-then-publish).
- Queue -> Workers: at-least-once delivery; duplicates are expected and absorbed by the conditional claim.
- Workers -> Job DB: every progress update and every finalize is a guarded UPDATE against the source of truth.
- Workers -> Notification: the terminal notification is written to the outbox in the same transaction as the terminal state.
- Status API -> Job DB: reads the truth directly. The stream, when added, is only a faster delivery channel, not a second source of truth.

---

## 7. Core Components and Responsibilities

For each component: responsibility, design details, failure behavior, scaling.

### API Gateway / Load Balancer
Responsibility: route traffic, terminate TLS, enforce request-size limits, apply rate limiting, integrate authentication. Design: stateless edge where admission control begins. Failure: a saturated edge must shed load predictably (reject with a clear status code), not queue unboundedly and time out. Scaling: stateless, horizontal.

### Job API Service (Flask)
Responsibility: validate the submission, authorize the user, cap payload size, create the job row, enforce the idempotency key, write the dispatch-outbox row, and serve status, list, summary, cancel, and events endpoints. Design: submission writes two rows in one transaction and returns 202; it never runs the job and never publishes to the queue directly. Failure: if the process dies after the commit, the job is safe in the database and the scheduler will publish it from the outbox. Scaling: stateless Flask behind gunicorn, scaled horizontally.

### Job State Store (PostgreSQL)
Responsibility: source of truth for job metadata, the state machine, attempts, timestamps, lease columns, cancellation requests, ownership, idempotency records, the audit timeline, and both outboxes. Why relational fits: transactions make the outbox and the same-transaction notification possible; conditional UPDATEs make safe concurrent transitions possible; indexes make status queries and the scheduler's scans cheap; a relational store gives auditability and arbitrary lookup by job id, which a queue cannot. Failure: tolerate failover and elevated latency; status reads degrade before writes do. Scaling: index the hot queries (Appendix A), keep events append-only, archive terminal jobs, partition only if volume demands it.

### Durable Queue (Redis)
Responsibility: absorb spikes, buffer pending work, distribute job ids to workers, and hold the dead-letter list. Design: three priority lists consumed by one blocking pop in high-normal-low order; carries ids only. Failure: at-least-once delivery means duplicates happen and are handled by the conditional claim; the queue is never consulted for truth. Scaling: backlog depth and oldest-message age are the primary operational and autoscaling signals.

### Worker Fleet
Responsibility: blocking-pop a job id, claim it (conditional UPDATE = transition + lock), record the attempt, run the handler, heartbeat, check cancellation, and finalize (succeeded, failed, retrying, or cancelled) while enqueuing the terminal notification. Design: stateless; the handler runs outside any database transaction so a long job does not hold a connection or a lock open; progress and cancellation checks are short separate transactions. Failure: a crash leaves an expired lease that the scheduler reaps. Scaling: horizontal on queue depth and message age; pools can be split by job type or priority later.

### Scheduler / Retry Coordinator
Responsibility: the six control loops (dispatch from outbox, promote due retries, reap expired leases, re-publish stuck queued jobs, expire stale jobs, dispatch notifications). Design: a single process on a fixed interval; every loop is idempotent because every write is a guarded UPDATE. Failure: if the scheduler is down, nothing corrupts; new jobs simply wait in the outbox and retries wait in retrying until it returns. Scaling: lightweight; one active instance is enough for v1, with leader election if a second is ever added.

### Notification Service
Responsibility: deliver completion, failure, cancellation, and expiry notifications over a channel (log by default, signed webhook if the payload carries one), with backoff retries and per-event deduplication. Design: outbox-backed; rows are written in the same transaction as the terminal state. Failure: a provider outage buffers in the outbox and is retried; nothing is lost, only delayed. Scaling: dispatcher throughput scales with the scheduler batch size, and can move to dedicated dispatcher workers later.

### Status Service / Real-Time Channel
Responsibility: GET a job, list a user's jobs with cursor pagination, return per-job counts, and stream updates later via SSE. Recommendation: polling for v1. Trade-off: polling is simple, reliable, cacheable, and good enough; SSE and WebSockets add latency wins at the cost of connection-scaling and operational complexity. Design: reads the database directly; the stream is only a channel.

### Result Store
Responsibility: hold small results inline in the database; large artifacts belong in object storage referenced by id, served via signed URLs. Failure: an object-store outage degrades artifact download but not job correctness, because correctness lives in the database. Scaling: object storage scales independently of the database.

---

## 8. Job Lifecycle

Job state is an explicit machine. States: pending, queued, running, retrying, succeeded, failed, cancelling, cancelled, expired. Terminal states: succeeded, failed, cancelled, expired.

Valid transitions (the full valid/invalid matrix is Appendix F):

```
pending   -> queued | cancelled | expired
queued    -> running | cancelled | expired
running   -> succeeded | failed | retrying | cancelling | queued
retrying  -> queued | cancelled
cancelling-> cancelled | succeeded | failed
```

The `running -> queued` edge is the lease reaper requeuing a crashed worker's job. The `cancelling -> succeeded | failed` edges exist because a job can finish before it observes the cancellation request.

ASCII state diagram:

```
submitted (pending)
   |
   v
 queued -----> cancelled
   |  \
   |   \------> expired
   v
 running ----> succeeded
   |  \\
   |   \-----> cancelling -----> cancelled
   |   \                  \----> succeeded | failed
   |    \----> failed
   v
 retrying ----> queued
```

The important nuance: a job may finish before its cancellation is processed, so the final state may be succeeded or failed rather than cancelled. Cancellation is best-effort and cooperative unless a job type supports hard interruption.

---

## 9. Key Flows (Submission, Retry, Cancellation)

Submission:
1. Client sends POST /jobs with a body and an optional Idempotency-Key header.
2. API validates the body and the payload size, and normalizes it per job type.
3. If an idempotency key is present and already maps to a job for this user, the existing job is returned (no duplicate created).
4. In one transaction: insert the job as pending, record a submitted event, insert a dispatch-outbox row.
5. API returns 202 with the job id and a status URL.
6. The scheduler's dispatch loop claims the outbox row, transitions the job pending -> queued in the same transaction it marks the outbox published, then LPUSHes the job id to the priority list after commit.
7. A worker blocking-pops the id and claims the job with a conditional UPDATE (queued or retrying, not cancelled). Rowcount 0 means another worker won or it was cancelled; the worker skips.
8. The worker runs the handler, heartbeating and reporting progress.
9. The worker finalizes the job and, in the same transaction, enqueues the terminal notification.
10. The notification dispatcher delivers it. The user polls status throughout.

The transaction boundary is explicit: the job exists in the database before any worker can see it, because the worker only ever sees an id the scheduler published from the committed outbox. If the publish is lost after commit, the stuck-queued reaper re-publishes from the database. Appendix C details this.

Retry: on a retryable failure with attempts remaining, the worker transitions the job to retrying and sets next_attempt_at to now plus exponential backoff with jitter. The scheduler's retry loop promotes due retrying jobs back to queued and re-publishes them. On exhaustion, the job is marked failed, dead_lettered_at is set, and the id is pushed to the Redis dead-letter list.

Cancellation: the API marks a queued, pending, or retrying job straight to cancelled (row-locked), or marks a running job cancelling and records the request. The worker observes the request at its next checkpoint and finalizes to cancelled at a safe point. An already-terminal job returns 409.

---

## 10. Retry and Failure Handling

Decision: classify errors, retry only the retryable ones with capped exponential backoff and jitter, and dead-letter the rest.
Reason: retrying a non-retryable error (bad input, permission denied) wastes capacity and only delays a certain failure; retrying a transient error (timeout, downstream rate limit) usually succeeds.
Trade-off: classification requires handlers to raise the right error type, which is a small discipline cost.
Failure mode: a handler raises a generic exception that is actually permanent, and the system retries it to exhaustion.
Mitigation: unexpected exceptions are treated as retryable but still bounded by max_attempts, so the cost is capped at a handful of attempts and the job lands in the dead-letter list for inspection.

Handlers raise RetryableError or NonRetryableError. Retryable examples: network timeout, transient dependency failure, a downstream or LLM-provider rate limit, a transient 5xx. Non-retryable examples: invalid input, permission denied, unsupported job type.

The backoff curve grows geometrically from a small base, is capped at a maximum, and has symmetric jitter applied. The shape matters more than the exact numbers: start small so transient blips recover quickly, grow geometrically so a struggling dependency is not hammered, cap so a job does not sleep for hours, and jitter so a thundering herd of retries does not re-synchronize into a second spike. The concrete schedule is in Appendix B.

After max attempts: mark failed, store the final error code and message, set dead_lettered_at, push to the dead-letter list, and emit a failure notification.

The system is designed for at-least-once delivery with idempotent processing, because exactly-once execution is not a realistic guarantee across distributed workers and external dependencies. Retries therefore require idempotent handlers; side effects must be guarded with idempotency keys, external operation ids, check-before-write, dedupe records, or transactional writes.

---

## 11. Cancellation Design

Decision: cancellation is cooperative and best-effort for running jobs, and immediate for jobs that have not started.
Reason: a worker mid-operation cannot be safely interrupted from the outside without risking partial side effects; a job sitting in the queue can be finalized instantly.
Trade-off: a user who cancels a running job may still see it succeed or fail, because the job can cross the finish line before it checks the flag.
Failure mode: the worker crashes after the cancel is requested but before it finalizes.
Mitigation: the job is left in cancelling with an expired lease; the lease reaper requeues or fails it, and the request is preserved in cancellation_requested_at so it is honored on the next claim.

Three cases:
- Queued, pending, or retrying job: the API takes a row lock (SELECT ... FOR UPDATE), transitions straight to cancelled, records the event, and enqueues the cancelled notification. If a stale queue message for this job is later delivered, the worker's conditional claim fails (the status is no longer claimable) and it skips.
- Running job: the API sets status to cancelling and stamps cancellation_requested_at. The worker checks the flag at handler checkpoints and finalizes to cancelled at a safe point. If it cannot stop in time, the job finishes (cancelling -> succeeded or failed); the cooperative model accepts that.
- Terminal job: 409 Conflict. A finished job cannot be cancelled.

Workers check cancellation before each major step and again before scheduling a retry, so a job that fails transiently while a cancel is pending finalizes as cancelled rather than looping through more attempts. The user-facing wording is explicit: cancellation is best-effort and cooperative for running jobs.

---

## 12. Real-Time Status Updates

Decision: polling for v1; SSE as the documented next step; WebSockets only for a broader real-time product need.
Reason: status is a cheap indexed database read, and polling every one to five seconds is simple, reliable, cacheable, and survives reconnects with zero server state. The reference frontend uses TanStack Query polling.
Trade-off: polling adds a small constant read load and a few seconds of latency versus a push channel.
Failure mode: at very high concurrency, naive polling could pressure the database.
Mitigation: status reads are single-row or short keyset scans on indexed columns; a short-lived cache on hot job ids is the first lever, and SSE is the second, before any WebSocket investment.

Options compared:
- Polling: simplest, most reliable, easiest to operate, good first version.
- Server-Sent Events: one-way server push, lower latency, good for progress, simpler than WebSockets.
- WebSockets: bidirectional, justified only by many live dashboards or a broader real-time need, and the most operational overhead.

In every case the database stays the source of truth; the stream is only a faster delivery channel for the same state.

---

## 13. Notification Design

Decision: deliver notifications through a transactional outbox, written in the same transaction as the terminal state change, with per-event deduplication.
Reason: this couples "the job finished" to "the user will be told" atomically. There is no window where a job completes but the notification is lost, and no window where a notification fires for a job that did not actually finish.
Trade-off: delivery is asynchronous, so there is a small delay between the terminal transition and the user seeing it.
Failure mode: the notification provider (webhook endpoint) is down.
Mitigation: the row stays pending in the outbox and is retried with backoff up to a cap; after the cap it is marked failed and surfaced, but the job's own correctness is unaffected.

Flow:
1. The worker (or the scheduler's reaper/expiry loop) marks the job terminal.
2. In the same transaction, it inserts a notification-outbox row with a dedupe_key of `{job_id}:{event_type}`, using insert-on-conflict-do-nothing so a duplicate finalize cannot create a second notification.
3. The scheduler's notification loop claims due rows (row-locked, skip-locked), delivers them, and marks them sent.
4. Failures are rescheduled with backoff; the cap prevents infinite retries.

Channels: a LOG channel by default (the destination is the user id), or a signed HMAC-SHA256 webhook if the job payload carries a notify_webhook. Webhooks are signed (the receiver verifies the signature header), retried with backoff, and capped. The dedupe key plus the unique index means a user is never notified twice for the same job and event, even under duplicate delivery or a double finalize.

---

## 14. Consistency, Idempotency, and Duplicate Handling

This is the spine of the design. Three layers of idempotency.

Submission idempotency: the client may send an Idempotency-Key. It is scoped per user_id and backed by a partial unique index on (user_id, idempotency_key). A duplicate submission returns the same job rather than creating a second one. The path is check-then-insert, with an IntegrityError catch that re-reads the existing job to close the race between two concurrent identical submissions.

Worker idempotency under at-least-once delivery: the queue can deliver the same id twice, and the lease reaper can legitimately requeue a job whose original worker stalled. The claim is a single conditional UPDATE:

```sql
UPDATE jobs
SET status = 'running',
    attempts = attempts + 1,
    locked_by = :worker_id,
    lock_expires_at = :now + :lease,
    heartbeat_at = :now,
    started_at = COALESCE(started_at, :now)
WHERE id = :job_id
  AND status IN ('queued', 'retrying')
  AND cancellation_requested_at IS NULL
RETURNING attempts;
```

If this affects zero rows, another worker already claimed the job or it was cancelled, and this worker skips. This is precisely why duplicate deliveries never double-run a job: only one UPDATE can move the row out of a claimable status, and the row is the arbiter.

Finalize idempotency: every finalize (succeeded, failed, retrying, cancelled) is also guarded, additionally on `locked_by = :worker_id`, so a worker whose lease already expired and was reaped cannot overwrite the new owner's result. If the guard fails, the late attempt is marked superseded in the audit and discarded.

The principle: state only ever changes through a guarded UPDATE whose WHERE clause encodes the precondition. The database, not application logic, is the concurrency arbiter.

---

## 15. Worker Lease and Heartbeat

Decision: a worker holds a time-bounded lease on a job, renewed by a background heartbeat, and a separate reaper recovers leases that expire.
Reason: this is how the system distinguishes a slow-but-healthy job from a dead worker without killing the former or stranding the latter.
Trade-off: a short lease recovers crashes faster but adds heartbeat write load; a long lease is cheaper but strands a crashed job's work for longer.
Failure mode: a healthy worker is paused (GC, network blip) long enough for its lease to expire, the reaper requeues the job, and now two workers run it.
Mitigation: the lease is set comfortably longer than the heartbeat interval (60s lease, 15s heartbeat in the reference, four chances to renew before expiry), and the finalize guard on locked_by ensures the stale worker's late result is rejected. The job runs twice but only one result is ever committed, which is exactly the at-least-once contract.

On claim, the worker sets locked_by, lock_expires_at, and heartbeat_at in the same UPDATE that marks the job running. A daemon thread re-stamps lock_expires_at every heartbeat interval. Progress updates also extend the lease, so an actively-working job never expires. The scheduler's lease reaper finds running jobs with lock_expires_at in the past and either requeues them (attempts remain) or fails and dead-letters them (attempts exhausted).

---

## 16. Scaling and Backpressure Strategy

Decision: the system fails predictably under overload rather than accepting unbounded work and timing out later.
Reason: a system that accepts everything during a spike converts a capacity problem into a latency-and-timeout problem for every user at once, which is worse.
Trade-off: some submissions are rejected or throttled during extreme spikes, which is a visible degradation.
Failure mode: retries amplify load during an incident, turning a dip into a sustained overload (a retry storm).
Mitigation: backoff with jitter spreads retries out, max_attempts plus the dead-letter list act as a relief valve, and admission control sheds load at the edge before it reaches the database.

By layer:
- API: stateless and horizontal, with payload caps, input validation, and per-user rate limits. It does almost no work per request, so it scales cheaply.
- Queue: absorbs bursts and decouples API from workers. Backlog depth and oldest-message age are the headline operational metrics.
- Workers: scale on queue depth and message age; per-priority lists already let urgent work jump the line; per-type pools and per-tenant concurrency caps are the next levers.
- Database: hot queries are indexed (Appendix A), events are append-only, terminal jobs are archived, and partitioning is held in reserve for very high volume.
- Backpressure: reject or throttle submissions when the backlog is too deep, enforce per-user and per-tenant quotas, and use the priority lists for admission ordering.

---

## 17. Priority and Fairness

The risk is that one large customer floods the system and starves everyone else during a spike.

v1 approach: three priority lists (high, normal, low) consumed in order, a priority field on every job, per-worker concurrency limits, and per-user rate limits at the edge. This is enough to keep urgent work moving and to stop a single client from trivially monopolizing intake.

Trade-off: strict priority ordering can starve low-priority work if high-priority volume is sustained. v1 accepts this because it is simple and the priority lists are already in the implementation.

For a mature system: weighted fair queueing and tenant-aware scheduling, so capacity is shared by policy rather than by arrival order. That is deliberately out of v1 scope (section 30) because it adds real scheduler complexity for a fairness guarantee the team has not yet confirmed it needs (section 4).

---

## 18. Compliance and Data Governance (SOC2 / HIPAA aware)

Decision: design for SOC2 and HIPAA-aligned operation from day one (minimize sensitive data, encrypt everywhere, isolate tenants, audit everything), without claiming certification.
Reason: the domain is healthcare and financial services; retrofitting data protection after a breach or an audit finding is far more expensive than building it in.
Trade-off: data minimization and redaction add small friction to debugging, because you cannot just log the raw payload.
Failure mode: PHI or PII leaks into logs, error messages, or a notification body.
Mitigation: redact payloads and errors in logs by policy, keep secrets out of payloads entirely, and treat the notification body as a place for ids and status, not raw sensitive content.

Concretely:
- Data classification: payloads, results, and error messages are the fields most likely to carry PHI or PII. Store the minimum necessary, and reference large or sensitive blobs by id in object storage rather than inlining them.
- Encryption: TLS in transit everywhere; encryption at rest for the database, object storage, and queue payloads where the platform supports it.
- Secrets: never in a job payload. Reference a secret by id and resolve it at execution time inside the worker.
- Tenant isolation: ownership is enforced on every read and cancel via the identity header; every query is scoped by user_id. Row-level scoping and per-tenant keys are the next step.
- Immutable audit trail: job_events is append-only and, with job_attempts, gives a complete, reviewable timeline per job, suitable for compliance review.
- Retention and expiry: payloads, results, and artifacts get a TTL and a scheduled purge; the expired lifecycle state already models age-out for jobs that never start.
- Least privilege: services and operators get the minimum access, and access to job data is itself logged.
- Logging hygiene: structured logs carry job_id, user_id, type, attempt, worker_id, transition, error code, and duration, with raw payload and error contents redacted.

---

## 19. Security and Abuse Prevention

Authentication and authorization gate the API. Ownership checks ensure a user can only read or cancel their own jobs; in the reference this is enforced on every read and cancel via an X-User-Id identity header, which is a deliberate stand-in for real auth (see the deviation note below). Payload size is capped and every input is validated by marshmallow schemas. Per-user rate limits and quotas blunt abuse and protect downstreams. Webhooks are signed with HMAC-SHA256 so receivers can verify authenticity. Sensitive payloads are encrypted, and secrets never travel in a payload. The audit timeline doubles as a security record.

Deviation, stated plainly: v1 has no real authentication. It is explicitly out of scope for this exercise. Ownership is enforced through the X-User-Id header (defaulting to a demo user), which stands in for an authenticated principal. In production this header would be replaced by a verified token claim, with no change to the ownership logic that already scopes every query by user.

Untrusted code: the baseline assumption is that job handlers run trusted, server-side code (the five demo types in section 23). If the product ever needs to run user-provided code, sandboxing and isolation (resource limits, syscall filtering, network egress control, separate execution environments) become a major additional problem, called out here as out of scope and not solved by anything in this design.

---

## 20. Observability and Operations

The full catalog is Appendix E; the essentials:

Logs are structured and carry job_id, user_id, job_type, attempt, worker_id, the status transition, error code, and duration, with PHI and PII redacted. The health endpoint reports database and queue reachability.

Metrics worth alerting on: submissions per minute, queue depth, oldest queued-job age, duration p50/p95/p99, success/failure/retry/cancellation rates, dead-letter count, notification success and failure, worker utilization, and heartbeat misses.

Traces span the submission, the queue publish, worker execution, and notification delivery, so a single job can be followed end to end.

Alerts fire on dead-letter growth past a threshold, high queue age, high worker error rate, notification failures, elevated database latency, and stuck running jobs. Each alert maps to a concrete failure in section 22.

---

## 21. SLOs, Error Budgets, and Capacity

Candidate SLOs, each with its reasoning:
- Submission API availability and latency: the submission path writes two rows and returns 202, so a p99 in the low hundreds of milliseconds is a reasonable target. It does no heavy work, so latency here is a pure infrastructure-and-database signal.
- Status read latency: indexed single-row and short keyset reads; the target is tight because users poll it constantly.
- Time-to-start (queued -> running) under normal load: this is the headline user-perceived metric and it is governed directly by worker capacity versus arrival rate.
- Time-to-notify after a terminal state: bounded by the scheduler interval plus delivery; the SLA here depends on the answer to the open question in section 4.

Error budgets are the lever for deciding when to spend on reliability versus features: if time-to-start is comfortably inside budget, build features; if it is burning budget, add workers or tighten admission. Queue depth and oldest-message age are the leading indicators that feed both autoscaling and the capacity conversation, because they rise before the SLO is actually breached.

---

## 22. Failure Scenarios (What Breaks at 3am)

| Scenario | Detection | Mitigation |
|---|---|---|
| Worker crashes mid-job | lock_expires_at in the past; heartbeat misses | Lease reaper requeues (attempts remain) or fails and dead-letters; conditional claim makes reprocessing safe |
| Queue saturates during a spike | Queue depth and oldest-message age spike | Backpressure and admission control at the edge; autoscale workers on depth and age |
| Database failover or high latency | DB latency metric; health endpoint | Connection retries and pooling; status reads degrade before writes; the queue keeps buffering |
| Downstream dependency timeout or outage | Elevated retry rate for a job type | Retryable classification, backoff with jitter, circuit breaker as a future step |
| Retry storm during an incident | Retry rate climbs across many jobs | Jitter de-synchronizes retries; capped attempts plus the dead-letter list bound the amplification |
| Notification provider outage | Notification failure rate; rising pending outbox | Outbox buffers and retries with backoff; no notifications lost, only delayed |
| Duplicate delivery | Two deliveries of one id (expected) | Conditional claim: the second UPDATE affects zero rows and the worker skips |
| Poison message (a job that always crashes the worker) | Repeated failures on one job; dead-letter growth | max_attempts routes it to the dead-letter list; alert and provide replay tooling |
| Lost publish after commit | A queued job sits with no worker pickup | Stuck-queued reaper re-publishes queued jobs older than a threshold from the database |
| Stale cancel honored late | cancellation_requested_at set on a requeued job | Claim refuses jobs with a pending cancel; worker finalizes to cancelled |

---

## 23. AI / LLM Jobs as a First-Class Workload

The company automates companies with AI, so LLM jobs are a primary workload, not a curiosity. They are long-running, non-deterministic, cost money per call, and hit provider rate limits. The reference includes an llm_summary job type that models exactly this.

Implications, each handled by an existing mechanism:
- Per-call cost plus at-least-once delivery means idempotent retries are critical: you must not pay for the same generation twice. The conditional claim and the per-job result guard ensure only one successful execution commits, even if the job runs more than once.
- Provider rate limits are a retryable failure. The llm_summary handler raises a PROVIDER_RATE_LIMIT retryable error, which flows through the same backoff-with-jitter path as any transient failure, so a rate-limited provider is backed off rather than hammered.
- Long generations need cooperative cancellation so a user can stop in-flight token generation; the worker's checkpoint checks apply directly.
- Partial progress and token streaming map onto the progress field and feed real-time status, and would feed an SSE stream when added.

---

## 24. Cost Awareness

Spikes, autoscaling, and per-call AI cost are connected, and a senior design weighs cost, not just correctness:
- Scale workers down (or to zero for idle pools) when queue depth and age are low, so you pay for capacity only when there is work.
- Cap per-worker and per-tenant concurrency to bound spend during a spike, especially for paid LLM calls.
- Prefer idempotent retries so a redelivery never triggers a second paid operation; the result guard already enforces single-commit.
- Tier expensive job types (separate pools, separate concurrency caps) so a flood of cheap jobs and a flood of expensive ones can be scaled and budgeted independently.

---

## 25. Testing and Validation Strategy

The point is to prove the hard guarantees, not assert them.
- Idempotency: inject duplicate queue deliveries of the same id and assert exactly one execution commits and attempts increments once per real claim.
- Retry and backoff: fault-inject transient failures and assert the attempt count, the retrying transitions, the backoff timing, and dead-letter routing on exhaustion.
- Cancellation: assert a running job stops at a checkpoint and lands in cancelled, and assert the race where a job finishes mid-cancel correctly lands in succeeded or failed.
- Crash recovery: kill a worker mid-job and assert the lease expires, the reaper requeues, and the stale worker's late finalize is rejected as superseded.
- Load and spike: drive synthetic spikes and assert backpressure engages and the SLOs behave as designed.
- Contract tests on the API surface; chaos and fault injection in staging against the real Postgres and Redis.

---

## 26. The Three Hardest Problems and Proposed Approaches

### Hard Problem 1: Reliable state transitions under at-least-once delivery
Why it is hard: the queue can deliver duplicates, workers crash mid-job, and the database write and the queue publish can fail independently. Exactly-once execution is not achievable.
Approach: make the database the source of truth and the sole concurrency arbiter. Every transition is a guarded conditional UPDATE whose WHERE clause encodes its precondition (claim requires queued/retrying and no pending cancel; finalize requires ownership of the lease). The transactional outbox removes the dual-write on submission. Leases plus heartbeats plus a reaper recover crashes. job_attempts and job_events make every decision auditable. The result is at-least-once execution with single-commit results, which is the honest version of "exactly-once."

### Hard Problem 2: Cancellation of running jobs
Why it is hard: you cannot safely interrupt arbitrary in-flight work from the outside, the job may finish while the cancel is in flight, and the worker may crash during cancellation.
Approach: a cancellation sub-state machine (cancelling as an intermediate state), cooperative checkpoints in handlers, the cancellation_requested_at flag that survives requeues, clear terminal-state rules (cancelling can still end in succeeded or failed), heartbeat-timeout recovery for a crash during cancel, and explicit user-facing wording that cancellation is best-effort for running jobs.

### Hard Problem 3: Handling spikes without hurting reliability or fairness
Why it is hard: high volume can overload the database, queue, workers, or downstreams; one user can monopolize capacity; retries amplify load during incidents; unbounded queues just convert overload into latency.
Approach: the queue buffers bursts, workers autoscale on depth and age, admission control and per-user quotas shed load predictably at the edge, priority lists keep urgent work moving, backoff with jitter plus capped attempts plus the dead-letter list contain retry storms, and clear SLOs and alerts make the degradation visible and bounded.

---

## 27. Alternatives Considered

Direct synchronous processing: rejected. Jobs run for minutes, so this causes API timeouts, a poor user experience, and no clean way to absorb spikes.

In-memory queue: rejected. Jobs are lost on restart, there is no durable retry, it does not scale horizontally, and it has no operational visibility.

Database-only polling queue (no Redis): viable for small scale. Pros: fewer moving parts, trivial transactions, the outbox and the queue collapse into one table. Cons: worker polling creates database contention and is less efficient at high throughput, and scaling consumption is harder. Good for an MVP, but the brief's "unpredictable spikes" pushes toward a real queue. Worth noting: the database-as-truth design here means switching the delivery mechanism later is a contained change, because the queue carries only ids.

Durable queue plus database (recommended): durable, scalable, absorbs spikes, separates state from delivery, and supports retries and a dead-letter list cleanly. Cost: more moving parts, the dual-write challenge (solved by the outbox), and a required discipline of idempotency.

Kafka or event streaming: a large-scale option, kept out of v1. Pros: very high throughput, replayability, event history. Cons: heavier operations, awkward as a task queue, and per-job control like cancellation needs extra design. Justified only if event streaming is already part of the platform or volume genuinely demands it.

---

## 28. Trade-Offs

The central trade-offs, stated as choices:
- Durability and auditability over raw latency, because the domain punishes lost or unexplainable state more than a few hundred milliseconds.
- At-least-once with idempotent processing over an illusory exactly-once, because the honest guarantee is the one you can actually keep.
- Cooperative, best-effort cancellation over guaranteed interruption, because safe interruption of arbitrary work is not possible from the outside.
- Predictable failure under overload over unbounded acceptance, because shedding some load beats degrading for everyone.
- More moving parts (queue, scheduler, two outboxes) in exchange for operability, recovery, and clean separation of concerns.

---

## 29. What I Would Build First

The MVP is essentially the accompanying reference: POST /jobs, GET /jobs, GET /jobs/{id}, GET /jobs/summary, POST /jobs/{id}/cancel, GET /jobs/{id}/events, and GET /health; PostgreSQL as the source of truth with the full state machine; Redis as the priority queue; a worker fleet with leases and heartbeats; retry with capped backoff and a dead-letter list; both outboxes (dispatch and notification); polling status with a React dashboard; structured logs and metrics; and ownership checks plus compliance-aware data handling from day one.

Not in the MVP: a weighted fair scheduler, multi-region active-active, an advanced admin dashboard, an untrusted-code sandbox, ML-based job prediction, WebSockets, and a custom workflow engine.

Why this cut: it covers every stated requirement (async submission, retries, real-time status, cancellation, notification, spike absorption) while staying small enough to understand, operate, and reason about, with the regulated-domain concerns built in rather than bolted on.

---

## 30. Future Improvements

Each with a reason it is deferred rather than dropped:
- SSE then WebSockets for richer real-time updates, once users are shown to actively watch long jobs.
- Tenant-aware fair scheduling and weighted fair queueing, once the fairness requirement is confirmed (section 4).
- A short-lived cache for hot status reads, once polling load is measured to warrant it.
- Workflow orchestration for multi-step or dependent jobs, once that product need is real.
- Per-job-type queues and pools, once workloads diverge enough in duration or cost to need isolation.
- Object storage for large payloads and results with signed URLs, once result sizes demand it.
- Circuit breakers around flaky downstreams, dead-letter replay tooling, autoscaling on queue age, and chaos testing in staging, as operational maturity grows.
- Multi-region failover, once a single-region availability target is no longer sufficient.

---

## 31. Final Summary

The design separates submission, state, execution, and notification. The API accepts and records jobs quickly and returns 202. The durable Redis queue absorbs spikes and feeds workers, while PostgreSQL remains the single source of truth for job state. Workers process jobs with leases, heartbeats, capped retries, and cooperative cancellation, and every state change is a guarded conditional UPDATE so the database itself arbitrates concurrency. The dual-write between database and queue is solved with a transactional outbox, and a scheduler runs the control loops that keep the system live: publishing, retrying, reaping crashed leases, re-publishing stuck work, expiring stale jobs, and delivering notifications through a second outbox that guarantees a user is notified once and only when the job truly finished. Users query status by polling, with SSE as the next step.

The hard parts were never the endpoints. They are correctness under at-least-once delivery, the semantics of cancelling running work, and absorbing overload without hurting reliability or fairness, all handled in a way that is auditable and compliance-aware for a healthcare and financial context.

---

# Appendix A. Data Model

PostgreSQL 16, SQLAlchemy 2.0, Alembic migrations, psycopg3. Primary keys are UUIDv7 (time-ordered, which keeps index locality for the keyset pagination). All timestamps are timezone-aware.

## jobs (state machine and lease)
| Column | Type | Notes |
|---|---|---|
| id | uuid (v7) | primary key |
| user_id | varchar(64) | tenant/owner; every query is scoped by this |
| type | varchar(40) | job type (see Appendix, job catalog) |
| status | varchar(20) | state-machine value |
| priority | varchar(10) | high / normal / low |
| payload | jsonb | normalized input; size-capped at submission |
| result | jsonb null | small result inline; large artifacts go to object storage by reference |
| error_code | varchar(64) null | last error code |
| error_message | text null | last error message (redacted in logs) |
| progress | integer | 0 to 100, check-constrained |
| attempts | integer | incremented on each claim |
| max_attempts | integer | check >= 1 |
| idempotency_key | varchar(128) null | submission idempotency |
| next_attempt_at | timestamptz null | when a retrying job becomes due |
| cancellation_requested_at | timestamptz null | set by cancel; honored across requeues |
| cancel_reason | text null | optional |
| locked_by | varchar(64) null | owning worker id (the lease holder) |
| lock_expires_at | timestamptz null | lease expiry; reaper scans this |
| heartbeat_at | timestamptz null | last heartbeat |
| dead_lettered_at | timestamptz null | set when routed to the dead-letter list |
| created_at | timestamptz | |
| queued_at | timestamptz null | |
| started_at | timestamptz null | set once on first claim (coalesced) |
| completed_at | timestamptz null | |
| updated_at | timestamptz | on-update |

Indexes:
- (user_id, created_at desc, id desc): the list-jobs keyset query.
- (status): broad status filtering.
- (status, next_attempt_at): the due-retries scan.
- (status, lock_expires_at): the expired-lease reaper scan.
- (status, queued_at): the stuck-queued reaper scan.
- unique partial (user_id, idempotency_key) where idempotency_key is not null: submission idempotency.
- check: progress between 0 and 100; max_attempts >= 1.

## job_attempts (per-execution audit)
Columns: id, job_id (fk), attempt_number, worker_id, status, started_at, completed_at, error_code, error_message. Unique (job_id, attempt_number). Purpose: distinguish a job from its attempts and debug retries and supersession.

## job_events (append-only timeline)
Columns: id, job_id (fk), event_type, from_status, to_status, detail (jsonb), created_at. Index (job_id, created_at desc, id desc). Purpose: the immutable audit trail for support and compliance.

## dispatch_outbox (DB -> queue publication)
Columns: id, job_id (fk), status (pending/published), attempts, created_at, published_at. Index (status, created_at). Purpose: the transactional outbox for submission (Appendix C).

## notification_outbox (reliable notification delivery)
Columns: id, job_id (fk), user_id, channel, destination, event_type, payload (jsonb), status (pending/sent/failed), attempts, next_attempt_at, dedupe_key, last_error, created_at, sent_at. Unique (dedupe_key); index (status, next_attempt_at). The unique dedupe_key plus insert-on-conflict-do-nothing is what makes the enqueue idempotent.

---

# Appendix B. API Surface

Flask plus flask-smorest (OpenAPI 3 / Swagger UI), marshmallow schemas. Identity is the X-User-Id header (v1 stand-in for auth, default demo-user). Ownership is enforced on every read and cancel.

## POST /jobs
Submit a job. Header: Idempotency-Key (optional, scoped per user).
Request:
```json
{ "type": "report", "payload": { "pages": 5 }, "priority": "normal", "max_attempts": 5 }
```
Response 202:
```json
{ "job_id": "0190...uuid7", "status": "pending", "status_url": "/jobs/0190...uuid7" }
```
202 is correct because processing is asynchronous. A duplicate Idempotency-Key returns the existing job. 413 if the payload exceeds the size cap; 422 on validation failure.

## GET /jobs
List the caller's jobs, cursor-paginated. Query: status, type, limit, cursor.
Response 200:
```json
{ "items": [ /* JobSchema */ ], "next_cursor": "base64...", "has_more": true }
```
The cursor is base64 over (created_at desc, id desc); see Appendix on pagination below.

## GET /jobs/{job_id}
Fetch one job (owner-scoped). 404 if not found or not owned.
```json
{
  "id": "0190...", "type": "report", "status": "running", "priority": "normal",
  "progress": 42, "attempts": 1, "max_attempts": 5,
  "result": null, "error_code": null, "error_message": null,
  "created_at": "...", "queued_at": "...", "started_at": "...", "completed_at": null, "updated_at": "..."
}
```

## GET /jobs/summary
Counts by status for the caller.
```json
{ "counts": { "running": 2, "succeeded": 17, "failed": 1 }, "total": 20 }
```

## POST /jobs/{job_id}/cancel
Request: `{ "reason": "User requested cancellation" }`.
- 200 `{ "job_id": "...", "status": "cancelled" }` when a queued/pending/retrying job is cancelled immediately.
- 202 `{ "job_id": "...", "status": "cancelling" }` when a running job's cancel is accepted (cooperative).
- 404 if not found or not owned; 409 if the job is already terminal.

## GET /jobs/{job_id}/events
The append-only timeline for one job (owner-scoped), newest first. `{ "items": [ /* events */ ] }`.

## GET /health
`{ "status": "ok", "database": "ok", "queue": "ok" }`. Reports database and queue reachability.

Job types: sleep, report, flaky, always_fail, llm_summary (section 23).

Backoff schedule (concrete, referenced from section 10): backoff = base * 2^(attempt - 1), capped at a maximum, with symmetric jitter of +/- a fixed ratio. With base 2s, ratio 0.25, cap 1800s, the unjittered series is roughly 2s, 4s, 8s, 16s, 32s, ... up to the 1800s cap, each value then shifted by up to +/-25%.

---

# Appendix C. Transactional Outbox (Detailed Flow)

Problem: submission must write the job to the database and make it visible to workers via the queue. If the database write commits but the publish fails, the job is stranded. If the publish succeeds but the database write rolls back, a worker receives an id for a job that does not exist.

Solution (dispatch_outbox), commit-then-publish:
1. In one database transaction, the API inserts the job (status pending), records a submitted event, and inserts a dispatch_outbox row (status pending). Either all three commit or none do, so there is never a job without an outbox row.
2. The scheduler's dispatch loop claims pending outbox rows (row-locked, skip-locked), and in one transaction marks each row published and transitions its job pending -> queued.
3. After that transaction commits, the loop LPUSHes the job ids to the Redis priority lists.

The ordering matters: the queue is only ever fed ids whose jobs are committed and marked queued. The remaining gap is a crash between the commit in step 2 and the LPUSH in step 3, which would leave a job queued in the database but absent from Redis.

Liveness backstop: the stuck-queued reaper scans for jobs in status queued whose queued_at is older than a threshold and re-publishes them. This makes the publish self-healing without distributed transactions. A simpler design (write database, then publish, with only a reconciliation job) is possible, but the outbox is preferred because it keeps submission atomic and the publish path idempotent.

---

# Appendix D. Python / Flask Implementation Notes

- API: stateless Flask behind gunicorn, horizontally scalable. flask-smorest provides OpenAPI and Swagger UI; marshmallow validates every input.
- Persistence: SQLAlchemy 2.0 typed models for jobs, job_attempts, job_events, dispatch_outbox, notification_outbox; Alembic migrations; psycopg3 driver; a pooled session factory.
- Delivery: Redis lists (high/normal/low) under a namespace; publish is LPUSH, consume is a single blocking BRPOP across the three keys in priority order, so priority needs no extra consumer. The dead-letter list is a fourth key.
- Process topology: API, worker, and scheduler are separate deployables (separate containers in docker-compose; separate Deployments in Kubernetes). Workers and the scheduler are plain Python processes, not tied to the web server.
- Worker model: blocking-pop, then claim via a guarded UPDATE; the handler runs outside any database transaction; a daemon heartbeat thread extends the lease; progress and cancellation checks are short, separate transactions; finalize is one guarded transaction that also enqueues the notification.
- Scheduler model: one process, one tick on a fixed interval, six idempotent loops in order: dispatch_pending, promote_due (retries), reap_expired (leases), redeliver_stuck (queued), expire_stale, dispatch_due (notifications). Every loop is safe to run repeatedly because every write is a guarded UPDATE.
- Configuration: a single Pydantic settings source (database and Redis URLs, lease and heartbeat seconds, scheduler interval and batch size, retry base/cap/jitter, payload cap, queue max age, notification cap and signing secret). No scattered constants.
- Conditional transitions: implemented as UPDATE ... WHERE <precondition> with a rowcount or RETURNING check; rowcount 0 means "lost the race, do not proceed."

---

# Appendix E. Observability Catalog

Logs (structured, PHI/PII redacted): job_id, user_id, job_type, attempt, worker_id, status transition, error code, duration. Notable events already emitted: worker.started/stopped, execution.finalize_skipped (supersession), notification.delivered/exhausted, scheduler.tick_failed.

Metrics: jobs submitted per minute; queue depth (sum of the three priority lists); dead-letter depth; oldest queued-job age; duration p50/p95/p99; success/failure/retry/cancellation rates; notification success/failure and pending-outbox age; worker utilization; heartbeat misses; supersession count.

Traces: submission (API write plus outbox insert); scheduler publish; worker execution (claim -> handler -> finalize); notification delivery.

Alerts: dead-letter depth above threshold; queue age too high; worker error rate high; notification failure rate high; database latency high; stuck running jobs (lease expired faster than the reaper clears them); pending-outbox backlog growing.

---

# Appendix F. State Transition Table

States: pending (PE), queued (QU), running (RU), retrying (RE), succeeded (SU), failed (FA), cancelling (CG), cancelled (CA), expired (EX). Y = valid (trigger noted), . = invalid. Rows are the from-state; columns are the to-state. Terminal states (SU, FA, CA, EX) have no outgoing transitions.

| from \ to | PE | QU | RU | RE | SU | FA | CG | CA | EX |
|---|---|---|---|---|---|---|---|---|---|
| PE | .  | Y1 | .  | .  | .  | .  | .  | Y2 | Y3 |
| QU | .  | .  | Y4 | .  | .  | .  | .  | Y2 | Y3 |
| RU | .  | Y5 | .  | Y6 | Y7 | Y8 | Y9 | .  | .  |
| RE | .  | Y10| .  | .  | .  | .  | .  | Y2 | .  |
| CG | .  | .  | .  | .  | Y11| Y11| .  | Y12| .  |
| SU | .  | .  | .  | .  | .  | .  | .  | .  | .  |
| FA | .  | .  | .  | .  | .  | .  | .  | .  | .  |
| CA | .  | .  | .  | .  | .  | .  | .  | .  | .  |
| EX | .  | .  | .  | .  | .  | .  | .  | .  | .  |

Triggers:
- Y1 PE->QU: scheduler dispatch publishes from the outbox.
- Y2 ->CA: cancel on a pending/queued/retrying job (immediate, row-locked).
- Y3 ->EX: expiry reaper ages out a job that never started (older than the queue max age).
- Y4 QU->RU: worker conditional claim succeeds.
- Y5 RU->QU: lease reaper requeues a crashed worker's job (attempts remain).
- Y6 RU->RE: retryable failure with attempts remaining; next_attempt_at set.
- Y7 RU->SU: handler returns successfully.
- Y8 RU->FA: non-retryable failure, exhausted retryable, or lease reaper with attempts exhausted (dead-lettered).
- Y9 RU->CG: cancel requested on a running job.
- Y10 RE->QU: retry loop promotes a due retry.
- Y11 CG->SU/FA: the job finished before it observed the cancel.
- Y12 CG->CA: worker finalized the cancellation at a safe checkpoint.

All other pairs are invalid and are rejected by the guarded UPDATEs, whose WHERE clauses permit only the from-states listed above.
