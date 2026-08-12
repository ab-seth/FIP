# FIP

Financial Integrity and Fraud Intelligence Platform (FIP) is a non-production fraud-analysis platform for reproducible transaction scoring, evidence-grounded explanations, human review, and tamper-evident decision records.

## Architecture

FIP is a modular monorepo with independently runnable and deployable services:

- `apps/web`: Next.js analyst interface.
- `apps/api`: FastAPI application with modular domain boundaries.
- `trainer`: separately deployed offline worker built from `apps/api`.
- `packages/contracts`: shared API contracts for the web application.
- `infrastructure`: deployment and environment documentation.

The frontend and backend are separate applications. The transactional backend is a modular monolith
for the MVP: ingestion, scoring, explainability, cases, audit, and evaluation remain isolated modules
inside one API deployment. CPU-heavy model training runs in a separate worker service.

Browser authentication crosses a small server-side boundary in the Next.js application. The web server exchanges credentials with the API and keeps the short-lived API token in an `HttpOnly`, `SameSite=Lax` cookie; the token is never exposed to browser JavaScript or local storage. The API enforces temporary account lockout after repeated failed sign-in attempts.

Transaction intake accepts a canonical REST payload or an analyst CSV import. CSV validation is read-only, a valid import commits atomically, and SHA-256 receipts make exact replays idempotent. The canonical fields and endpoint behavior are documented in [`docs/transaction-intake.md`](docs/transaction-intake.md).

Every newly stored transaction also receives an immutable semantic feature snapshot and transparent
deterministic rule assessment in the same commit. The rules-only score, evidence contributions,
version records, and limitations are documented in
[`docs/semantic-risk-rules.md`](docs/semantic-risk-rules.md).

Operationally compatible model versions can be registered into a governed candidate lifecycle and,
after independent evaluator approval, produce immutable shadow-only predictions. Shadow output never
changes the rules-only score or triggers a financial action. The gates and tamper-evident lineage are
documented in [`docs/model-governance.md`](docs/model-governance.md).

Verified shadow predictions can be summarized into immutable baseline-versus-evaluation drift and
latency reports. Reports are monitoring evidence only and cannot change lifecycle or transaction
state. See [`docs/shadow-model-evaluation.md`](docs/shadow-model-evaluation.md).

Registered operational artifacts can be installed into a content-addressed store and executed only
after checksum verification and independent evaluator shadow admission. The operator-triggered
runtime records immutable ML predictions and local semantic factors without changing case decisions.
See [`docs/trusted-shadow-runtime.md`](docs/trusted-shadow-runtime.md).

The `/ml/models` workspace exposes that governed handoff without collapsing its trust boundaries.
Administrators register generated candidate payloads and install matching artifacts; independent
evaluators control shadow admission; authorized operators can run advisory inference; and
evaluators can seal monitoring windows. All roles can inspect artifact status, lifecycle lineage,
checksums, and reports. See
[`docs/model-operations-workspace.md`](docs/model-operations-workspace.md).

A governed hybrid evidence service can combine one verified rule assessment with explicit
supervised and anomaly shadow predictions under the versioned 20/60/20 policy. It preserves exact
lineage and contributions, fails closed on missing or damaged inputs, and cannot change case or
transaction state. The case dossier exposes the model factors and lets authorized governance roles
assemble only an explicitly selected, verified prediction pair. See
[`docs/hybrid-risk-evidence.md`](docs/hybrid-risk-evidence.md).

Analysts can generate an immutable, cited case brief from the verified rules evidence and, when
explicitly selected, one verified hybrid assessment. Provider output is schema-checked and
fact-checked before display; unavailable or ungrounded output becomes a clearly labeled
deterministic fallback. The LLM cannot change scores, classifications, or financial state. See
[`docs/grounded-case-briefs.md`](docs/grounded-case-briefs.md).

Authenticated evaluators and operators can inspect a single read-only system evaluation record at
`/evaluation`. It distinguishes failed controls from evidence that is not observed or not yet
demonstrated, reports only captured latency, re-verifies material record integrity, and pins the
contract versions behind the snapshot. See
[`docs/system-evaluation-record.md`](docs/system-evaluation-record.md).

Medium and high deterministic assessments now open a human investigation case. Analysts can record
notes and one final classification in a tamper-evident ledger; independent evaluators control
whether a binary outcome is eligible for a future ML dataset. No feedback-driven training occurs in
this workflow. See [`docs/investigation-cases.md`](docs/investigation-cases.md).

Independently approved binary outcomes can be frozen into immutable operational dataset snapshots.
Snapshots exclude direct identifiers, use chronological partitions, expose explicit readiness
gates, and re-verify every source and row checksum. A snapshot never starts training. See
[`docs/operational-ml-datasets.md`](docs/operational-ml-datasets.md).

A separate offline trainer can consume only a ready, freshly verified snapshot and produce
reproducible supervised and anomaly candidate bundles. It uses training-only preprocessing,
chronological calibration, validation-only selection and thresholding, one held-out test evaluation,
model cards, checksummed artifacts, and schema-valid registration payloads. It never registers or
promotes a model. See
[`docs/operational-candidate-training.md`](docs/operational-candidate-training.md).

The `/ml/training` workspace provides a durable control plane for that trainer. Administrators queue
immutable configurations; a separate worker seals checksum-verified candidate bundles; and all roles
can inspect the run chain. Registration, artifact installation, and shadow admission remain explicit
later actions. See [`docs/training-operations-workspace.md`](docs/training-operations-workspace.md).

An authenticated, read-only audit workspace unifies the material records already owned by cases,
scoring, model governance, explanations, hybrid evidence, datasets, training, and evaluation. It
reuses each
domain's integrity verifier, keeps damaged evidence visible, and never creates a second source of
truth. See [`docs/audit-ledger.md`](docs/audit-ledger.md).

## Prerequisites

- Node.js 24+
- pnpm 11+
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose

## Local development

Copy the environment template:

```bash
cp .env.example .env
```

Install dependencies:

```bash
pnpm install
uv sync --project apps/api --all-groups
```

Start PostgreSQL, the API, and the web application:

```bash
docker compose up --build
```

The services are available at:

- Web: `http://localhost:3000`
- API documentation: `http://localhost:8000/docs`
- API liveness: `http://localhost:8000/health`
- API readiness: `http://localhost:8000/api/v1/health/ready`

The bootstrap account configured in `.env` can enter the workspace at `/login`. Change the example credentials before sharing any environment.

## Quality checks

```bash
make check
```

`make check` runs Python linting, type checking, tests, frontend linting, frontend type checking, and the production frontend build.

## Data policy

Raw financial datasets are never committed. Dataset adapters, checksums, license metadata, and reproducible preparation commands will be versioned in the repository. FIP uses only legally reusable public data and small generated fixtures for automated tests.

The initial real-data baseline and approval gates are documented in [`data/README.md`](data/README.md).
The executable research-only training and evidence workflow is documented in
[`docs/ml-research-evidence.md`](docs/ml-research-evidence.md). It does not participate in live
scoring.

Completed research runs can be independently replayed into checksummed, registry-ready research
candidate dossiers without deserializing the supplied artifact. See
[`docs/ml-candidate-dossiers.md`](docs/ml-candidate-dossiers.md).

Operational training is deliberately separate from those public-data research workflows. A real
operational run requires a ready institution-owned snapshot; generated fixtures are test-only and
the repository makes no claim that the current label inventory is sufficient.

## Status

The project is under active MVP development. It must not be used for real customer data, automated financial actions, or production fraud decisions.
