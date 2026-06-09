# AGENTS.md

Operating rules for AI agents and human contributors working in this repository.
This project is a focused technical-assessment vertical slice, not a production platform
service. These rules adapt a stricter house style to that reality.

## What this project is

Distributed Job Orchestrator: an asynchronous job processing system. Users submit jobs through
an HTTP API, jobs run on a horizontally scalable worker fleet, and users are notified when a job
completes or fails. The backend is Flask plus flask-smorest plus SQLAlchemy 2.0 on PostgreSQL,
with Redis as the durable queue. The frontend is React plus TypeScript plus Vite plus MUI plus
TanStack Query. Realtime status is polling. The full specification lives in `INSTRUCTIONS.md` and
`PROJECT.md` at the repository root (kept local, not republished); that specification is the
contract and wins any conflict about product behavior or API shape. The architecture reasoning
lives in `docs/DESIGN.md` and `docs/ADR.md`.

## Code quality rules (always apply)

These are non-negotiable in every file and every language.

- No comments, docstrings, or JSDoc. The only exception is the `Why this change is needed`
  block at the top of an Alembic migration.
- No emojis. No em-dash or en-dash characters. Use a plain hyphen, comma, or parentheses.
  Use the ASCII `->` only when a literal arrow is required.
- English-only identifiers. No filler prepositions (`function_value`, not
  `function_with_value`). No fluff prefixes or suffixes (`Enhanced`, `New`, `V2`, `Temp`,
  `Manager`, `Helper`, `Utils`) without real domain meaning.
- Booleans use `is_`, `has_`, `can_`, `should_`. Counters end in `_count` or `_total`.
- Acronyms stay uppercase in PascalCase and SCREAMING_SNAKE_CASE (`HTTPClient`, `UUID`,
  `API_BASE_URL`) and lowercase in snake_case (`http_client`, `api_base_url`).
- No magic numbers or hardcoded URLs, paths, timeouts, or limits. Backend runtime configuration
  lives in `backend/app/core/config.py` (Pydantic `BaseSettings`). Frontend polling intervals,
  the API base URL, and the user identity live in `frontend/src/config.ts`.
- Enumerations use `Enum` (Python) or string-literal unions (TypeScript), never loose string
  constants.
- No placeholder markers (`TODO`, `FIXME`, `HACK`, `XXX`) in committed code.
- No dead code, no unused imports, no commented-out code.
- No `print`, `console.log`, `debugger`, or stray debug logging in committed code. Scripts
  (seed, submitter) log through a configured logger, which is intentional output.
- No `any` in TypeScript. No untyped parameters in Python (see the test note under deviations).
  Every function has an explicit return type. Every nullable value is handled explicitly.
- All imports at module top. No imports inside functions or methods except a `TYPE_CHECKING`
  block to break a genuine import cycle.
- External input is validated with marshmallow (backend) or typed parsing (frontend).
- SQL is parameterized through SQLAlchemy. No string concatenation into queries.
- No secrets in code or Compose. Use `${VAR}` passthrough and `.env` (git-ignored). Only
  `.env.example` is committed.
- Commits follow Conventional Commits. One logical change per commit.

## Architecture rules

- Layered backend (`backend/app`): `domain` (enums, the job state machine, the job-type handler
  catalog, backoff, errors), `schemas` (marshmallow request and response models), `repositories`
  (database access only, including the conditional state-transition UPDATEs), `services`
  (use-case logic and transaction boundaries), `api/blueprints` (thin flask-smorest handlers),
  `workers` (the worker loop and the scheduler), `queue` (the Redis delivery abstraction).
- Route handlers stay thin. Transaction-sensitive logic lives in services, never in handlers.
- Repositories never own transactions. Services own transaction boundaries
  (`with session.begin()`), so a use case commits exactly once.
- The database is the source of truth for job state. The Redis queue is a delivery mechanism, not
  the source of truth. A queue message is a signal to execute a job, never the only record of it.
