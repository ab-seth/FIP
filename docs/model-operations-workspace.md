# Model operations workspace

## Purpose

`/ml/models` is the role-aware control surface for FIP's existing governed model lifecycle. It
turns the offline candidate-training handoff into an inspectable product workflow without adding
automatic registration, approval, execution, promotion, or transaction action.

The page is server-rendered behind the same `HttpOnly` session boundary as the investigation
workspace. Browser JavaScript calls only same-origin Next.js routes; those handlers attach the API
token on the server and forward the exact request to FastAPI.

## Workflow

1. An administrator selects the `registration-payload.json` written by
   `fip-operational-train`. The browser parses JSON only and submits immutable metadata to
   `POST /api/v1/models`.
2. An administrator selects the matching `model.joblib`. The Next.js proxy preserves the
   `application/octet-stream` body and the API accepts it only when its SHA-256 matches the
   registered operational model.
3. Any authenticated role can inspect fresh trusted-store status through
   `GET /api/v1/models/{model_id}/artifact`. The read never returns executable bytes or a storage
   path.
4. A different user with the evaluator role may admit a compatible candidate to `shadow`.
   Administrators cannot self-authorize shadow admission.
5. Administrators and evaluators may explicitly run checksum-verified shadow inference for named
   transaction UUIDs or a bounded automatic batch.
6. An evaluator may seal non-overlapping baseline and evaluation windows after each contains at
   least 20 verified predictions.

## Visible evidence

Every model record shows:

- purpose, kind, runtime contract, feature version, training dataset, and threshold;
- current lifecycle status and complete checksum-linked event history;
- registration, model artifact, dataset, and model-card checksums;
- training-data approval and operational-feature compatibility;
- freshly verified artifact installation status and byte count; and
- immutable monitoring-report count.

The workspace never infers success from a prior upload response. Artifact status reopens and
rehashes the stored file on each read so a missing or damaged file remains visible.

## Role matrix

| Capability | Administrator | Evaluator | Analyst / manager |
| --- | --- | --- | --- |
| Read registry, lineage, artifact status, and reports | Yes | Yes | Yes |
| Register candidate metadata | Yes | No | No |
| Install checksum-matching artifact | Yes | No | No |
| Admit candidate to shadow | No | Yes, independently | No |
| Reject or retire a model version | Yes | Yes | No |
| Run shadow inference | Yes | Yes | No |
| Seal monitoring report | No | Yes | No |

The UI hides unavailable controls, but the FastAPI role and governance checks remain authoritative.

## Safety and claims boundary

- Registration never deserializes an artifact.
- Artifact status never returns the executable file.
- Shadow output remains `shadow_only` and cannot change deterministic scoring, case priority,
  analyst classification, or transaction state.
- Monitoring reports never promote, reject, or retire a model automatically.
- Terminal `retired` and `rejected` decisions remain irreversible.
- Public research candidates remain blocked by purpose and feature-contract gates.
- This workspace is model governance evidence, not production approval or fraud-efficacy proof.
