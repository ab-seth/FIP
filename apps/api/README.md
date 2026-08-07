# FIP API

FastAPI service for FIP. The package exposes liveness, database readiness, token authentication, and role-based access foundations. Domain modules are added feature-by-feature under `fip_api.modules`.

## Commands

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run fip-api-bootstrap
uv run uvicorn fip_api.main:app --reload
uv run pytest
```
