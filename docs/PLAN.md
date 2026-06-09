# Build Plan

Status: implemented. This is the order the vertical slice was built in and the decisions that
shaped it. The full reasoning is in `DESIGN.md`; the one-page summary is in `ADR.md`.

## Build order

1. Decisions and house rules. Picked the stack (Flask plus flask-smorest, PostgreSQL as source of
   truth, Redis as the durable queue, React plus MUI) and wrote `AGENTS.md` reconciling the strict
   house style with this external assessment, recording each deviation.
2. Foundation. Config (Pydantic `BaseSettings`), structured logging, UUID7 helper, a testable
   clock, and the keyset pagination codec.
3. Data model and migration. The `jobs` state machine table plus `job_attempts`, `job_events`,
   `dispatch_outbox`, and `notification_outbox`, with the partial unique index on
   `(user_id, idempotency_key)`, the lease and retry indexes, and the keyset pagination index. One
   hand-written Alembic migration with a working downgrade.
4. Domain. The job status enum and the valid-transition map, the retryable and non-retryable error
   types, the backoff curve, and the job-type handler catalog (sleep, report, flaky, always_fail,
   llm_summary) with cooperative cancellation checkpoints and progress reporting.
5. Repositories. Database access only, including the conditional state-transition UPDATEs that are
   the correctness core. The queue abstraction over Redis priority lists.
6. Services. Submission (with idempotency), reads (with keyset pagination), cancellation
   (row-locked), the worker execution service (claim, heartbeat, run, finalize), and the scheduler
   services (outbox dispatch, retry promotion, lease reaping, expiry, notification delivery).
7. API. Thin flask-smorest blueprints, the app factory with dependency injection points for the
   session factory and the queue, CORS, and generated OpenAPI plus Swagger UI.
8. Workers. The worker loop and the scheduler loop, both with graceful shutdown.
9. Tests. 47 tests against real PostgreSQL and a fake Redis, written to prove the hard guarantees
   rather than assert them.
10. Frontend. The React plus MUI dashboard: status summary, submit form, cursor-paginated jobs
    table with per-row cancel and a detail dialog with the event timeline.
11. Infrastructure and docs. Docker Compose (postgres, redis, api, two workers, scheduler,
    frontend), Dockerfiles, Makefile, CI, the diagrams, the screenshots, and this documentation.

## Key design decisions

- The database is the source of truth; the queue is a delivery signal. This is what makes status
  queries, cancellation, auditability, retries, and crash recovery possible. A queue cannot be
  queried by arbitrary job id, cannot have a specific message mutated, and drops messages after
  ack.
- At-least-once delivery with idempotent processing. Exactly-once execution across distributed
  workers and external dependencies is not a realistic guarantee, so every transition is a
  conditional UPDATE guarded by a row-count check, and the queue is allowed to deliver duplicates.
- Cooperative, best-effort cancellation. A queued job is cancelled immediately; a running job is
  asked to stop and finalizes at its next checkpoint, and may finish first.
- The transactional outbox solves the dual-write between the database and the queue.

## Risks and tradeoffs

- More moving parts (api, workers, scheduler, postgres, redis) in exchange for durability,
  observability, and recovery. Justified for a job orchestrator, whose whole point is asynchronous
  execution.
- A custom worker loop instead of Celery or RQ, so the lease, heartbeat, conditional-transition,
  and outbox mechanics are explicit and provable by tests rather than hidden in a framework.
- Holding the notification delivery inside one scheduler transaction is acceptable at this scale
  (single scheduler instance, default log channel); the claim-then-deliver refinement is noted as
  future work.

## Out of scope (deliberate)

Authentication, untrusted-code sandboxing, object storage for large artifacts, Server-Sent Events,
weighted fair scheduling, OpenTelemetry and Prometheus, and multi-region. Each is either scoped out
by the brief or a scale concern that would trade correctness and clarity for unused machinery. The
ADR lists what would be added first as scale grows.
