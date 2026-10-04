.PHONY: up down logs test lint

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

lint:
	python3 -m ruff check src tests
	python3 -m ruff format --check src tests

test: lint
	sh scripts/prepare_test_db.sh
	DATABASE_URL=postgresql+psycopg://billpilot:billpilot@localhost:5432/billpilot_test python3 -m pytest
