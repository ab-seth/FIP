# FIP architecture

## Deployment boundaries

FIP has four runtime services:

1. A Next.js web application for analysts, managers, evaluators, and administrators.
2. A FastAPI backend implementing the business workflow and security boundaries.
3. PostgreSQL as the durable system of record.
4. An isolated offline candidate-training worker.

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
- `training_operations`: durable candidate-run orchestration and artifact verification.

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
checksums, and model-card generation live under `fip_api.research_ml`. Its executable pipeline has
no dependency edge from ingestion or operational scoring. The API imports only a sealed aggregate
evidence projection; it cannot execute the research model. Public datasets use source-specific
features and cannot register an operational model.

The same package owns an offline candidate-dossier adapter. It re-trains from a raw file that matches
the reviewed provider manifest, reproduces held-out evaluation without loading the supplied
serialized artifact, and builds a fresh checksummed artifact bundle with a schema-valid research
candidate. Dependency direction is one way: the offline adapter can use the registry input schema,
while API routing and operational scoring never import research code.

The first executable benchmark uses real ULB/OpenML transactions to validate methodology. It does
not demonstrate production efficacy because most features are undisclosed PCA components. The
dataset decision and promotion gate are documented in
[`ml-research-evidence.md`](ml-research-evidence.md).

The authenticated `GET /api/v1/ml/research-evidence` route exposes aggregate facts and checksums
from the completed run—never raw rows or the serialized model. The `/ml/research` frontend renders
this sealed projection and keeps the research-only, no-score, no-action, and no-promotion
constraints visible. See
[`research-ml-evidence-workspace.md`](research-ml-evidence-workspace.md).

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

## Grounded explanation boundary

The `explainability` module assembles an identifier-minimized evidence catalog from one case's pinned
rules evidence and, only when explicitly requested, one verified hybrid assessment. It checksums the
catalog and sends it through a provider-neutral JSON adapter under a server-owned, versioned prompt.
The provider has no database, scoring, case mutation, model lifecycle, training, or financial-action
interface.

Strict structured-output validation runs before display. Exact evidence references are required,
numerical claims must occur in their cited entries, and prohibited conclusions or consequential
actions fail validation. Failure selects a deterministic brief without interrupting scoring or case
review. Each result is immutable, independently re-verifiable, and recorded as a hash-linked case
event. See [`grounded-case-briefs.md`](grounded-case-briefs.md).

## Shadow evaluation boundary

The `model_evaluation` module reads immutable shadow predictions, canonical feature snapshots,
deterministic rule assessments, and model lineage. It can persist a checksummed comparison report but
has no dependency edge into ingestion, deterministic scoring, lifecycle transitions, cases, or
alerts. Rules/model disagreement is explicitly comparison evidence rather than a labeled accuracy
measure. Metric definitions and initial drift heuristics are documented in
[`shadow-model-evaluation.md`](shadow-model-evaluation.md).

## System evaluation record boundary

The `system_evaluation` module is a read-only projection over existing domain evidence. It reads
transaction and case counts, checksum-protected scoring-runtime observations, case-brief validation,
model and hybrid lineages, dataset manifests, training runs, and immutable shadow-evaluation reports.
It has no
write service and no dependency edge into ingestion, scoring execution, case mutation, model
lifecycle, training, or financial actions.

Only new deterministic assessments create runtime observations, inside the scoring transaction.
Historical timing is not reconstructed. The aggregate service re-verifies supported material
records, excludes damaged timing observations from latency statistics, assigns explicit
`not_observed` and `not_demonstrated` states, and checksums the versioned response. See
[`system-evaluation-record.md`](system-evaluation-record.md).

## Unified audit projection boundary

The `audit` module is a read-only cross-domain index. It reads material records from cases, model
governance, scoring observations, grounded explanations, hybrid evidence, operational datasets,
training runs, and model evaluation, then delegates verification back to each owning module. It does
not persist a
second ledger, rechecksum damaged evidence, or expose a mutation endpoint.

Case and model events remain hash-chained inside their domain boundaries. Other records retain
their existing content and lineage checksums. The projection deliberately keeps damaged records
visible and supports filterable, paginated inspection without changing operational state. See
[`audit-ledger.md`](audit-ledger.md).

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
aggregate evidence, and schema-valid registry payloads. `training_operations` is the control-plane
adapter: API routing may authorize and queue immutable runs, while only the separately deployed
worker invokes `operational_ml`. The API process, ingestion, cases, rules, scoring, registry services,
and shadow recording never execute training. The worker has no registry client and no lifecycle or
prediction write path. See
[`operational-candidate-training.md`](operational-candidate-training.md).

PostgreSQL stores the durable queue and checksum-linked attempt chain. The worker alone has
read/write access to candidate storage; the API has read-only access for fresh integrity checks and
authorized streaming. Completing a run cannot register or install a model. See
[`training-operations-workspace.md`](training-operations-workspace.md).

## Synthetic system-benchmark boundary

The `benchmarking` module owns a separate PostgreSQL-backed queue, fixed-seed generator, event
chain, result verifier, and report contract. Its worker submits canonical synthetic CSV bytes to the
normal ingestion service, which records `synthetic` provenance and invokes the same semantic
features, rules, runtime observation, and case-routing services used by operational intake.

The benchmark worker cannot train or register a model, change a model lifecycle, or modify scoring
configuration. The operational dataset module excludes synthetic provenance during readiness and
rechecks it during snapshot verification. The Evaluation Record accepts benchmark volume only from
one complete, checksum-verified sealed run; aggregate database volume is insufficient. See
[`reproducible-system-benchmarks.md`](reproducible-system-benchmarks.md).

## Design system

The approved frontend direction is **Forensic Ledger**: a warm archival canvas, white evidence surfaces, compact navigation, editorial case hierarchy, and restrained risk accents. LLM output is presented as a cited case brief rather than a chat interface.
