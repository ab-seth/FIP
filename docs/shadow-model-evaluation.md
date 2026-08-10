# Shadow-model evaluation and drift evidence

FIP can compare two non-overlapping windows of immutable shadow predictions and preserve the result
as a tamper-evident monitoring report. Evaluation is observational only: it cannot change a model
lifecycle, modify a transaction score, open a case, or trigger an automatic action.

## Evaluation windows

An authenticated evaluator creates a report with:

```text
POST /api/v1/models/{model_id}/evaluations
```

The request supplies a baseline start/end and evaluation start/end. All timestamps require an
explicit timezone. Windows use transaction occurrence time, include their start, exclude their end,
must not overlap, and must each contain 20 through 10,000 verified shadow predictions.

An exact replay returns the existing immutable report. Authenticated FIP users can inspect reports
with:

```text
GET /api/v1/models/{model_id}/evaluations
```

## Integrity gate

Before calculating metrics, FIP verifies:

- the registered model's complete lifecycle chain;
- each prediction checksum, artifact/feature/runtime registration relationship, and shadow
  authorization event;
- each immutable semantic feature snapshot; and
- the matching deterministic rule-assessment checksum and version.

The report stores a checksum over the ordered prediction, snapshot, rule-assessment, lifecycle, and
transaction lineage. A second checksum covers the model registration, evaluator, windows, metrics,
lineage checksum, creation time, and explicit non-operational flags. Reads re-verify the report and
all inputs that existed when it was created.

## Metrics

Each window records:

- score minimum, quartiles, 95th percentile, maximum, mean, and population standard deviation;
- model-threshold exceedance rate;
- mean, 95th-percentile, and maximum runtime latency; and
- deterministic-rules comparison counts and agreement/disagreement rates.

The rules comparison treats `high` deterministic-rule risk as a separate review signal. It is not a
fraud label, confusion matrix, accuracy measurement, or proof that either method is correct.

Between the two windows FIP records:

- model-score population stability index (PSI) using fixed probability deciles;
- mean-score and threshold-exceedance-rate changes;
- numeric-feature PSI using baseline-derived quintile boundaries;
- categorical-feature total-variation distance; and
- feature missing-rate changes.

Numeric and score drift are described as `stable` below 0.10, `watch` from 0.10 to below 0.25, and
`material` from 0.25. Categorical drift uses 0.10 and 0.20 boundaries. These are transparent initial
monitoring heuristics, not automatic policy thresholds or generally accepted proof of model decay.

## What the report does not do

- It does not evaluate fraud accuracy without reviewed outcome labels.
- It does not establish fairness, loss reduction, causal performance, or production fitness.
- It does not promote, retire, reject, or retrain a model.
- It does not combine the model score with the deterministic rule score.
- It does not alert an analyst or change case priority.

Those actions require separate human-reviewed policy, outcome evidence, and governance features.
