.PHONY: install test lint typecheck check dev seed up down

install:
	uv sync --all-groups
	cd frontend && npm ci

test:
	uv run pytest -q

lint:
	uv run ruff check .
	cd frontend && npm run lint

typecheck:
	uv run mypy app
	cd frontend && npm run build

check: lint typecheck test

dev:
	uv run uvicorn app.main:app --reload

seed:
	uv run alembic upgrade head
	uv run python -m scripts.seed_data

up:
	docker compose up --build

down:
	docker compose down

