# Research ML evidence workspace

FIP exposes the first completed public-data model experiment through the authenticated
`/ml/research` workspace and `GET /api/v1/ml/research-evidence` endpoint. This is a presentation and
verification surface for research evidence. It is not an operational model control plane.

## Evidence shown

The sealed record contains:

- OpenML dataset 1597 provenance, provider checksum, source SHA-256, row counts, and prevalence;
- the four time-ordered train, calibration, validation, and untouched-test partitions;
- logistic-regression and histogram-gradient-boosting validation results and the selected candidate;
- held-out PR-AUC, ROC-AUC, calibration, recall, false-positive rate, alert rate, and confusion counts;
- validation permutation importance with the semantic limitation of anonymized PCA components;
- pipeline, split, seed, runtime, evidence, model, metrics, and manifest lineage; and
- an explicit claims boundary that prevents operational promotion or efficacy extrapolation.

The endpoint returns `Cache-Control: no-store` and requires the same bearer authentication as the
other FIP workspaces. The page fetches the API record through the Next.js server boundary, so the
session token remains in the `HttpOnly` cookie and is not sent to browser JavaScript.

## Integrity contract

All material facts are canonicalized and sealed by a pinned SHA-256 checksum. The API recomputes the
checksum when it builds the response and reports whether the record still matches the reviewed
value. Any change to a dataset fact, metric, partition, artifact hash, or claims boundary requires a
deliberate evidence review and reseal.

The API test independently removes response-only integrity fields, recomputes the canonical
checksum, and verifies the temporal split ordering and single selected candidate.

## Operational boundary

This run demonstrates reproducible model-development methodology on real public transactions. It
does not demonstrate performance on an institution's data. Features `V1` through `V28` are
undisclosed PCA components and cannot be reconstructed from FIP's canonical transaction features.

Consequently, the workspace and endpoint:

- cannot register, install, admit, or promote the research artifact;
- cannot alter the deterministic operational score or case state;
- cannot trigger an automated or financial action;
- do not assert institution-specific fraud-detection efficacy; and
- never expose raw public-data rows or the serialized research artifact.

Operational ML continues through independently governed institution-owned dataset snapshots,
offline candidate training, artifact verification, evaluator admission, and shadow-only execution.
