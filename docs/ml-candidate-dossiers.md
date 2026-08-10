# Reproducible ML candidate dossiers

FIP can independently replay a completed public-dataset research run and export its verified facts
as a schema-valid model-registry candidate. This is the bridge between offline ML evidence and the
governed registry; it is not a production-promotion mechanism.

## Why replay instead of trusting the artifact

A checksum manifest proves that a set of files stayed together, but a modified artifact and a
modified manifest could still agree. The dossier command therefore starts from the reviewed dataset
manifest and raw source file, repeats the full experiment, and compares the results with the supplied
run.

The replay verifies:

1. the dataset file matches the provider MD5 in the reviewed manifest;
2. the raw SHA-256 matches the completed run;
3. all run files match their manifest checksums;
4. temporal partitions and equal-timestamp boundaries reproduce exactly;
5. both candidate models' validation metrics reproduce;
6. model selection, threshold, and held-out test metrics reproduce;
7. validation permutation importance reproduces;
8. the source model card regenerates from the recorded metrics and source artifact checksum; and
9. a fresh candidate artifact and matching model card are built from the replayed model.

The supplied `model.joblib` file is never deserialized. This avoids executing pickle-compatible
content merely because it appeared in a run directory. Serialized bytes can vary across otherwise
equivalent runtime environments, so the dossier records whether the fresh and source artifacts are
byte-identical but does not use that as an approval claim. The registry payload points only to the
freshly trained candidate in the new bundle.

## Command

After completing the training command documented in
[`ml-research-evidence.md`](ml-research-evidence.md), run:

```bash
uv run --project apps/api --group research fip-research-verify-candidate \
  --input data/raw/creditcard.arff \
  --dataset-manifest data/manifests/ulb-credit-card-v1.json \
  --run artifacts/research/ulb-seed-42 \
  --output artifacts/research/ulb-seed-42-candidate \
  --model-key ulb-fraud-research \
  --version openml-1597-v1-seed-42 \
  --model-card-reference artifacts/research/ulb-seed-42-candidate/model-card.md
```

The output directory must be new and is created atomically. It contains:

- `model.joblib`: the freshly retrained candidate artifact;
- `model-card.md`: a model card bound to that candidate artifact checksum;
- `candidate-registration.json`: a `ModelRegistrationCreate`-compatible payload;
- `candidate-dossier.json`: source lineage, explicit replay statements, and a canonical checksum;
- `bundle-manifest.json`: SHA-256 values for every candidate-bundle evidence file.

## Governance result

The exported ULB candidate is deliberately encoded with:

- `purpose: research`;
- `training_data_approved: false`, because public research approval is not operational training-data
  approval;
- `operational_feature_compatible: false`; and
- the source-specific feature contract `openml-1597-ulb-pca-v1`.

An administrator may preserve the payload in the governed registry as a candidate evidence record,
but the registry will reject any attempt to move it into shadow mode. No dossier command calls the
API, changes a model lifecycle, or affects a transaction.

## Claims boundary

Replay is strong evidence that the pinned code, data, configuration, and environment reproduce the
recorded experiment. It is not a digital signature, a third-party audit, or evidence of current U.S.
institutional efficacy. Operational feature parity, institution-owned or compatible licensed data,
independent evaluation, shadow monitoring, and governance approval remain separate requirements.
