# Data workspace

FIP uses public transaction data only for reproducible research evaluation. No reviewed public
dataset currently has the semantic compatibility required to activate a supervised model in the
operational scoring path.

## Dataset decision

1. [IEEE-CIS Fraud Detection](https://www.kaggle.com/competitions/ieee-fraud-detection) is the
   preferred research candidate because it contains real e-commerce
   transactions and retains more semantic context than ULB. Its adapter remains blocked until a
   project maintainer accepts and records the current Kaggle competition terms.
2. The [ULB credit-card fraud dataset](https://www.openml.org/d/1597) is a secondary methodology
   benchmark. Its transactions are real,
   but `V1` through `V28` are undisclosed PCA features that FIP cannot reproduce for a newly ingested
   canonical transaction.
3. The public
   [PLOS/Figshare transaction sample](https://doi.org/10.6084/m9.figshare.17030138) was rejected for
   model training. The paper reports
   60,595 transactions and 28 fraud labels, while the available historical repository files contain
   only 3,500 rows and six fraud labels; the latest repository version has no downloadable file.
4. Additional datasets must pass provenance, licensing, privacy, schema, label-quality, and
   deployable-feature review before an adapter is merged.

Production supervised scoring remains disabled until FIP has reviewed institution-owned labels or a
compatible licensed partner dataset. Deterministic operational rules use only the canonical fields
documented in [`../docs/semantic-risk-rules.md`](../docs/semantic-risk-rules.md).

## Repository policy

- Raw or prepared dataset rows are never committed.
- Every adapter must record the source URL, retrieval date, license or terms, file checksum, schema version, and preparation command.
- Training and evaluation splits must be deterministic and leakage-checked.
- Generated records are limited to small automated-test fixtures; they are never presented as model evidence.
- A dataset without confirmed reuse terms is blocked from training even if it is publicly downloadable.

Research adapters must remain isolated from operational scoring. Their future manifests and model
cards will state that boundary explicitly.
