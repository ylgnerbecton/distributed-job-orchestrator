# AI Interaction Log

This project was built in a single session by an AI coding agent (Claude, via Claude Code). This
log records the meaningful prompts, what the agent produced, the corrections that were needed, and
an honest reflection. Nothing here is fabricated; every correction below is a problem that actually
came up during the build and was fixed before the work was considered done.

## Initial prompt

Summarized: build the Distributed Job Orchestrator described in `INSTRUCTIONS.md` and `PROJECT.md`,
to the same quality bar as the existing telemetry-hub project, and publish it as a public GitHub
repository under the user's account. The deliverable had to include real tests, pagination, an MUI
frontend, a worthy README with a Swagger screenshot and a dashboard screenshot, an Architecture
Decision Record, this interaction log, an `AGENTS.md`, and the diagrams. Every logic path and
practice had to be correct, not just the tests. `INSTRUCTIONS.md` and `PROJECT.md` must not be
published, and the AI must not appear as a Git contributor.

## Phase 1: study the reference and decide the stack

The agent read the entire telemetry-hub project (README, AGENTS, ADR, AI log, Compose, CI,
pyproject, the layered backend, the MUI frontend, the tests) to extract the exact house style and
quality bar, then made the foundational decision: build on Flask plus flask-smorest rather than
FastAPI. The brief describes a Python and Flask shop and the architecture proposal it asks for
lands concretely on Flask, so building the reference implementation in Flask keeps the proposal and
the code consistent and demonstrates fit with the stack. PostgreSQL was chosen as the source of
truth and Redis as the durable queue (delivery only), with a custom, explicit worker loop rather
than Celery so the lease, heartbeat, conditional-transition, and outbox mechanics stay visible and
testable. These choices and their deviations from the stricter house style were recorded in
`AGENTS.md`.

## Phase 2: backend

The agent generated the layered backend: config, logging, UUID7, a testable clock, the keyset
pagination codec; the five-table schema (`jobs` plus `job_attempts`, `job_events`,
`dispatch_outbox`, `notification_outbox`) and one hand-written Alembic migration with a working
downgrade; the domain layer (the status state machine, retryable and non-retryable errors, the
backoff curve, and a job-type handler catalog with cooperative cancellation checkpoints); the
repositories with the conditional state-transition UPDATEs that are the correctness core; the
services (submission with idempotency, reads with pagination, row-locked cancellation, the worker
execution service, and the scheduler services); the Redis queue abstraction with priority lists;
the flask-smorest blueprints and app factory; and the worker and scheduler entry points.

## Phase 3: parallel work and tests

While the backend was being finished, the agent dispatched three focused sub-agents in parallel to
build the React plus MUI frontend, write the full architecture proposal (`docs/DESIGN.md`), and
author the Mermaid diagrams, each against a locked API contract. The agent then wrote 47 tests
against a real PostgreSQL and a fake Redis, written to prove the hard guarantees: idempotent
submission, cursor pagination (full traversal plus malformed-cursor rejection), ownership, the
state machine, execution, retry with backoff and dead-lettering, cooperative cancellation, lease
expiry and requeue, outbox dispatch, and notification delivery with deduplication. The headline
test fires eight concurrent deliveries of one job and asserts exactly one execution.

## Corrections made during the build

These are real defects the agent introduced and then caught, mostly by running the code rather than
by reading it.

- A read service method was named `list`, which shadowed the builtin `list` used in a later type
  annotation in the same class body, so the module failed to import with `TypeError: 'function'
  object is not subscriptable`. Renamed to `list_jobs`.
- The cancel endpoint documented its 202 response with `alt_response(202, CancelResultSchema)`,
  passing the schema as the positional `response` (a named reference) instead of `schema=`, which
  made apispec fail to build the OpenAPI document. Fixed to the `schema=` keyword.
- The notification logger passed `event=...` to structlog, which collides with structlog's reserved
  positional `event` (the log message itself), raising `TypeError: got multiple values for argument
  'event'`. Renamed the field to `event_type`. Caught by the notification delivery test.
