from __future__ import annotations

import hashlib
from pathlib import Path

import joblib  # type: ignore[import-untyped]

from fip_api.research_ml import PIPELINE_VERSION
from fip_api.research_ml.training import CandidateResult


def write_model_artifact(path: Path, candidate: CandidateResult) -> None:
    """Serialize a locally trained research candidate using the versioned artifact contract."""

    joblib.dump(
        {
            "pipeline_version": PIPELINE_VERSION,
            "research_only": True,
            "model_name": candidate.name,
            "estimator": candidate.estimator,
            "calibrator": candidate.calibrator,
            "threshold": candidate.threshold,
        },
        path,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
