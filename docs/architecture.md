# FIP architecture

## Deployment boundaries

FIP has three runtime services:

1. A Next.js web application for analysts, managers, evaluators, and administrators.
2. A FastAPI backend implementing the business workflow and security boundaries.
3. PostgreSQL as the durable system of record.

The frontend and backend are independently built and deployed. The backend is a modular monolith for the MVP, not a combined frontend/backend application.

## Backend module boundaries

The API will evolve around these modules:

- `ingestion`: institution-independent transaction and CSV interfaces.
- `validation`: schema, type, and required-field validation.
- `features`: versioned transaction and behavioral feature snapshots.
- `rules`: deterministic fraud signals.
- `models`: versioned supervised and anomaly models.
- `scoring`: risk normalization, aggregation, and thresholds.
- `explainability`: immutable evidence packages and factor contributions.
- `llm`: provider-neutral grounded explanation generation and validation.
- `cases`: alert queues, analyst notes, and human determinations.
- `audit`: append-only hash-chained material events.
- `evaluation`: reproducible model, grounding, and latency evidence.

Modules may share a process and database while preserving explicit service, schema, and dependency boundaries. Splitting a module into a separate service requires measured scaling or isolation evidence and is not part of the MVP.

## Initial security boundary

The API issues short-lived signed access tokens and enforces the roles `administrator`, `analyst`, `manager`, and `evaluator`. Passwords are hashed with Argon2. Secrets are provided through the environment and must be replaced outside local development.

## Transaction intake boundary

The `ingestion` module owns source parsing and canonical transaction creation. CSV validation is a read-only operation; import repeats validation and writes its ingestion batch and all transactions in one database commit. The raw source checksum is unique, so an exact replay returns the original receipt without creating duplicates. An external transaction identifier cannot be reused with different data.

The browser sends raw CSV bytes through a same-origin Next.js route. That server route attaches the short-lived API credential from the `HttpOnly` session cookie, preserving the authentication boundary established by workspace entry. Public-dataset adapters will target the same canonical transaction schema rather than add dataset-specific fields to scoring modules.

## Semantic rules boundary

Every new canonical transaction receives a versioned semantic feature snapshot and deterministic
rule assessment in the same database commit as intake. Historical features use only earlier
transactions for the same account, and amount comparisons are restricted to the same currency.
Triggered rules expose their exact point contribution and evidence values.

This rules-only score is a review-priority signal, not a fraud probability or final combined risk
assessment. Public research datasets and their anonymized fields are excluded from this operational
path. The contract and limitations are documented in
[`semantic-risk-rules.md`](semantic-risk-rules.md).

## Research ML boundary

Research dataset loading, temporal splitting, model training, calibration, evaluation, artifact
checksums, and model-card generation live under `fip_api.research_ml`. This package has no import or
dependency edge from the API router, ingestion service, or operational scoring service. Its public
datasets use source-specific features and cannot register an operational model.

The same package owns an offline candidate-dossier adapter. It re-trains from a raw file that matches
the reviewed provider manifest, reproduces held-out evaluation without loading the supplied
serialized artifact, and builds a fresh checksummed artifact bundle with a schema-valid research
candidate. Dependency direction is one way: the offline adapter can use the registry input schema,
while API routing and operational scoring never import research code.

The first executable benchmark uses real ULB/OpenML transactions to validate methodology. It does
not demonstrate production efficacy because most features are undisclosed PCA components. The
dataset decision and promotion gate are documented in
[`ml-research-evidence.md`](ml-research-evidence.md).

## Governed shadow model boundary

The operational model registry stores immutable version metadata and a hash-linked lifecycle. An
administrator may register a candidate, but a different evaluator must authorize entry into shadow
mode. Research-purpose, unapproved-data, source-incompatible, wrong-feature-version, and
insufficiently evaluated models are blocked.

