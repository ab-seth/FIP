# Data workspace

FIP will train and evaluate its initial fraud models with public transaction datasets rather than generated training data.

## Dataset order

1. The anonymized ULB credit-card fraud dataset is the primary baseline because it contains real transactions, a documented fraud label, and a manageable schema for the first reproducible pipeline.
2. IEEE-CIS Fraud Detection is an optional second adapter for broader identity and e-commerce signals, subject to confirming that its current competition terms permit the intended use.
3. Additional datasets must pass provenance, licensing, privacy, schema, and label-quality review before an adapter is merged.

## Repository policy

- Raw or prepared dataset rows are never committed.
- Every adapter must record the source URL, retrieval date, license or terms, file checksum, schema version, and preparation command.
- Training and evaluation splits must be deterministic and leakage-checked.
- Generated records are limited to small automated-test fixtures; they are never presented as model evidence.
- A dataset without confirmed reuse terms is blocked from training even if it is publicly downloadable.

The ingestion and model batches will add executable adapters and manifests under this directory after the corresponding feature mockups and implementation plan are approved.
