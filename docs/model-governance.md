# Governed shadow models

FIP can register operational model metadata and record model outputs in **shadow mode** without
changing the deterministic rule score, opening a case, blocking a transaction, or making any
financial decision. There is no active-production model state in the current system.

## Lifecycle

Each immutable model version begins as `candidate`. The permitted transitions are:

```text
candidate -> shadow -> retired
     |          |
     +--------> rejected
```

An administrator registers the candidate. Admission to `shadow` requires a different authenticated
user with the `evaluator` role. This separation of duties prevents a registrant from approving their
own artifact.

Research-purpose models cannot enter shadow mode. In particular, the ULB/OpenML model uses
undisclosed PCA components and is not compatible with the canonical transaction feature contract.
It may be recorded as research evidence, but the governance service blocks its admission.

The offline candidate-dossier workflow can replay the complete ULB experiment and export an exact
registration payload. It always marks that payload as research-only, operationally incompatible,
and not approved as operational training data. See
[`ml-candidate-dossiers.md`](ml-candidate-dossiers.md).

## Registration contract

`POST /api/v1/models` accepts immutable metadata including:

- model key, version, kind, purpose, and runtime contract;
- artifact, training dataset, and model-card SHA-256 values;
- canonical feature-set version and operational compatibility declaration;
- training-data approval state;
- comparison threshold and evaluation metrics;
- model-card reference.

The pair `(model_key, version)` is unique. An exact replay returns the existing registration; the
same key and version with different metadata returns a conflict.

Supervised candidates must use `binary-probability-v1`. Anomaly candidates must use
`anomaly-score-v1`. Before shadow admission, a supervised model must provide PR-AUC, ROC-AUC, Brier
score, recall, false-positive rate, evaluated row count, and positive-label count. An anomaly model
must provide its training row count, assumed contamination, and a checksum of its score reference
distribution.

## Shadow admission gates

`POST /api/v1/models/{model_id}/transitions` admits a candidate only when all gates pass:

- an independent evaluator authorizes the transition;
- purpose is `operational`;
- training data is approved;
- features are declared operationally compatible;
- the feature-set version exactly matches the current canonical snapshot version;
- model kind and runtime contract agree;
- a comparison threshold is present;
- required evaluation evidence exists and is within valid ranges.

`retired` and `rejected` are terminal states. Production activation is intentionally not available.

## Tamper-evident lineage

Registration metadata receives a canonical checksum. Every lifecycle event stores its sequence,
prior and next status, actor, reason, UTC timestamp, previous event checksum, and its own checksum.
The model API recomputes the complete chain and returns `lineage_verified`.

This is an application-level tamper-evident record, not a blockchain claim. There are no update or
delete endpoints for model registrations, lifecycle events, or shadow predictions.

## Shadow runtime boundary

An internal runtime must prove that its artifact checksum, feature-set version, and runtime contract
exactly match the registered model. FIP then evaluates the immutable canonical feature snapshot and
records:

- normalized score and registered comparison threshold;
- whether the score would exceed that threshold;
- up to 20 factor contributions referencing only fields in the snapshot;
- runtime latency;
- the exact lifecycle event that authorized shadow scoring;
- a checksum covering the transaction, feature snapshot, model registration, authorization event,
  output schema, score, threshold, factors, latency, and timestamp.

The internal runtime interface is deliberately not exposed as an API that accepts caller-supplied
scores. A future trusted worker or model-serving adapter will call it after verifying its artifact.

Authenticated users can inspect recorded outputs with:

```text
GET /api/v1/transactions/{transaction_id}/shadow-predictions
```

Every response states `shadow_only: true` and `affects_operational_score: false`. Exact replays for
the same model version and feature snapshot are idempotent.

Evaluators can aggregate verified predictions into immutable baseline-versus-evaluation monitoring
reports. The reports measure score and feature drift, latency, threshold rates, and rules/model
disagreement without changing model status or operational scoring. See
[`shadow-model-evaluation.md`](shadow-model-evaluation.md).

## What this feature does not claim

- No model is approved for production or real customer data.
- No public research artifact is deployable against canonical transactions.
- No shadow score changes the rules-only assessment or analyst queue.
- No automated intervention, retraining, lifecycle decision, or model promotion occurs.
- No serialized artifact is loaded from an untrusted request.
