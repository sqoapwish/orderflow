.PHONY: install format lint typecheck test test-all migration-check run up down logs

install:
	uv sync --frozen

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

typecheck:
	uv run mypy src tests

test:
	uv run pytest -m "not integration"

test-all:
	uv run pytest --cov=orderflow --cov-report=term-missing

migration-check:
	uv run alembic heads
	uv run alembic check

run:
	uv run uvicorn orderflow.main:app --reload --port 8002

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api worker

