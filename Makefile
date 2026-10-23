.PHONY: install test lint typecheck check dev seed up down demo demo-guided eval-baseline

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

demo:
	uv run python -m scripts.local_demo

demo-guided:
	uv run python -m scripts.local_demo --provider rules --workflow apparel --database data/local_demo/apparel-guided.db

eval-baseline:
	uv run python -m scripts.run_public_evaluation --profile baseline --resume

seed:
	uv run alembic upgrade head
	uv run python -m scripts.seed_data

up:
	docker compose up --build

down:
	docker compose down

