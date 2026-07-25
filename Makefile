.PHONY: install dev-api dev-web build test lint migration deploy

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

# Local development: API on :8000, Vite on :5173 proxying /api to it.
dev-api:
	cd backend && DEV_MODE=true RUN_BOT=false .venv/bin/uvicorn app.main:app --reload

dev-web:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check app tests
	cd frontend && npm run typecheck

# make migration m="add reminder flag"
migration:
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(m)"

deploy:
	docker compose up -d --build
