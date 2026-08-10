# ULB credit-card research benchmark — seed 42

- Run date: 2026-08-09
- Pipeline: `fip-research-ml-v1.0.0`
- Decision: **Research evidence only; not eligible for operational promotion**

## Purpose

This benchmark verifies FIP's fraud-model training and evaluation methodology against a real public
transaction dataset. It is not evidence that the resulting model can score FIP's canonical live
transactions. The dataset's anonymized PCA features cannot be reconstructed during operational
inference.

## Dataset evidence

- Source: [OpenML dataset 1597](https://www.openml.org/d/1597), version 1
- Provider metadata license value: `Public`
- Provider MD5: `178bcf9bb1f31a3dfe12d0e577884add`
- Downloaded file SHA-256: `fdaf12730dc1fc426f318b71349f24f5c5fd00aa1152940be7e7509ae3d89d2a`
- Transactions: 284,807
- Fraud labels: 492
- Observation period: two days of European card transactions from 2013

## Temporal partitions

Equal event timestamps were kept in the same partition.

| Partition | Rows | Fraud labels | Event-time range |
| --- | ---: | ---: | ---: |
| Train | 170,888 | 360 | 0–120,396 |
| Calibration | 42,717 | 38 | 120,397–139,320 |
| Validation | 28,481 | 42 | 139,321–151,328 |
| Test | 42,721 | 52 | 151,329–172,792 |

Training, sigmoid probability calibration, selection/thresholding, and testing used their respective
partitions. The test partition was evaluated only after selecting the model and threshold.

## Candidate selection

The selection metric was validation PR-AUC. Brier score was the tie breaker. Thresholds were chosen
on validation at a maximum false-positive rate of 1%.

| Candidate | Validation PR-AUC | ROC-AUC | Brier | Recall | False-positive rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Logistic regression | 0.846857 | 0.982447 | 0.000431 | 0.928571 | 0.007877 |
| Histogram gradient boosting | 0.870925 | 0.979986 | 0.000408 | 0.928571 | 0.005169 |

Histogram gradient boosting was selected.

## Held-out test result

| Metric | Result |
| --- | ---: |
| PR-AUC | 0.737251 |
| ROC-AUC | 0.954710 |
| Brier score | 0.000425 |
| Expected calibration error | 0.000222 |
| Precision | 0.188341 |
| Recall | 0.807692 |
| F1 | 0.305455 |
| False-positive rate | 0.004242 |
| Alert rate | 0.005220 |
| True positives / false negatives | 42 / 10 |
| False positives / true negatives | 181 / 42,488 |

The selected threshold was `0.00277101602326677`. The low numeric value reflects probability
calibration under extreme class imbalance and must not be reused as an operational FIP policy.
The serialized research artifact SHA-256 was
`75e07dea9004b5fce60ff6531c470bc4e81a09f2672ac7ffac63728a0ed4bf0e`.

## Global research explanation

Permutation importance was calculated on the full validation partition with three repeats, using
PR-AUC decrease. The ten highest diagnostic values were:

| Feature | Mean PR-AUC decrease | Standard deviation |
| --- | ---: | ---: |
| V14 | 0.189797 | 0.004590 |
| V4 | 0.079417 | 0.003183 |
| V12 | 0.026034 | 0.004172 |
| V17 | 0.015554 | 0.004017 |
| V7 | 0.012573 | 0.005266 |
| V18 | 0.006808 | 0.002631 |
| V3 | 0.005494 | 0.000157 |
| V10 | 0.004459 | 0.002865 |
| V15 | 0.003010 | 0.002350 |
| V21 | 0.002904 | 0.000584 |

These values help diagnose the research estimator; the PCA component names cannot be presented as
human-readable operational reasons.

## Reproduction

```bash
uv run --project apps/api --group research fip-research-fetch-ulb \
  --output data/raw/creditcard.arff

uv run --project apps/api --group research fip-research-train \
  --dataset ulb-credit-card \
  --input data/raw/creditcard.arff \
  --output artifacts/research/ulb-seed-42 \
  --seed 42 \
  --maximum-fpr 0.01
```

Runtime used for this recorded run: Python 3.13.12, NumPy 2.5.2, and scikit-learn 1.9.0. The lockfile
pins the complete dependency graph.

## Limitations and claims boundary

- The result does not demonstrate current U.S. institutional performance, financial-loss reduction,
  production latency, fairness, cross-institution generalization, or drift resilience.
- `V1` through `V28` have no semantic meaning available to FIP and cannot support analyst-readable
  factor explanations.
- The trained artifact must never enter operational scoring. A compatible licensed or
  institution-owned dataset, shadow validation, and governance approval remain mandatory.
- These figures are FIP benchmark results and are separate from metrics reported for earlier
  academic projects or publications.
