.PHONY: up down logs migrate seed test backend-test frontend-check build

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm -e SEED_DEMO=true api python -m app.db.seed

backend-test:
	docker compose run --rm api-test

frontend-check:
	docker compose run --rm frontend-test

test: backend-test frontend-check

build:
	docker compose build
