SHELL := /bin/bash

API_DIR := apps/api
WEB_DIR := apps/web

.PHONY: install install-api install-web dev dev-api dev-web docker-up docker-down db-migrate ingest-huntsville ingest-huntsville-agendas migrate-phase3-postgres docker-migrate-phase3-postgres send-alerts lint typecheck test test-api test-web test-performance e2e build clean

install: install-api install-web

install-api:
	cd $(API_DIR) && python3 -m venv .venv && . .venv/bin/activate && python -m pip install --upgrade pip && python -m pip install -e ".[dev]"

install-web:
	npm install

dev: docker-up

dev-api:
	cd $(API_DIR) && . .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	npm --workspace $(WEB_DIR) run dev

docker-up:
	docker compose up --build

docker-down:
	docker compose down

db-migrate:
	cd $(API_DIR) && . .venv/bin/activate && alembic upgrade head

ingest-huntsville:
	cd $(API_DIR) && . .venv/bin/activate && python -m app.ingestion.cli ingest-huntsville --data-dir ../../data

ingest-huntsville-agendas:
	cd $(API_DIR) && . .venv/bin/activate && python -m app.ingestion.cli ingest-huntsville-agendas --data-dir ../../data

migrate-phase3-postgres:
	cd $(API_DIR) && . .venv/bin/activate && PHASE3_STORE_BACKEND=postgres python -m app.ingestion.cli migrate-phase3-artifacts-to-postgres

docker-migrate-phase3-postgres:
	docker compose exec -e PHASE3_STORE_BACKEND=postgres api python -m app.ingestion.cli migrate-phase3-artifacts-to-postgres

send-alerts:
	cd $(API_DIR) && . .venv/bin/activate && python -m app.ingestion.cli send-alerts

lint:
	cd $(API_DIR) && . .venv/bin/activate && ruff check .
	npm --workspace $(WEB_DIR) run lint

typecheck:
	cd $(API_DIR) && . .venv/bin/activate && mypy app
	npm --workspace $(WEB_DIR) run typecheck

test: test-api test-web

test-api:
	cd $(API_DIR) && . .venv/bin/activate && pytest

test-web:
	npm --workspace $(WEB_DIR) run test

test-performance:
	cd $(API_DIR) && . .venv/bin/activate && pytest tests/test_phase4_hardening.py

e2e:
	npm --workspace $(WEB_DIR) run e2e

build:
	npm --workspace $(WEB_DIR) run build

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf $(WEB_DIR)/dist $(WEB_DIR)/coverage
