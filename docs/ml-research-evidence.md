# ML research and evidence boundary

FIP includes a reproducible machine-learning pipeline for research evaluation. It is intentionally
separate from the operational API and does not register a production model, alter a transaction
score, create a case, or make an automated financial decision.

## Current dataset decision

The first executable benchmark uses OpenML dataset 1597, the ULB credit-card fraud dataset. It
contains 284,807 real transactions and 492 fraud labels. OpenML marks the dataset license value as
`Public`. The source file is pinned by the provider MD5 and each run records its own SHA-256.

This dataset is useful for validating imbalanced-classification methodology, but it is not eligible
for operational scoring. Features `V1` through `V28` are confidential PCA transformations and
cannot be generated for new FIP transactions. A successful result therefore demonstrates the
training and evaluation process, not deployable FIP efficacy.

IEEE-CIS remains the preferred semantically richer research candidate. Its adapter and download
remain blocked until a project maintainer explicitly accepts and records the current Kaggle
competition terms. Neither public dataset may be connected to live scoring.

The machine-readable decisions live in `data/manifests/`.

## Reproducible run

Fetch the pinned OpenML file into the ignored raw-data workspace:

```bash
uv run --project apps/api --group research fip-research-fetch-ulb \
  --output data/raw/creditcard.arff
```

Run the experiment into the ignored artifact workspace:

```bash
uv run --project apps/api --group research fip-research-train \
  --dataset ulb-credit-card \
  --input data/raw/creditcard.arff \
  --output artifacts/research/ulb-seed-42 \
  --seed 42 \
  --maximum-fpr 0.01
```

The output directory is created atomically and contains:

- `metrics.json`: configuration, partition facts, validation results, and one held-out test result.
- `model.joblib`: selected research estimator, probability calibrator, and threshold.
- `model-card.md`: intended use, result, dataset limitations, and promotion decision.
- `run-manifest.json`: checksums of all evidence files.

An existing output directory is never overwritten.

The first verified full-data result is recorded in
[`evidence/ulb-credit-card-v1-seed-42.md`](evidence/ulb-credit-card-v1-seed-42.md). The recorded report
contains metrics and source checksums, but never the raw rows or serialized model.

## Leakage and evaluation controls

The pipeline applies these controls:

1. Rows are stably ordered by event time.
2. Equal timestamps never cross partition boundaries.
3. Training, probability calibration, model selection, and final testing use four separate temporal
   partitions.
4. Logistic regression and histogram gradient boosting are trained with balanced sample weights.
5. Selection uses validation precision-recall area under the curve, with Brier score as the tie
   breaker.
6. The review threshold is selected on validation data at a configured maximum false-positive
   rate.
7. The test partition is evaluated only after model and threshold selection.
8. Accuracy is not used as the headline metric for this severely imbalanced dataset.

Generated records are permitted only inside automated tests and are never included in model
evidence.

## Promotion gate

A research artifact cannot be promoted into the operational scorer. Production supervised scoring
requires all of the following:

- institution-owned labels or a compatible licensed partner dataset;
- canonical features available identically during training and transaction-time inference;
- label provenance, leakage review, segment and temporal evaluation, and calibration evidence;
- shadow-mode latency and drift evidence;
- model governance approval and a documented rollback path.