- The notification enqueue returned its result from `rowcount`, but psycopg (v3) reports
  `rowcount = -1` for `INSERT ... ON CONFLICT DO NOTHING`, so the deduplication signal was wrong
  even though the row was inserted correctly. Switched to `RETURNING ... ; first() is not None`.
  Caught by the dedupe test asserting the first enqueue returns true and the second false.
- A formatting hook ran the linter with autofix after every edit, which repeatedly removed a
  just-added import before the follow-up edit that used it had landed (this happened with
  `MessageSchema`, `RedisError`, `or_`, and `time`), surfacing as `F821` or `NameError`. Each was
  re-added once its usage was in place.
- `wsgi.py` was written at the backend root, but the Dockerfile, Compose file, and Makefile all
  referenced `app.wsgi:app` and the Dockerfile did not copy a root-level `wsgi.py`, so gunicorn
  failed to boot. Moved it into the package at `app/wsgi.py`.

## The real bug, found by running the whole system

After the tests were green, the agent brought up the full stack (API, two workers, scheduler,
PostgreSQL, Redis), submitted a batch of jobs, and watched it. The first batch processed correctly,
but a second batch sat stuck in `queued`. Inspection showed two coupled failures, both exactly the
kind of thing that breaks at 3am:

- Both workers had died on a transient `redis.exceptions.TimeoutError` from the blocking pop,
  because the consume loop was not wrapped, so a single Redis hiccup killed the process.
- With the workers down, jobs piled up in `queued`, and the stuck-queued reaper re-published every
  one of them on every scheduler tick, flooding Redis with 546 entries for 42 jobs.

The agent fixed the root causes rather than the symptoms: the worker now catches Redis errors,
backs off, and keeps running; and a `last_dispatched_at` column gives the reaper a per-job cooldown
so a stuck job is re-published at most once per window. It then re-ran the full pipeline and
confirmed the workers stayed alive, the queue stayed bounded (around 15 to 22 entries instead of
546), retries fired and resolved, and the batch drained cleanly. The dashboard and Swagger
screenshots were captured from this running stack.

## Follow-up iteration: responsive UI, admission control, and a stack review

A second prompt asked to improve the layout and make it more responsive, to keep finding and
filling gaps, and to reconsider whether Flask was the right choice.

- Responsive UI. The dashboard was rebuilt for every screen size: the status summary cards reflow
  with an auto-fit grid and carry a per-status color accent, the submit form gained a per-type
  description, the jobs panel gained status and type filters, and on phones the wide jobs table is
  replaced by a list of compact cards so nothing scrolls horizontally, with the detail dialog
  opening full screen. This was verified by capturing real screenshots at desktop, tablet, and
  phone widths, not just asserted.
- Gap filled: admission control. The brief stresses high submission volume with unpredictable
  spikes and per-user quotas, but submission was unbounded, a gap between the design and the
  implementation. Added a configurable per-user in-flight cap that returns 429 when exceeded, with
  a test. Added `.dockerignore` files as well, after noticing the frontend image's `COPY . .` would
  copy the host `node_modules` over the freshly installed one.
- The Flask question, answered honestly. Flask was kept, and this is the right call for this brief:
  the company is a Flask shop and the architecture proposal lands on Flask, so the implementation
  matches the proposal and demonstrates fit. The honest trade-off: FastAPI plus async would be a
  marginally more natural fit for I/O-bound orchestration, but the concurrency model here is
  process-based (a horizontally scalable worker fleet plus gunicorn API workers), which is exactly
  what the proposal recommends, so synchronous Flask loses nothing material; flask-smorest covers
  request validation and the generated OpenAPI and Swagger UI. Switching to FastAPI would have
  contradicted both the brief and the proposal for no real gain.
- The recurring annoyance worth recording: the repository's autofix formatter runs after every
  edit and kept removing a just-added import before the follow-up edit that used it had landed, so
  several imports had to be re-added once their usage was present. The lesson was to add the usage
  first, then the import.

## Migration to FastAPI and a real layout redesign

