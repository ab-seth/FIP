# System evaluation record

## Purpose

FIP exposes one read-only, checksum-protected view of the evidence currently available to support
system-performance and reproducibility claims. It combines observed transaction volume,
deterministic-scoring latency, grounded-explanation behavior, model monitoring evidence, record
integrity, and the version lineage needed to interpret the snapshot.

This is environment evidence, not a certification. A small pilot cannot be presented as a 10,000
transaction benchmark, and a system without historical timing observations cannot report invented
latency.

## Endpoints and access

All authenticated roles can read the same snapshot:

```text
GET /api/v1/evaluation/record
GET /api/v1/metrics
```

`/metrics` is a compatibility alias for the BRD/system-design endpoint. Both routes execute the same
service and return the same schema and checksum for unchanged evidence. The evaluator workspace is
available at `/evaluation` in the web application.

The read path does not append an audit event, mutate a case, trigger inference, create an evaluation
report, train a model, transition model lifecycle state, reprioritize a review, or take a financial
action. The response records `read_only: true` and `changes_operational_state: false`.

## Evaluation gates

Every gate has one of four states:

- `passed`: the observed, integrity-verified evidence meets the fixed target;
- `failed`: observed evidence violates the target or its material lineage failed verification;
- `not_observed`: the relevant instrument has no valid observations; or
- `not_demonstrated`: the evidence exists but does not establish the stated capability claim.

The initial gates are:

| Gate | Target | Important interpretation |
| --- | --- | --- |
| Transaction benchmark volume | At least 10,000 scored transactions in this environment | Current row count is not a load-test result. Below-target volume is `not_demonstrated`, not failed. |
| Deterministic scoring latency | Maximum verified runtime below 2,000 ms | Includes semantic feature/history construction and deterministic rule evaluation inside `assess_transaction`; excludes request parsing, network time, transaction commit, and UI rendering. |
| LLM explanation latency | Maximum validated LLM generation below 10,000 ms | Deterministic fallbacks are excluded. Historical briefs without valid LLM observations are `not_observed`. |
| Displayed explanation grounding | Zero displayed grounding or brief-integrity failures | Rejected provider candidates may safely fall back and remain recorded as rejection evidence. |
| Append-only integrity | Zero verification failures across supported material records | Empty record families are reported honestly; supported records are independently re-verified on read. |
| Reproducible candidate training | At least one verified candidate-only training bundle | Runs pin dataset, configuration, worker event chain, registration handoffs, and bundle checksums. |
| Reproducible model evaluation | At least one verified immutable shadow-evaluation report | Reports pin model, feature, rules, prediction, window, requester, and checksum lineage. |

The overall status is `attention` if any gate fails, `passed` only if every gate passes, and
`evidence_pending` otherwise.

## Scoring runtime observations

New deterministic assessments create one immutable `semantic-rules-runtime-v1.0.0` observation in
the same database transaction. The duration is measured with a monotonic high-resolution clock and
stored in whole milliseconds. Its checksum binds:

- the external transaction identifier;
- feature-snapshot checksum;
- rule-assessment checksum;
- observed runtime;
- schema version; and
- creation timestamp.

Replaying an existing assessment does not create a second observation. Assessments created before
this instrument was introduced are retained but have no reconstructed timing value. Damaged runtime
records fail integrity and are excluded from latency statistics.

## Aggregated evidence

The response contains:

- transaction, risk-band, case-status, and human-outcome counts;
- count, mean, interpolated p95, maximum, target, and state for observed latencies;
- validated LLM brief, fallback, rejection, and grounding counts;
- training-run, sealed-candidate, registered-model, verified-lineage, shadow-prediction,
  hybrid-assessment, and evaluation-report counts;
- integrity results for case chains, model lineages, briefs, hybrid assessments, dataset snapshots,
  training runs, model evaluation reports, and scoring observations;
- current feature, rules, risk-band, hybrid, explanation, dataset, shadow, and evaluation contract
  versions; and
- up to 20 latest immutable shadow-model evaluation reports.

The snapshot checksum covers all returned evaluation facts except the checksum itself. Timestamps
are normalized to UTC before checksum calculation.

## Claims boundary

The record supports repeatable inspection of this environment. It does not establish production
throughput, institutional fraud efficacy, fairness, robustness to unseen attacks, regulatory
approval, automatic-decision safety, or model fitness for promotion. Those claims require separately
designed datasets, load tests, segment analyses, independent review, and governance decisions.
