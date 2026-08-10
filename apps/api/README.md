# FIP API

FastAPI service for FIP. The package exposes liveness, database readiness, token authentication, and role-based access foundations. Domain modules are added feature-by-feature under `fip_api.modules`.

## Commands

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run fip-api-bootstrap
uv run fip-api-backfill-rule-assessments
uv run uvicorn fip_api.main:app --reload
uv run pytest
```

New transactions are atomically assigned a versioned semantic feature snapshot and deterministic
rules-only assessment. See [`../../docs/semantic-risk-rules.md`](../../docs/semantic-risk-rules.md)
for the feature, rule, score-band, and API contracts.
