# FIP API

FastAPI service for FIP. The package exposes liveness, database readiness, token authentication, and role-based access foundations. Domain modules are added feature-by-feature under `fip_api.modules`.

## Commands

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run fip-api-bootstrap
uv run fip-api-backfill-rule-assessments
uv run fip-api-backfill-cases
uv run fip-operational-train --help
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

Administrators can install the exact registered artifact with
`PUT /api/v1/models/{model_id}/artifact`. After evaluator admission, administrators or evaluators
can execute checksum-verified, shadow-only inference with
`POST /api/v1/models/{model_id}/shadow-runs`. See
[`../../docs/trusted-shadow-runtime.md`](../../docs/trusted-shadow-runtime.md).

Administrators and evaluators can combine explicitly selected, verified supervised and anomaly
predictions with the pinned rules result through
`POST /api/v1/transactions/{transaction_id}/hybrid-assessments`. Authenticated users can read the
immutable evidence from the matching GET endpoint. Existing case-detail responses project any
matching hybrid records without changing the case ledger. The versioned formula, fail-closed
lineage, and non-intervention boundary are documented in
[`../../docs/hybrid-risk-evidence.md`](../../docs/hybrid-risk-evidence.md).

Evaluators can create immutable comparison reports with
`POST /api/v1/models/{model_id}/evaluations`; authenticated users can read them from the matching GET
endpoint. Drift, latency, rules-comparison, integrity, and claims boundaries are documented in
[`../../docs/shadow-model-evaluation.md`](../../docs/shadow-model-evaluation.md).

`GET /api/v1/evaluation/record` and its system-design alias `GET /api/v1/metrics` expose the same
authenticated, read-only system evidence snapshot. The response aggregates observed scoring and LLM
latency, environment volume, grounding behavior, model evidence, integrity findings, version
lineage, and latest model reports without changing operational state. See
[`../../docs/system-evaluation-record.md`](../../docs/system-evaluation-record.md).

`GET /api/v1/audit/ledger` exposes a filtered, paginated read-only projection of material case,
model, scoring, explanation, hybrid, dataset, and evaluation records. It reuses each owning module's
integrity verifier and never repairs or duplicates source evidence. See
[`../../docs/audit-ledger.md`](../../docs/audit-ledger.md).

Medium and high deterministic assessments open investigation cases. The case API supports review
start, notes, one final human classification, an append-only hash chain, and independent
future-training-label review. See
[`../../docs/investigation-cases.md`](../../docs/investigation-cases.md).

Administrators and analysts can create a cited explanation with
`POST /api/v1/cases/{case_id}/briefs`; all authenticated roles can read the immutable versions. The
provider-neutral JSON adapter, deterministic grounding validation, fallback behavior, audit record,
and non-intervention controls are documented in
[`../../docs/grounded-case-briefs.md`](../../docs/grounded-case-briefs.md).

`GET /api/v1/ml/datasets/readiness` exposes approved-label, integrity, class-balance, temporal, and
holdout gates. Administrators can freeze those sources with `POST /api/v1/ml/datasets/snapshots`;
the result excludes direct identifiers, is immutable checksummed evidence, and does not trigger training. See
[`../../docs/operational-ml-datasets.md`](../../docs/operational-ml-datasets.md).

The offline `fip-operational-train` command accepts only a ready, integrity-verified operational
snapshot. It writes reproducible supervised and anomaly candidate artifacts, evidence, model cards,
and validated registration payloads without calling the registry or executing either model. See
[`../../docs/operational-candidate-training.md`](../../docs/operational-candidate-training.md).

The offline `fip-research-verify-candidate` command re-trains a completed public-dataset experiment,
verifies its source evidence, and exports a fresh checksummed artifact bundle with a research-only
registry payload. It does not call the API or promote a lifecycle. See
[`../../docs/ml-candidate-dossiers.md`](../../docs/ml-candidate-dossiers.md).
