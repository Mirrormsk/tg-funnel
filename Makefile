.PHONY: install run lint fmt test check

install:  ## зависимости + git-хуки
	uv sync
	uv run pre-commit install

run:  ## бот + планировщик + дашборд
	uv run python -m app.main

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest

check: lint test  ## то же, что в CI
