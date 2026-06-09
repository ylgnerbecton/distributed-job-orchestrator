# Distributed Job Orchestrator

[![CI](https://github.com/ylgnerbecton/distributed-job-orchestrator/actions/workflows/ci.yml/badge.svg)](https://github.com/ylgnerbecton/distributed-job-orchestrator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An asynchronous job processing system. Users submit jobs through an API, jobs run on a
horizontally scalable worker fleet, and users are notified when a job completes or fails. It is
built to handle high submission volume with spikes, retries with backoff, real-time status, and
cancellation mid-execution. PostgreSQL is the source of truth (a durable job state machine) and
Redis is the durable queue used for delivery only.

This is a focused technical-assessment vertical slice, not a production deployment. It
prioritizes correctness under at-least-once delivery and honest documentation over breadth. A
one-page Architecture Decision Record is in [docs/ADR.md](docs/ADR.md) and the full architecture
proposal is in [docs/DESIGN.md](docs/DESIGN.md).

## Dashboard

The React + MUI dashboard polls the API and updates live. It shows status summary cards with a
per-status color accent, a submit-job form (with a per-type description), and a cursor-paginated
jobs table that auto-polls, with status and type filters, a per-row cancel action, and a job
detail dialog that shows the event timeline.

![Dashboard](docs/images/dashboard.png)

The layout is fully responsive. On a phone the summary cards reflow to a two-column grid, the form
stacks, and the jobs table becomes a list of compact cards (no horizontal scrolling); the detail
dialog opens full screen.

![Responsive dashboard on a phone](docs/images/dashboard-mobile.png)

Interactive API documentation (Swagger UI) is served at `/docs`.

![Swagger UI](docs/images/swagger.png)

## Architecture overview

The backend is a layered Flask service. Route handlers stay thin and delegate to services, which
own transaction boundaries; repositories hold all database access; the domain layer holds enums,
the job state machine, the job-type handler catalog, and backoff. The queue and the worker fleet
sit alongside this stack (api -> services -> repositories -> domain, plus queue and workers).

![Architecture](docs/images/architecture.png)

A job moves through a strict lifecycle state machine. Every transition is validated in the domain
layer and applied with a conditional database UPDATE, so an out-of-order or duplicate transition
cannot corrupt state.

![Job lifecycle](docs/images/job-lifecycle.png)

Submission uses a transactional outbox. The job row and a dispatch-outbox row are written in one
transaction; the scheduler publishes the job to Redis only after that transaction commits, so the
durable record and the queue signal never disagree.

![Submission flow](docs/images/submission-sequence.png)

Retry and cancellation share the same conditional-transition machinery. A failed attempt is
rescheduled with exponential backoff up to a maximum attempt count and then dead-lettered;
cancellation is cooperative, flipping the job to a cancelling state that the worker observes and
honors at the next checkpoint.

![Retry and cancellation](docs/images/retry-cancellation.png)

### Data model

PostgreSQL holds the jobs table (the state machine), the job events timeline, the dispatch outbox,
and the notification outbox, plus the supporting indexes (a partial unique index on
`(user_id, idempotency_key)` and the keyset-pagination index on `(created_at desc, id desc)`).

![Data model](docs/images/data-model.png)

Diagram sources are in [docs/diagrams](docs/diagrams).

Layers (`backend/app`):

- `domain` enums, the job state machine, the job-type handler catalog, and backoff.
- `schemas` marshmallow request and response models (the API contract).
- `repositories` database access only, including conditional state-transition UPDATEs.
- `services` use-case logic and transaction boundaries.
- `api/blueprints` thin flask-smorest handlers.
- `workers` the worker loop and the scheduler.

## Tech stack

- Backend: Python, Flask, flask-smorest (OpenAPI 3 and Swagger UI), marshmallow,
  SQLAlchemy 2.0, psycopg3, Alembic, structlog, uuid-utils (UUID7), gunicorn.
- Source of truth: PostgreSQL 16.
- Durable queue: Redis 7 (priority lists).
- Frontend: React 18, TypeScript, Vite, MUI (Material UI) v6, TanStack Query v5
  (cursor pagination via `useInfiniteQuery`).
- Tests: pytest, fakeredis.
- Tooling: Ruff, Docker Compose, Makefile.

### Why PostgreSQL as the source of truth (not the queue)

Status queries, cancellation, auditability, and crash recovery all need a queryable, durable store
that holds the full state of every job. A queue cannot answer "what is the status of job X" or
"cancel job X", and it loses history once a message is consumed. PostgreSQL gives the durable job
state machine, conditional UPDATEs for safe transitions, and the indexes behind pagination and
idempotency. Redis is just the delivery signal that wakes a worker. The rationale is in
[docs/ADR.md](docs/ADR.md).

### Why Flask

Flask is the company stack, and flask-smorest adds marshmallow validation at the boundary plus a
generated OpenAPI 3 contract and Swagger UI at `/docs`. The orchestration concerns here (state
machine, outbox, worker leases) live in the service and worker layers, not the web framework, so a
focused, well-understood framework is the right fit. The rationale is in [docs/ADR.md](docs/ADR.md).

### Why polling (not WebSockets) for v1

The dashboard's status view is satisfied by short-interval polling with TanStack Query, which is
simpler, has no connection-state edge cases, and is adequate at this scale. Server-Sent Events for
push status is a later improvement, not a current need. This is revisited in
[docs/ADR.md](docs/ADR.md).

## Repository layout

```
distributed-job-orchestrator/
  backend/        Flask API, workers, Alembic migrations, tests, scripts
  frontend/       React + TypeScript + Vite dashboard
  docs/           DESIGN.md, ADR.md, PLAN.md, diagrams/, images/
  docker-compose.yml, Makefile, .env.example
  README.md
```

## Quick start with Docker Compose

Requires Docker and Docker Compose.

```bash
cp .env.example .env
make up
make demo        # or: docker compose exec backend python scripts/submit_jobs.py
```

Then open the dashboard at http://localhost:5173 (API at http://localhost:8000, docs at
http://localhost:8000/docs).

`make up` builds and starts PostgreSQL, Redis, the API (which runs `alembic upgrade head` on
start), two workers, the scheduler, and the frontend. `make demo` submits a batch of jobs so the
dashboard has something to show. Stop everything with `make down`.

If ports 5432, 6379, 8000, or 5173 are already in use, set `POSTGRES_HOST_PORT`,
`REDIS_HOST_PORT`, `BACKEND_HOST_PORT`, or `FRONTEND_HOST_PORT` in `.env` before `make up`.

## Run the backend locally

Requires Python 3.10+ and a running PostgreSQL and Redis (use
`docker compose up -d postgres redis`).

```bash
make backend-install        # python -m venv .venv && pip install -e ".[dev]"
make migrate                # alembic upgrade head
```

Then, in separate terminals:

```bash
make backend-dev            # API on http://localhost:8000
make worker-dev             # a worker
make scheduler-dev          # the scheduler
make demo                   # submit a batch of jobs
```

The backend reads configuration from environment variables or a `.env` file (see
`.env.example`). `DATABASE_URL` and `REDIS_URL` default to the local Compose services.

## Run the frontend locally

Requires Node 18+.

```bash
make frontend-install
make frontend-dev           # http://localhost:5173
```

The dashboard calls the API at `VITE_API_BASE_URL` (default http://localhost:8000).

## Run the tests

The suite runs against a real PostgreSQL and an in-memory fake Redis, so only PostgreSQL needs to
be running.

```bash
docker compose up -d postgres     # or: make up
make backend-install
make backend-test
```

The suite has 47 tests covering submission and idempotency, cursor pagination (full traversal plus
malformed-cursor rejection), ownership, the job state machine, job execution, duplicate-delivery
safety under concurrency (eight concurrent deliveries of one job produce exactly one execution),
retry with backoff and dead-lettering, cooperative cancellation, lease expiry and requeue, outbox
dispatch, and notification delivery with deduplication. All 47 pass.

`TEST_DATABASE_URL` controls the test database connection; the test database is created
automatically if it does not exist.

## API endpoints

Every request carries an `X-User-Id` header identifying the caller (default `demo-user`), and
ownership is enforced on every job resource.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Liveness check, plus database and queue checks |
| POST | `/jobs` | Submit a job; returns 202; accepts an `Idempotency-Key` header; returns 429 when the caller is over the per-user in-flight quota |
| GET | `/jobs` | List the caller's jobs (cursor-paginated); filters: `status`, `type`, `limit`, `cursor` |
| GET | `/jobs/{job_id}` | Full job status |
| GET | `/jobs/summary` | Counts by status |
| POST | `/jobs/{job_id}/cancel` | Request cancellation; 200 if cancelled, 202 if cancelling, 409 if terminal |
| GET | `/jobs/{job_id}/events` | The job event timeline |

### Pagination

`GET /jobs` uses keyset (cursor) pagination ordered by `(created_at desc, id desc)`, which stays
fast as the table grows because it never uses `OFFSET`. The response is a generic envelope:

```json
{
  "items": [ ... ],
  "next_cursor": "base64...",
  "has_more": true
}
```

Pass `next_cursor` back as the `cursor` query parameter to fetch the next page; `has_more` is
`false` and `next_cursor` is `null` on the last page. A malformed cursor returns `400`. The
dashboard consumes this with TanStack Query's `useInfiniteQuery` and a Load older control.

## Job types

These run trusted server-side handlers, not untrusted user code.

| Type | Behavior |
| --- | --- |
| `sleep` | Long-running job that reports progress and is cancellable |
| `report` | Multi-step report generation that produces a small result |
| `flaky` | Fails a configurable number of times, then succeeds, to exercise retries |
| `always_fail` | A non-retryable validation failure |
| `llm_summary` | Simulates a language-model call: long-running, models a provider rate limit as a retryable error, and retries idempotently so a paid call is not repeated on success |

## Correctness guarantees

Each guarantee names the mechanism and the test that proves it.

- Idempotent submission. An `Idempotency-Key` scoped per user returns the same job. A partial
  unique index on `(user_id, idempotency_key)` plus an `IntegrityError` fallback make it race-safe.
- Exactly-once effect under at-least-once delivery. A job is claimed with a conditional UPDATE
  (`status IN (queued, retrying)` with a row-count check), so duplicate queue deliveries or
  concurrent workers never double-run a job. Proven by a test that fires eight concurrent
  deliveries of one job and asserts exactly one execution.
- Crash recovery. Workers hold a time-boxed lease and heartbeat to extend it; a scheduler reaper
  requeues or fails jobs whose lease has expired.
- Dual-write safety. The job row and a dispatch-outbox row are written in one transaction (the
  transactional outbox), and the scheduler publishes to Redis after commit, with a stuck-queued
  reaper as the backstop.
- Reliable notifications. A notification-outbox row is written in the same transaction as the
  terminal state change, delivered with backoff retries, and deduplicated by a unique key per
  `(job, event)` so a user is never notified twice.

To be precise: the system is at-least-once with idempotent processing, never exactly-once
execution.

## Configuration

All configuration is environment-driven (`.env`, see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://orchestrator:orchestrator@localhost:5432/job_orchestrator` | Source-of-truth database |
| `REDIS_URL` | `redis://localhost:6379/0` | Durable delivery queue |
| `API_HOST`, `API_PORT` | `0.0.0.0`, `8000` | API bind address |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed CORS origin(s), comma-separated |
| `WORKER_LEASE_SECONDS` | `60` | How long a worker's lease on a job lasts |
| `WORKER_HEARTBEAT_SECONDS` | `15` | How often a worker extends its lease |
| `SCHEDULER_INTERVAL_SECONDS` | `2` | Scheduler loop interval |
| `JOB_DEFAULT_MAX_ATTEMPTS` | `5` | Default attempt limit before dead-lettering |
| `JOB_MAX_PAYLOAD_BYTES` | `65536` | Maximum accepted job payload size |
| `JOB_QUEUE_MAX_AGE_SECONDS` | `3600` | Age after which a pending or queued job is expired |
| `MAX_IN_FLIGHT_JOBS_PER_USER` | `200` | Admission-control cap; submissions beyond it return 429 |
| `RETRY_BASE_SECONDS` | `2.0` | Base delay for exponential backoff |
| `NOTIFICATION_MAX_ATTEMPTS` | `8` | Notification delivery attempt limit |
| `VITE_API_BASE_URL` | `http://localhost:8000` | API base URL used by the frontend |

## Known limitations

- No real authentication (out of scope per the brief). Caller identity comes from an `X-User-Id`
  header and ownership is enforced. CORS is restricted to the configured origin.
- Job handlers are trusted server-side code, not a sandbox for running untrusted code.
- Results and payloads are stored inline as JSONB (small by design). Large artifacts would go to
  object storage.
- Single-region, single-instance scheduler in v1. The worker fleet scales horizontally.
- Tests require a running PostgreSQL; the queue is faked in tests by design.

## Future improvements

See [docs/ADR.md](docs/ADR.md) and [docs/DESIGN.md](docs/DESIGN.md) for the full discussion. In
short: Server-Sent Events for push status, tenant-aware fair scheduling and quotas, object storage
for large payloads and results, a full observability stack (OpenTelemetry, Prometheus), real
authentication via a JWT identity provider, multi-region failover, and DLQ replay tooling.
