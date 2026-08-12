# Reproducible synthetic system benchmarks

`/evaluation/benchmarks` provides measured, fixed-seed evidence for FIP's transaction-processing
pipeline. It is a system benchmark, not a fraud-model accuracy benchmark.

## What one run exercises

The dedicated `benchmark` worker generates a canonical UTF-8 CSV and submits it through the same
boundaries used by an analyst upload:

1. CSV headers, values, identifiers, row count, and encoding are validated.
2. The complete import is stored as an atomic `synthetic` ingestion batch.
3. Semantic history features and deterministic rules are evaluated for every row.
4. A checksum-protected scoring-runtime observation is retained for every assessment.
5. Medium- and high-risk assessments follow the standard governed case-opening path.
6. Aggregate results and their source-set checksums are sealed in a benchmark report.

No special benchmark scorer or case rule exists. This prevents the evidence path from silently
diverging from the application path it is intended to measure.

## Reproduction contract

The generator pins its version, transaction count, seed, and configuration checksum. Those inputs
produce stable opaque synthetic identifiers, timestamps, profiles, and canonical CSV bytes. FIP
stores the dataset SHA-256 before execution and regenerates the data during integrity verification.

Run lifecycle events form an append-only checksum chain:

```text
queued -> running -> succeeded
                  -> failed -> queued (explicit administrator retry)
```

The configuration checksum makes an exact request idempotent. A stale worker lease produces a
failed event instead of leaving a run indefinitely active.

## Acceptance profile

The BRD acceptance profile is one sealed run with:

- exactly 10,000 generated transactions;
- 10,000 stored rule assessments;
- 10,000 independently verified runtime observations;
- a complete validation, ingestion, scoring, and case-routing pipeline;
- maximum measured deterministic scoring time below 2,000 milliseconds per transaction; and
- intact dataset, transaction-set, assessment-set, runtime-set, case-set, report, and event-chain
  checksums.

Runs from 100 through 9,999 rows are supported for calibration and operational checks, but cannot
satisfy the acceptance-volume gate. End-to-end elapsed time and throughput are recorded when the
worker performs the import. Per-transaction scoring time remains the acceptance latency measure.

## Evidence boundary

Every response and report states:

- `synthetic_only: true`;
- `eligible_for_operational_training: false`;
- `model_efficacy_claim: false`; and
- `changes_operational_configuration: false`.

Synthetic benchmark outcomes are excluded in both operational-dataset readiness and immutable
snapshot verification. Even an independently approved analyst outcome for a synthetic case can
never become an operational training row.

This benchmark demonstrates reproducibility, pipeline completeness, measured runtime, and
tamper-evident evidence retention. Public ULB research evidence remains the appropriate evidence
for model-development methodology. Neither source alone demonstrates institution-specific model
efficacy, which requires representative governed operational labels and temporal evaluation.

## API and roles

All authenticated roles can inspect runs and download a successful verified report:

```text
GET /api/v1/evaluation/benchmarks
GET /api/v1/evaluation/benchmarks/{run_id}
GET /api/v1/evaluation/benchmarks/{run_id}/report
```

Only administrators can queue or retry immutable configurations:

```text
POST /api/v1/evaluation/benchmarks
POST /api/v1/evaluation/benchmarks/{run_id}/retry
```

The global Evaluation Record counts only verified sealed benchmark evidence for its
`transaction_benchmark_volume` gate. Raw database volume cannot satisfy that gate.