The `model_runtime` module installs administrator-supplied bytes into a content-addressed store only
after matching the immutable registered checksum. A shadow run re-hashes the open file before
deserialization and verifies its class, model kind, feature version, training dataset, threshold,
and runtime contract. It then scores only the operational feature allow-list and delegates immutable
recording to the shadow ledger. Predictions reference the exact feature snapshot and authorization
event and cannot modify the deterministic rule assessment. There is no production-active state or
external score-submission endpoint. See [`trusted-shadow-runtime.md`](trusted-shadow-runtime.md).

## Hybrid risk evidence boundary

The `hybrid_scoring` module reads a current verified rule assessment and two explicitly selected,
verified shadow predictions: one supervised and one anomaly. All three inputs must reference the
same immutable feature snapshot. The module applies a server-owned versioned policy, records exact
component contributions and upstream checksums, and exposes an independently verifiable combined
assessment.

Dependency direction is read-only toward rules, feature snapshots, the model registry, and the
shadow ledger. There is no dependency edge from hybrid scoring into ingestion, case mutation,
transaction action, lifecycle transition, model execution, training, or LLM generation. Missing,
mismatched, or damaged inputs block combination rather than changing weights. Case detail may
project matching hybrid evidence read-only, but hybrid creation cannot append a case event or alter
case state. See
[`hybrid-risk-evidence.md`](hybrid-risk-evidence.md).

## Shadow evaluation boundary

The `model_evaluation` module reads immutable shadow predictions, canonical feature snapshots,
deterministic rule assessments, and model lineage. It can persist a checksummed comparison report but
has no dependency edge into ingestion, deterministic scoring, lifecycle transitions, cases, or
alerts. Rules/model disagreement is explicitly comparison evidence rather than a labeled accuracy
measure. Metric definitions and initial drift heuristics are documented in
[`shadow-model-evaluation.md`](shadow-model-evaluation.md).

## Investigation case boundary

The `cases` module converts medium and high deterministic assessments into a human review queue. A
case pins the exact transaction, semantic feature snapshot, and rule assessment that caused the
review threshold to be met. Review start, notes, final classification, and label-quality review are
append-only hash-linked events; a damaged chain is readable as failed evidence but cannot be
extended through the API.

The analyst's one-time classification closes the case. A separate evaluator decision only controls
future-ML label eligibility and cannot change that classification. Inconclusive outcomes are never
training-eligible, and no cases dependency reaches into training, model registration, shadow
prediction, lifecycle transition, or transaction action code. See
[`investigation-cases.md`](investigation-cases.md).

## Operational ML dataset boundary

The `training_datasets` module reads independently approved binary case outcomes and their pinned
pre-decision feature snapshots. It exports only an explicit, identifier-free semantic feature
allow-list, assigns deterministic chronological partitions, evaluates fixed readiness gates, and
stores immutable checksummed dataset rows and manifests.

This is a one-way dependency: dataset curation may read case evidence, while the cases, ingestion,
scoring, and transaction modules never call dataset creation or training. A blocked snapshot is
valid evidence of insufficient or imbalanced labels; it cannot be represented as training-ready.
No training or model lifecycle action is triggered. See
[`operational-ml-datasets.md`](operational-ml-datasets.md).

## Operational candidate training boundary

The `operational_ml` package is an offline consumer of one ready operational dataset snapshot. It
re-verifies dataset integrity and exact feature, label, and temporal-split contracts before fitting.
Preprocessing learns only from chronological training rows; a training-tail partition is reserved
for supervised calibration, validation controls candidate selection and thresholds, and test is
evaluated once after selection.

The package creates independently checksummed supervised and anomaly artifacts, model cards,
aggregate evidence, and schema-valid registry payloads. Dependency direction remains one way: it may
read `training_datasets` and registry input schemas, while API routing, ingestion, cases, rules,
scoring, registry services, and shadow recording never invoke training. The trainer has no registry
client and no lifecycle or prediction write path. See
[`operational-candidate-training.md`](operational-candidate-training.md).

## Design system

The approved frontend direction is **Forensic Ledger**: a warm archival canvas, white evidence surfaces, compact navigation, editorial case hierarchy, and restrained risk accents. LLM output is presented as a cited case brief rather than a chat interface.
