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

`POST /api/v1/models` and `POST /api/v1/models/{model_id}/transitions` manage immutable candidate and
shadow model metadata under role and compatibility gates. Recorded shadow outputs are available at
`GET /api/v1/transactions/{transaction_id}/shadow-predictions`; they never alter rule assessments.
See [`../../docs/model-governance.md`](../../docs/model-governance.md).

The offline `fip-research-verify-candidate` command re-trains a completed public-dataset experiment,
verifies its source evidence, and exports a fresh checksummed artifact bundle with a research-only
registry payload. It does not call the API or promote a lifecycle. See
[`../../docs/ml-candidate-dossiers.md`](../../docs/ml-candidate-dossiers.md).
