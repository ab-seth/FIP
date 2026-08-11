# Investigation cases and governed outcome labels

## Purpose

FIP opens a human-review case when the current deterministic rules-only assessment is `medium` or
`high`. Opening a case is a workflow action, not a financial action: it does not block a
transaction, contact a customer, change a score, or promote a shadow model.

The feature implements the BRD's analyst case, notes, final classification, and tamper-evident
decision history. It also records an independent quality review before a binary outcome may be
treated as eligible input to a future, separately versioned ML training dataset.

## Lifecycle

1. Transaction intake creates a versioned feature snapshot and rules-only assessment.
2. A medium assessment opens a `standard` case; a high assessment opens an `urgent` case.
3. An administrator or analyst can begin review and append evidence-based notes.
4. An administrator or analyst records exactly one final outcome:
   - `confirmed_fraud`
   - `legitimate`
   - `inconclusive`
5. The final outcome closes the case and cannot be replaced through the application.
6. For binary outcomes only, a different user with the `evaluator` role may approve or reject the
   outcome as a future-ML label. An inconclusive outcome is never training-eligible.

Administrator access to investigation actions supports the current bootstrap/demo path. It does
not bypass independent label review.

## Audit and provenance

Each case pins the exact transaction, feature snapshot, and rule assessment that caused it to open.
The opening checksum covers their immutable checksums, priority, reason, display identifier, and
timestamp.

Every material action is an append-only `CaseEvent`. Events have a per-case sequence number and
SHA-256 chain over the prior checksum, actor, timestamp, action type, and payload. The outcome and
its independent review have their own checksums. Case reads verify the complete chain and expose
`integrity_verified`; mutations stop when verification fails.

Generating a grounded case brief appends `brief_generated` with its evidence and explanation
checksums, provider and prompt lineage, and generation mode. The explanation has its own integrity
verification and cannot alter the lifecycle status derived from human case events. See
[`grounded-case-briefs.md`](grounded-case-briefs.md).

A label is `training_eligible` only when all of the following are true:

- the outcome is `confirmed_fraud` or `legitimate`;
- a different evaluator approved it;
- the complete case, evidence, outcome, review, and event chain still verifies.

Eligibility is metadata only. This feature does not export a training dataset, train a model,
retrain from feedback, or alter operational scoring.

## API

All endpoints require authentication.

| Method | Endpoint | Roles | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/cases` | Any authenticated role | List cases; optional `status` query filter. |
| `GET` | `/api/v1/cases/{case_id}` | Any authenticated role | Read transaction facts, evidence, outcome, and audit events. |
| `POST` | `/api/v1/cases/{case_id}/review` | Administrator, analyst | Mark an open case in review. |
| `POST` | `/api/v1/cases/{case_id}/notes` | Administrator, analyst | Append a note before final classification. |
| `POST` | `/api/v1/cases/{case_id}/outcomes` | Administrator, analyst | Record the immutable final classification. |
| `POST` | `/api/v1/cases/{case_id}/outcomes/{outcome_id}/review` | Evaluator | Approve or reject future-ML label eligibility. |
| `GET` | `/api/v1/cases/{case_id}/briefs` | Any authenticated role | Read immutable grounded explanation records. |
| `POST` | `/api/v1/cases/{case_id}/briefs` | Administrator, analyst | Generate a validated cited brief without changing the score or decision. |

## Existing assessments

New qualifying transactions open cases in the same database commit as ingestion. After applying the
migration, create cases for previously assessed transactions with:

```bash
uv run fip-api-backfill-cases
```

The command is replay-safe: transactions that already have a case are skipped, and low-risk
assessments do not create cases.

## Current limitations

- Case assignment, service-level timers, attachments, and external evidence stores are deferred.
- Labels remain institution-owned demonstration evidence; they are not claims of ground truth from
  a bank or card network.
- Dataset curation, temporal leakage checks, class-balance readiness, immutable manifests, and
  chronological partitions are implemented in the separate
  [`operational-ml-datasets.md`](operational-ml-datasets.md) boundary. Training, calibration, and
  model admission remain later governed features.
