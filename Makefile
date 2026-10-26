# Development tasks for CodeGraph AI.
#
# Windows note: these targets assume a POSIX shell (bash/sh) — Git Bash or
# WSL. From plain PowerShell/cmd.exe, run the underlying command directly
# instead, e.g. `cd backend; pytest -q` for `make test-backend`, or
# `docker compose up -d` for `make dev`.

.PHONY: help setup setup-backend setup-frontend \
        lint lint-backend lint-frontend \
        format format-backend format-frontend \
        typecheck typecheck-backend typecheck-frontend \
        test test-backend test-frontend test-unit test-integration test-e2e \
        run-backend run-frontend \
        dev up down stop logs \
        demo-seed demo-reset demo-check \
        check-env check-neo4j check-embeddings check-llm \
        clean

help:
	@echo "Available targets:"
	@echo "  setup            Install backend and frontend dependencies"
	@echo "  lint             Run Ruff (backend) and ESLint (frontend)"
	@echo "  format           Run Ruff format (backend) and Prettier (frontend)"
	@echo "  typecheck        Run mypy (backend) and tsc --noEmit (frontend)"
	@echo "  test             Run Pytest (backend) and Vitest (frontend)"
	@echo "  test-unit        Run backend unit tests only"
	@echo "  test-integration Run backend integration tests only (needs Neo4j)"
	@echo "  test-e2e         Run backend end-to-end tests only (needs Neo4j)"
	@echo "  run-backend      Run the FastAPI dev server"
	@echo "  run-frontend     Run the Vite dev server"
	@echo "  dev              Start the full stack via Docker Compose (detached)"
	@echo "  up               Alias for dev"
	@echo "  stop / down      Stop the Docker Compose stack"
	@echo "  logs             Tail Docker Compose service logs"
	@echo "  demo-seed        Import and analyze the demo repository"
	@echo "  demo-reset       Remove the demo repository from every store"
	@echo "  demo-check       Run end-to-end backend capability checks against the demo repo"
	@echo "  check-env        Run every infrastructure smoke test (Neo4j, Chroma, embeddings, LLM, ...)"
	@echo "  check-neo4j      Real Neo4j connectivity + schema smoke test"
	@echo "  check-embeddings Real embedding-model load + embed smoke test"
	@echo "  check-llm        Real LLM (Anthropic/LM Studio) connectivity + generation smoke test"
	@echo "  clean            Remove local caches, build artifacts, and virtualenvs"

setup: setup-backend setup-frontend

setup-backend:
	cd backend && python -m venv .venv
	cd backend && . .venv/bin/activate && pip install -e ".[dev]"

setup-frontend:
	cd frontend && npm install

lint: lint-backend lint-frontend

lint-backend:
	cd backend && ruff check .

lint-frontend:
	cd frontend && npm run lint

format: format-backend format-frontend

format-backend:
	cd backend && ruff format .

format-frontend:
	cd frontend && npm run format

typecheck: typecheck-backend typecheck-frontend

typecheck-backend:
	cd backend && mypy app

typecheck-frontend:
	cd frontend && npm run typecheck

test: test-backend test-frontend

test-backend:
	cd backend && pytest -q

test-frontend:
	cd frontend && npm run test

test-unit:
	cd backend && pytest tests/unit -q

test-integration:
	cd backend && pytest tests/integration -q

test-e2e:
	cd backend && pytest tests/e2e -q

run-backend:
	cd backend && uvicorn app.main:app --reload --port 8000

run-frontend:
	cd frontend && npm run dev

dev:
	docker compose up -d

up: dev

down:
	docker compose down

stop: down

logs:
	docker compose logs -f

demo-seed:
	python scripts/seed_demo_repository.py

demo-reset:
	python scripts/reset_demo.py

demo-check:
	python scripts/run_demo_checks.py

check-env:
	python scripts/check_environment.py

check-neo4j:
	python scripts/check_neo4j.py

check-embeddings:
	python scripts/check_embeddings.py

check-llm:
	python scripts/check_llm.py

clean:
	rm -rf backend/.venv backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
	rm -rf frontend/node_modules frontend/dist
