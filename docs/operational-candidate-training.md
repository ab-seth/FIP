# Governed operational candidate training

## Purpose and boundary

FIP can train reproducible supervised and anomaly candidates from an immutable operational dataset
snapshot. This is an offline, one-way workflow. It writes checksummed evidence and schema-valid
registration payloads, but it never calls the model registry, changes a lifecycle, runs shadow
inference, changes a rule score, or performs a financial action.

The trainer lives under `fip_api.operational_ml`. It does not import the public-dataset research
package. ULB/OpenML features remain research-only and cannot enter this operational path.

## Admission checks

Training stops before preprocessing unless the selected snapshot:

- is explicitly `ready`;
- passes a fresh source, row, manifest, and dataset integrity verification;
- uses the current semantic feature, reviewed-binary-label, and chronological split contracts;
- contains exactly the identifier-free operational feature allow-list;
- has contiguous, chronological rows and ordered train, validation, and test partitions; and
- contains both binary classes in every dataset partition.

The existing 70/15/15 dataset partition is preserved. The training partition is further divided
chronologically: the final 20 percent, with a 20-row minimum, calibrates supervised probabilities
and earlier rows fit the estimators. If that chronological calibration tail or estimator partition
lacks either class, training is blocked rather than reshuffled.

## Preprocessing contract

Preprocessing learns no state from validation or test data. Numeric values receive training-only
median imputation and standardization. Categorical values use a sorted, deterministic one-hot
encoding with explicit missing and unknown categories. The fitted preprocessor is stored inside
each artifact so later trusted runtimes can apply the exact same transformation to the semantic
feature contract.

## Candidate training and selection

The supervised path compares fixed-seed balanced logistic regression and histogram gradient
boosting. Each estimator is calibrated on the chronological training tail. Validation PR-AUC is the
primary selection metric and validation Brier score is the tie-breaker. The operating threshold is
also chosen on validation under the configured maximum false-positive rate. The held-out test
partition is evaluated only after model selection.

The anomaly path fits a fixed-seed Isolation Forest on the complete training partition. Its raw
scores are converted to empirical percentiles against a checksummed training-score reference. Its
threshold is selected on validation under the same false-positive-rate constraint, followed by one
held-out test evaluation. Anomaly is a complementary novelty signal; it is not a fraud verdict.

Both paths produce semantic-feature permutation importance on validation for global diagnostics.
This evidence is not a transaction-level explanation.

## Run the trainer

Install all dependency groups and point the command at a ready snapshot by UUID or display ID:

```bash
uv sync --project apps/api --all-groups
uv run --project apps/api fip-operational-train \
  --dataset-id ODS-EXAMPLE \
  --version 2026.08.1 \
  --output-directory artifacts/operational/2026.08.1 \
  --seed 42 \
  --maximum-false-positive-rate 0.05
```

The output directory must not already exist. A successful run writes it atomically:

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

`run-manifest.json` checksums every other file. The evidence includes only governed dataset metadata,
contract versions, aggregate partition counts, configuration, metrics, and global importance—never
source foreign keys, account or transaction identifiers, reviewer identities, notes, or rationales.

## Registration handoff

Each registration payload is validated against `ModelRegistrationCreate` during bundle creation.
Submitting one remains an explicit administrator action. Registration creates only a candidate;
independent evaluator authorization, lineage checks, required metric validation, and later shadow
monitoring still apply. The bundle itself grants no lifecycle authority.

## Current evidence status

This feature implements and tests the governed training mechanism. It does not claim that FIP's
current operational label inventory is sufficient, and this repository contains no trained
operational artifact. Generated rows exist only as small automated-test fixtures and are never
presented as model evidence. A real run must start from institution-owned outcomes that independently
passed the dataset workflow.

## Limitations and next gate

- Minimum dataset readiness counts are admission safeguards, not proof of statistical sufficiency.
- Calibration, threshold behavior, subgroup performance, drift, and analyst capacity require human
  review against the actual institution and time period.
- Serialized artifacts must be stored and distributed through a trusted artifact channel before a
  shadow runtime can use them.
- The next implementation gate is a trusted, checksum-verifying shadow runtime for explicitly
  registered and evaluator-authorized artifacts; live decision use remains out of scope.
