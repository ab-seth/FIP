# Hybrid risk evidence

FIP can combine one verified deterministic rule assessment, one verified supervised shadow
prediction, and one verified anomaly shadow prediction into an immutable decision-support record.
The record is not an operational fraud decision: it cannot open or reprioritize a case, block a
transaction, change a rule score, or promote a model.

## Versioned policy

The initial policy is `hybrid-risk-v1.0.0`:

```text
combined score = 100 * (
    0.20 * normalized rule score
  + 0.60 * supervised score
  + 0.20 * anomaly score
)
```

The rule score is normalized from `0..100` to `0..1`; both model contracts already emit values in
`0..1`. The combined score is quantized to four decimal places and mapped to fixed bands:

- low: `0 <= score < 40`;
- medium: `40 <= score < 70`;
- high: `70 <= score <= 100`.

The 20/60/20 weights are transparent design defaults, not a claim of statistical optimality. They
are server-owned and versioned rather than caller-editable. Future calibration must create a new
policy version and preserve existing assessments.

## Creation contract

An administrator or evaluator creates evidence by naming the exact two shadow predictions:

```http
POST /api/v1/transactions/{transaction_id}/hybrid-assessments
Content-Type: application/json

{
  "supervised_prediction_id": "<prediction-uuid>",
  "anomaly_prediction_id": "<prediction-uuid>"
}
```

Creation fails closed unless all of the following are true:

- the current rule assessment and feature snapshot pass checksum verification;
- each prediction and its complete model lifecycle pass integrity verification;
- the supervised input comes from an operational supervised model;
- the anomaly input comes from an operational anomaly model;
- both predictions belong to the requested transaction;
- the rules and both models reference the same immutable feature snapshot and feature version;
- both predictions were authorized by an actual `shadow` lifecycle event.

FIP does not silently select a “latest” model, substitute a missing component, or renormalize the
remaining weights. An exact replay returns the existing assessment.

Authenticated users can list the recorded evidence:

```http
GET /api/v1/transactions/{transaction_id}/hybrid-assessments
```

They can also inspect the transaction's candidate prediction evidence:

```http
GET /api/v1/transactions/{transaction_id}/shadow-predictions
```

Each prediction response states its `model_kind` and `runtime_contract` directly, alongside the
model version, score, local factors, checksum, and integrity result. Callers therefore do not need
to infer whether a prediction is supervised or anomaly evidence from a model name.

If the deterministic rules already opened a case, `GET /api/v1/cases/{case_id}` includes the same
assessment under `hybrid_assessments`. This is a read-only dossier projection; creating the hybrid
record does not append a case event or alter case status, priority, or opening evidence.

## Case-dossier workspace

The case dossier presents the hybrid record as a separate machine-learning evidence layer next to
the deterministic rule ledger. It shows the fixed rule, supervised, and anomaly contributions; the
model versions and local factors behind available predictions; the versioned policy; and the
assessment proof. The original rules-only score remains visible as the operational score.

Administrators and evaluators can assemble an assessment in the dossier only by explicitly
selecting one integrity-verified supervised prediction and one integrity-verified anomaly
prediction. Failed predictions remain visible for investigation but are excluded from the
selection controls. The server repeats every type, lineage, authorization, and checksum check; the
browser is not a trust boundary. Analysts and managers receive the same evidence view without the
creation control.

## Evidence and integrity

Each record pins:

- feature, history, rule-assessment, and triggered-rule evidence;
- ruleset, risk-band, hybrid-policy, and evidence-schema versions;
- each model key/version, runtime contract, artifact checksum, registration checksum, training
  dataset identifier/checksum, and shadow authorization checksum;
- each prediction checksum and local factor contributions;
- source scores, normalized values, weights, contribution points, combined score, and risk band;
- creator identity, UTC creation time, and an assessment checksum over the complete record.

Reads recompute the policy result and verify every upstream checksum. `integrity_verified` becomes
false if the assessment or any pinned upstream evidence is altered.

Every response also states:

```json
{
  "decision_support_only": true,
  "shadow_inputs_only": true,
  "affects_case_priority": false,
  "affects_transaction_action": false,
  "llm_influenced_score": false
}
```

An LLM may later explain this evidence, but it may never change the source values, weights, score,
band, or checksum.

## Current limitations

- The policy is not calibrated or validated for production use.
- Shadow inputs are comparison evidence, not production-approved models.
- No automatic batch assembly, alerting, transaction action, or external score submission occurs.
- Application checksums are tamper-evident records, not digital signatures or a blockchain.
