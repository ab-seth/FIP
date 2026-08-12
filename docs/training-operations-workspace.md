# Training operations workspace

## Purpose

`/ml/training` turns the existing governed offline trainer into an observable product workflow.
An administrator can queue one immutable training configuration against a ready operational dataset;
a separate worker consumes it and seals supervised and anomaly candidate bundles. All authenticated
roles can inspect the resulting evidence.

This is a control plane around candidate generation, not automatic MLOps promotion. A successful run
does not register either model, install executable bytes in the trusted runtime, authorize shadow
execution, affect a rule score, reprioritize a case, or take a transaction action.

## Service boundary

Training does not execute inside FastAPI or a browser request. Docker Compose runs a separate
`trainer` service from the API image. The API and worker coordinate through durable PostgreSQL run
records; only the worker mounts the candidate-bundle volume read/write. The API mounts that volume
read-only so it can reverify evidence and stream authorized downloads.

Each worker claim has a time-bounded lease. If a worker dies, a later worker records the expired
attempt as failed. An administrator can explicitly retry the same immutable configuration. If a
prior worker atomically completed the bundle before losing its lease, the next attempt can recover
it only after a full checksum and contract inspection.

## Request contract

Only administrators can queue or retry training:

```http
POST /api/v1/ml/training-runs
Content-Type: application/json

{
  "dataset_id": "ODS-...",
  "candidate_version": "2026.08.1",
  "seed": 42,
  "maximum_false_positive_rate": "0.05",
  "reason": "Train the approved snapshot for independent candidate review."
}
```

The API freshly verifies dataset readiness and integrity before recording the request. The exact
dataset checksum, pipeline version, candidate version, seed, maximum false-positive rate, and
candidate-only controls form a unique configuration checksum. An exact replay returns the existing
run; reusing a version for different inputs is rejected.

Authenticated users may list and inspect run records:

```http
GET /api/v1/ml/training-runs
GET /api/v1/ml/training-runs/{run_id}
```

## Execution and evidence

The worker uses the unchanged `fip_api.operational_ml` pipeline. It reloads the pinned snapshot,
repeats every dataset and contract check, learns preprocessing only from training data, reserves the
chronological calibration tail, selects models and thresholds on validation, and evaluates the
held-out test partition once.

Each run has a checksum-linked lifecycle: `queued`, `running`, then `succeeded` or `failed`. A retry
adds `failed → queued` to the same chain and increments the attempt count only when another worker
claims it. Worker diagnostics expose a bounded error code and safe message; stack traces and paths
remain in worker logs.

A successful bundle must contain exactly:

```text
training-evidence.json
run-manifest.json
supervised/model.joblib
supervised/model-card.md
supervised/registration-payload.json
anomaly/model.joblib
anomaly/model-card.md
anomaly/registration-payload.json
```

The worker verifies every manifest checksum, both registry schemas, model kinds, runtime contracts,
dataset lineage, versions, artifact and model-card checksums, and non-intervention flags before it
marks the directory immutable and seals a bundle checksum in PostgreSQL. Reads repeat this
verification; damaged evidence remains visible with `integrity_verified: false`.

## Human handoff

All roles can download registration JSON and model cards. Only administrators can retrieve the
executable `.joblib` candidates. Downloading does not register or install anything. An administrator
must take each registration payload and matching artifact to `/ml/models`, where the existing model
registry and trusted artifact store repeat their own checks. A different evaluator must still admit
the candidate to shadow.

## Current limitations

- PostgreSQL is the durable queue; this MVP does not include autoscaling, distributed scheduling,
  cancellation, prioritization, or progress percentages.
- A worker lease is deliberately long because the current trainer does not emit heartbeats.
- Candidate artifacts use joblib and must be treated as executable; only the trusted runtime may
  deserialize them after installation and checksum verification.
- A successful run proves reproducibility and lineage for its frozen dataset, not production fraud
  efficacy, fairness, calibration stability, or readiness for automated decisions.
