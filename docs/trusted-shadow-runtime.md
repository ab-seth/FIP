# Trusted operational shadow runtime

FIP can install and execute an explicitly registered operational candidate after an independent
evaluator admits that exact version to `shadow`. The runtime writes comparison evidence only. It
cannot change the deterministic rule score, create or prioritize a case, promote a model, or make a
transaction decision.

## Trust boundary

Python model artifacts are serialized objects and may execute code while loading. FIP therefore
does not load a file path supplied by an inference request. The controlled workflow is:

1. Offline training creates the artifact, model card, evidence, and registration payload.
2. An administrator registers the immutable metadata and artifact SHA-256.
3. An administrator uploads the artifact bytes as `application/octet-stream`.
4. FIP verifies the bytes against the registered checksum and stores them under that checksum in
   the configured content-addressed artifact volume.
5. A different evaluator reviews the evidence and admits the registered version to `shadow`.
6. A role-gated shadow run reopens and re-hashes the stored file before deserialization.
7. FIP verifies the artifact class, model kind, runtime contract, feature version, training dataset
   checksum, and threshold against the immutable registration before inference.

Artifact approval is therefore a privileged code-deployment decision, not an ordinary file upload.
Only artifacts produced by the reviewed FIP training pipeline should be registered and installed.

## Install an artifact

The API image includes the ML runtime dependencies, and Compose persists installed artifacts in the
`fip_model_artifacts` volume. The relevant settings are:

```text
FIP_MODEL_ARTIFACT_ROOT=/var/lib/fip/model-artifacts
FIP_MODEL_ARTIFACT_MAX_BYTES=268435456
```

After registering the matching `registration-payload.json`, an administrator installs the exact
candidate file:

```bash
curl --fail-with-body \
  -X PUT "http://localhost:8000/api/v1/models/${MODEL_ID}/artifact" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @artifacts/operational-candidate/anomaly/model.joblib
```

An exact replay is idempotent. Empty, oversized, checksum-mismatched, symlinked, non-regular, or
subsequently modified artifacts are rejected.

## Run shadow inference

After independent evaluator admission, an administrator or evaluator can score an explicit set of
transactions:

```bash
curl --fail-with-body \
  -X POST "http://localhost:8000/api/v1/models/${MODEL_ID}/shadow-runs" \
  -H "Authorization: Bearer ${EVALUATOR_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"transaction_ids":["<transaction-uuid>"]}'
```

Omitting `transaction_ids` selects up to `limit` oldest compatible, unscored feature snapshots:

```json
{"limit": 100}
```

A run uses only the identifier-free operational training feature allow-list. The runtime derives up
to ten local factors by comparing the transaction score with one-feature-at-a-time learned numeric
median or unknown-category references. It then delegates persistence to the existing immutable,
checksum-protected shadow ledger. Replaying the same model and feature snapshot returns the prior
prediction.

## Explicit limits

- Shadow inference is operator-triggered; intake remains available if an artifact is absent.
- A verified shadow output may be referenced by a separate hybrid evidence record, but it never
  changes the rules-only case score or case priority.
- No public research model can enter this runtime because its purpose and feature contract fail the
  operational gates.
- Serialized model portability still depends on compatible Python, NumPy, joblib, and scikit-learn
  versions; the candidate evidence records those versions.
- Production activation and automated model promotion remain unavailable.
