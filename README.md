# FIP

Financial Integrity and Fraud Intelligence Platform (FIP) is a non-production fraud-analysis platform for reproducible transaction scoring, evidence-grounded explanations, human review, and tamper-evident decision records.

## Architecture

FIP is a modular monorepo with independently runnable and deployable services:

- `apps/web`: Next.js analyst interface.
- `apps/api`: FastAPI application with modular domain boundaries.
- `packages/contracts`: shared API contracts for the web application.
- `infrastructure`: deployment and environment documentation.

The frontend and backend are separate applications. The backend is a modular monolith for the MVP: ingestion, scoring, explainability, cases, audit, and evaluation remain isolated modules inside one API deployment.

Browser authentication crosses a small server-side boundary in the Next.js application. The web server exchanges credentials with the API and keeps the short-lived API token in an `HttpOnly`, `SameSite=Lax` cookie; the token is never exposed to browser JavaScript or local storage. The API enforces temporary account lockout after repeated failed sign-in attempts.

Transaction intake accepts a canonical REST payload or an analyst CSV import. CSV validation is read-only, a valid import commits atomically, and SHA-256 receipts make exact replays idempotent. The canonical fields and endpoint behavior are documented in [`docs/transaction-intake.md`](docs/transaction-intake.md).

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

## Status

The project is under active MVP development. It must not be used for real customer data, automated financial actions, or production fraud decisions.
