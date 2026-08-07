PNPM ?= pnpm
UV ?= uv

.PHONY: install dev api web lint typecheck test build check

install:
	$(PNPM) install
	$(UV) sync --project apps/api --all-groups

dev:
	docker compose up --build

api:
	$(UV) run --project apps/api uvicorn fip_api.main:app --reload --port 8000

web:
	$(PNPM) --filter @fip/web dev

lint:
	$(UV) run --project apps/api ruff check apps/api/src apps/api/tests apps/api/alembic
	$(UV) run --project apps/api ruff format --check apps/api/src apps/api/tests apps/api/alembic
	$(PNPM) lint

typecheck:
	$(UV) run --project apps/api mypy apps/api/src
	$(PNPM) typecheck

test:
	$(UV) run --project apps/api pytest apps/api/tests --cov=fip_api --cov-report=term-missing --cov-fail-under=80

build:
	$(PNPM) build

check: lint typecheck test build
