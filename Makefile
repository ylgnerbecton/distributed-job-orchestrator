.DEFAULT_GOAL := help
.PHONY: help up down logs backend-install backend-dev worker-dev scheduler-dev backend-test migrate seed demo frontend-install frontend-dev frontend-build lint fmt diagrams

help:
	@echo "Distributed Job Orchestrator - available commands:"
	@echo "  make up                 Start postgres, redis, backend, workers, scheduler and frontend"
	@echo "  make down               Stop all Docker Compose services"
	@echo "  make logs               Tail Docker Compose logs"
	@echo "  make backend-install    Create backend venv and install dependencies"
	@echo "  make backend-dev        Run the API with autoreload"
	@echo "  make worker-dev         Run a single worker process"
	@echo "  make scheduler-dev      Run the scheduler (outbox, retries, lease reaper, notifications)"
	@echo "  make backend-test       Run the backend test suite (needs postgres running)"
	@echo "  make migrate            Apply Alembic migrations"
	@echo "  make seed               Seed demo users and a starter set of jobs"
	@echo "  make demo               Submit a varied batch of jobs to the running API"
	@echo "  make frontend-install   Install frontend dependencies"
	@echo "  make frontend-dev       Run the frontend dev server"
	@echo "  make frontend-build     Type-check and build the frontend"
	@echo "  make lint               Lint backend (ruff) and frontend (tsc)"
	@echo "  make fmt                Format backend code with ruff"
	@echo "  make diagrams           Render Mermaid diagram sources to PNG"

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

backend-install:
	cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"

backend-dev:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker-dev:
	cd backend && .venv/bin/python -m app.workers.worker

scheduler-dev:
	cd backend && .venv/bin/python -m app.workers.scheduler

backend-test:
	cd backend && .venv/bin/pytest

migrate:
	cd backend && .venv/bin/alembic upgrade head

seed:
	cd backend && .venv/bin/python scripts/seed.py

demo:
	cd backend && .venv/bin/python scripts/submit_jobs.py

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

lint:
	cd backend && .venv/bin/ruff check .
	cd frontend && npm run lint

fmt:
	cd backend && .venv/bin/ruff format .

diagrams:
	npx -y @mermaid-js/mermaid-cli -i docs/diagrams -o docs/images
