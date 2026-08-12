# Unified audit ledger

## Purpose

FIP exposes a single read-only register of the material, checksum-protected records already owned
by its domain modules. The register helps analysts and evaluators trace human decisions, rules
scoring, model evidence, grounded explanations, governed datasets, training runs, and evaluation reports without
moving or copying the source records into a second audit database.

The ledger is a projection, not a new source of truth. Case and model lifecycle events retain their
existing hash chains. Other material artifacts retain their existing content and lineage checksums.
Every displayed record is reverified through its owning module when the ledger is read.

## Endpoint and access

All authenticated roles can read:

```text
GET /api/v1/audit/ledger
```

Supported query parameters are:

| Parameter | Values | Default |
| --- | --- | --- |
| `category` | `case`, `model`, `scoring`, `explanation`, `hybrid`, `dataset`, `training`, `evaluation` | all categories |
| `integrity` | `all`, `verified`, `failed` | `all` |
| `q` | Case/model/transaction reference, actor, action, detail, or checksum text | none |
| `page` | Integer at least 1 | 1 |
| `page_size` | Integer from 1 through 100 | 25 |

The web workspace is available at `/audit`. The response and UI explicitly state that the view is
read-only and changes no operational state.

## Included records

- case-open, review, note, classification, outcome-review, and brief-link events;
- registered-model lifecycle events and immutable shadow predictions;
- deterministic scoring runtime observations;
- grounded case briefs;
- governed hybrid evidence assessments;
- operational dataset snapshots;
- candidate training-run lifecycle events; and
- immutable shadow-model evaluation reports.

Rows link back to the owning case dossier, dataset archive, model evidence, or evaluation archive.
Case-note text and raw provider output are not copied into this cross-domain index.

## Integrity semantics

A case event is marked verified only when the complete case chain and its pinned transaction,
feature, rule, outcome, and review evidence verify. A model lifecycle event is marked verified only
when the complete model registration and lifecycle chain verify. Standalone material records use
their existing domain verifier, including all required upstream lineage.

If a source record is damaged, the ledger does not hide it. The entry remains visible with
`integrity_verified: false`, appears under the failed-integrity filter, and contributes to the
failure summary. The read path never repairs, deletes, rechecksums, or replaces damaged evidence.

## Scope and scaling boundary

The MVP service merges supported domain records in memory after reading them from PostgreSQL. This
keeps verification logic inside the owning modules and is appropriate for the current bounded pilot
volume. Before high-volume production use, the projection requires a measured query plan, cursor
pagination, retention policy, and independently reviewed access controls. Those changes must
preserve the same source-ownership and fail-visible integrity semantics.