Two later prompts reversed earlier decisions: migrate the whole backend from Flask to FastAPI
because it is the better solution, and stop proving the dashboard is responsive with screenshots
and instead fix the screen itself so it uses space correctly.

- FastAPI migration. The backend was rewritten end to end to asynchronous FastAPI: Pydantic v2
  schemas instead of marshmallow, async SQLAlchemy 2.0 with asyncpg instead of synchronous psycopg,
  redis.asyncio instead of the sync client, async repositories and services, the worker and
  scheduler as asyncio processes (each worker runs a pool of consumer coroutines sized by
  worker_concurrency), the per-job heartbeat as an asyncio task instead of a thread, httpx for
  outbound webhooks, and FastAPI's generated OpenAPI 3.1 plus Swagger UI at /docs. Custom exception
  handlers keep the error body as `{ "message": "..." }` so the existing frontend kept working
  unchanged. The 48 tests were rewritten to pytest-asyncio plus httpx AsyncClient, including the
  eight-concurrent-deliveries exactly-once test rebuilt with asyncio.gather. All 48 pass.
- Two real bugs surfaced only when the live async stack was run, not by the unit tests. First, on
  Python 3.10 `asyncio.TimeoutError` is a distinct class from the builtin `TimeoutError`, so the
  scheduler's `except TimeoutError` did not catch its own interval timeout and the scheduler
  crashed on the first tick; the unit tests passed because they never hit that timeout, and CI runs
  on 3.12 where the two classes are merged. Second, the redis.asyncio client's `health_check_interval`
  wrapped the blocking BRPOP read with a timeout that fired after about a minute, so the worker
  logged the queue as unavailable and stopped consuming. Both were diagnosed by reading the worker
  and scheduler logs and reproducing the Redis behavior in a small script, then fixed by catching
  `asyncio.TimeoutError` explicitly (correct on 3.10 and 3.12) and dropping `health_check_interval`
  while keeping socket keepalive. The re-run drained cleanly with four jobs running in parallel per
  worker, retries firing, notifications delivered, and zero scheduler or worker errors.
- Layout redesign. The earlier responsive-plus-screenshots work missed the real problem: the screen
  wasted space. The layout was rebuilt so the jobs table is the full-width hero, job submission moved
  into a New job dialog opened from the top bar (removing the cramped sidebar column), the status
  panel became a compact full-width KPI strip with a per-status color accent, the content area was
  widened, and a plain status word replaced the empty zero-percent progress bar for jobs that are not
  running. The mobile card layout was kept.
- The earlier defense of Flask was honest given the brief (a Flask shop), but once the constraint to
  match that stack was lifted, FastAPI is the better fit for an I/O-bound orchestrator, and the owner
  was right to make that call.

## Reflection

- Where AI helped most: scaffolding a large, consistent, layered codebase quickly; writing the
  concurrency-correct SQL (conditional state transitions, partial unique indexes, the transactional
  outbox) and the tests that prove it; and parallelizing the frontend, the architecture document,
  and the diagrams against a fixed contract. The repetitive, pattern-heavy work was fast and
  uniform.
- Where AI was wrong or risky: several mistakes were the kind that only surface at runtime, not in
  review. The `list` shadowing, the structlog `event` collision, and the psycopg `rowcount = -1`
  behavior were all real and would have been silent or confusing in production. The most important
  one, the worker dying on a transient Redis error and the reaper then flooding the queue, was
  invisible in the unit tests and only appeared when the whole system ran under load.
- What needed manual verification: transaction boundaries (making sure finalize is guarded by the
  lease holder so a reaped worker cannot overwrite a requeued job), and the end-to-end behavior of
  the outbox plus reaper plus worker under real concurrency. These were run and observed, not
  reasoned about in the abstract.
- What the runtime caught that tests did not: queue flooding and worker death under sustained load.
  This is the clearest lesson of the build: green unit tests are necessary but not sufficient for a
  distributed system, and actually running it found the bug that mattered most.
- What would be improved with more time: a load test characterizing throughput under sustained
  burst, the claim-then-deliver refinement for notification delivery, and property-based tests for
  the state machine transitions.
