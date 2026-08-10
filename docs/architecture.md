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

## Design system

The approved frontend direction is **Forensic Ledger**: a warm archival canvas, white evidence surfaces, compact navigation, editorial case hierarchy, and restrained risk accents. LLM output is presented as a cited case brief rather than a chat interface.