- Business logic never lives inside SQLAlchemy models.
- UUID7 (via `uuid_utils`) for all generated UUID primary keys. Never UUID4.
- Timezone-aware datetimes, stored in UTC. Time is read through `app.core.clock.now`.
- Structured logging via `structlog`.

## Concurrency and correctness rules (the heart of this project)

- Job state transitions are conditional UPDATE statements with a row-count check
  (`UPDATE jobs SET status='running' ... WHERE id=:id AND status IN ('queued','retrying')`).
  Never read a status into Python, branch, then write it back. The row-count is the gate that
  makes duplicate at-least-once deliveries and concurrent workers safe.
- A worker claims a job by transitioning it to `running` with a `locked_by` and a
  `lock_expires_at` lease, then a background thread heartbeats to extend the lease. Every finalize
  (succeeded, failed, retrying, cancelled) is guarded by `locked_by` so a superseded worker cannot
  overwrite a reaped job.
- Submission writes the job row and a `dispatch_outbox` row in one transaction (the transactional
  outbox), and the scheduler publishes to Redis after commit. A stuck-queued reaper re-publishes
  from the database as the backstop, so the queue is never the system of record.
- Terminal transitions write a `notification_outbox` row in the same transaction, deduplicated by
  a unique key per (job, event), so a user is never notified twice.
- Execution is at-least-once with idempotent processing. Never claim exactly-once execution.
- Every concurrency or correctness guarantee has a test that exercises it against real PostgreSQL.

## Deliberate deviations from the stricter house style

This repository is an external assessment, not a platform service. The following platform mandates
are intentionally not applied here, because the assessment specification defines a different
contract or scopes the concern out. Each deviation is a reasoned decision, recorded so reviewers
understand it was a choice, not an oversight.

- The stack is Flask plus flask-smorest (synchronous WSGI), not FastAPI plus async. The brief
  targets a Python and Flask shop, and the architecture proposal in `docs/DESIGN.md` lands on
  Flask, so the reference implementation is built on Flask to keep the proposal and the code
  consistent and to demonstrate fit with the stack. Concurrency comes from running multiple API,
  worker, and scheduler processes, which is the model the proposal recommends. This is the one
  place the platform "async on every I/O path" mandate does not apply.
- API request and response validation uses marshmallow, which flask-smorest is built on. Pydantic
  is still used for typed configuration (`pydantic-settings`). Domain objects are plain typed
  Python classes and dataclasses.
- Database access uses synchronous SQLAlchemy 2.0 with the `psycopg` (v3) driver, not asyncpg.
- No authentication. The specification scopes authentication out. Caller identity comes from an
  `X-User-Id` header (default `demo-user`) and ownership is enforced on every read and cancel.
  CORS is still restricted to the configured frontend origin (no wildcard).
- Single-resource and bounded responses use explicit shapes; list endpoints use a generic
  `{ items, next_cursor, has_more }` envelope with keyset pagination. There is no generic
  `ApiResponse[T]` wrapper.
- Status-like columns are stored as strings and validated by Python `Enum` plus marshmallow, with
  no native PostgreSQL enum types, which keeps migrations simple while staying type-safe at the
  boundary.
- No OpenTelemetry and no Prometheus in v1. The specification lists an observability stack as a
  future improvement and asks not to overengineer. structlog provides structured logs today. This
  is documented in the ADR.
- pytest fixture parameters are typed at their source (the fixture return annotations in
  `conftest.py`) rather than repeated at every test signature. All non-fixture functions and all
  return types are explicitly annotated.

## Working agreement

- Read `INSTRUCTIONS.md` and `PROJECT.md` before changing behavior.
- Run validation after changes: `ruff` for lint, `pytest` for the backend, `tsc` plus
  `vite build` for the frontend.
- Never claim tests pass without running them. If a test cannot run, document why in the README
  under Known limitations.
- Keep the README, ADR, AI interaction log, and diagrams truthful and current.
