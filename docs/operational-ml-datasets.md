# Governed operational ML datasets

## Purpose

FIP can freeze independently reviewed investigation outcomes into an immutable operational dataset
snapshot. The snapshot is a provenance and readiness artifact: it does not train a model, schedule
training, register a candidate, change a transaction score, or create an automated feedback loop.

This boundary converts the `training_eligible` metadata created by the investigation workflow into
a reproducible dataset contract without weakening the analyst/evaluator separation of duties.

## Source admission

An outcome is considered only when all of the following remain true at snapshot time:

- the analyst classification is `confirmed_fraud` or `legitimate`;
- a different evaluator approved the outcome for future ML use;
- the complete case, evidence, event, outcome, and review checksums still verify;
- the feature snapshot uses the current `semantic-transaction-v1.0.0` contract;
- the feature snapshot and transaction predate the analyst outcome; and
- the evaluator review existed before the requested snapshot cutoff.

Approved sources that fail integrity, feature-contract, or temporal checks are excluded and counted
as failed readiness evidence. Inconclusive and rejected outcomes never enter the candidate set.

## Feature and privacy contract

Rows contain an explicit allow-list of pre-decision semantic features. Account references, external
transaction identifiers, merchant references, case identifiers, analyst names, evaluator names,
notes, rationales, rule scores, and post-decision values are not exported as model features.

Internal foreign keys remain in PostgreSQL so FIP can re-verify provenance. API row previews are
identifier-reduced rather than claimed to be fully anonymized: they expose the allow-listed
features, event time, binary label, chronological split, source checksums, and row checksum.

Changing the allow-list requires a new feature-set contract. The current dataset cannot silently
adopt a newly added feature.

## Readiness gates

The initial MVP gates are intentionally conservative:

| Gate | Requirement |
| --- | --- |
| Source integrity | Zero approved-source integrity failures. |
| Feature compatibility | Zero feature-contract mismatches. |
| Temporal leakage | Zero post-decision feature violations. |
| Rows | At least 100 eligible labels. |
| Positive labels | At least 20 confirmed-fraud outcomes. |
| Negative labels | At least 20 legitimate outcomes. |
| Source period | At least seven calendar days. |
| Holdout coverage | Both labels in train, validation, and test partitions. |

Meeting these gates only permits a later training experiment. It is not evidence of model quality,
fairness, generalization, or production fitness. The separate operational candidate trainer still
performs chronological calibration, validation-only selection and thresholding, held-out evaluation,
diagnostic importance, and model-governance handoff. See
[`operational-candidate-training.md`](operational-candidate-training.md).

## Chronological split

Eligible rows are ordered by transaction occurrence time and immutable feature checksum, then
assigned to a deterministic 70/15/15 train/validation/test split. There is no random reshuffle.
This keeps later observations out of earlier training partitions and makes an exact source manifest
reproducible.

## Immutability and integrity

Each snapshot records:

- the feature, label, and split contract versions;
- source-review checksums and exclusion/readiness evidence;
- label and partition counts;
- one checksum per de-identified row;
- a source-manifest checksum; and
- a dataset checksum over the contract, gates, counts, manifest, and ordered row checksums.

An exact replay returns the existing snapshot. There are no update or delete endpoints. Dataset
reads re-verify the source cases, reviews, exported feature values, row checksums, manifest, counts,
splits, and dataset checksum; a damaged record remains readable with `integrity_verified: false`.

## API

All endpoints require authentication.

| Method | Endpoint | Roles | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/ml/datasets/readiness` | Any authenticated role | Inspect the live eligible-label inventory and readiness gates. |
| `GET` | `/api/v1/ml/datasets` | Any authenticated role | List immutable snapshots. |
| `GET` | `/api/v1/ml/datasets/{dataset_id}` | Any authenticated role | Read the manifest and bounded identifier-reduced row preview. |
| `POST` | `/api/v1/ml/datasets/snapshots` | Administrator | Freeze the current approved evidence at an optional cutoff. |

## Current limitations

- The labels are demonstration/institution-owned evidence, not verified card-network ground truth.
- The minimum thresholds are admission safeguards, not statistical sufficiency guarantees.
- Creating or reading a dataset still never triggers model training, artifact serialization,
  registry submission, or shadow inference.
- A separate offline command can explicitly train a ready snapshot, but external artifact storage and
  trusted shadow-runtime distribution remain deferred.
