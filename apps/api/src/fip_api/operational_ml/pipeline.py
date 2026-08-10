from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any

import joblib  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.models import ModelKind, ModelPurpose, ModelRuntimeContract
from fip_api.operational_ml import PIPELINE_VERSION
from fip_api.operational_ml.dataset import (
    OperationalTrainingDataset,
    load_operational_training_dataset,
    validate_operational_training_dataset,
)
from fip_api.operational_ml.models import (
    AnomalyTrainingResult,
    SupervisedTrainingResult,
    TrainingPartitions,
    build_training_partitions,
    train_anomaly_model,
    train_supervised_model,
)
from fip_api.schemas.model_registry import ModelRegistrationCreate

VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class OperationalTrainingConfig:
    output_directory: Path
    version: str
    seed: int = 42
    maximum_false_positive_rate: float = 0.05

    def validate(self) -> None:
        if not VERSION_PATTERN.fullmatch(self.version):
            raise ValueError("version must satisfy the governed model version contract")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if not 0 < self.maximum_false_positive_rate < 1:
            raise ValueError("maximum_false_positive_rate must be between 0 and 1")
        if self.output_directory.exists():
            raise FileExistsError(self.output_directory)


def run_operational_training(
    db: Session,
    dataset_id: str,
    config: OperationalTrainingConfig,
) -> dict[str, Any]:
    dataset = load_operational_training_dataset(db, dataset_id)
    return run_operational_training_dataset(dataset, config)


def run_operational_training_dataset(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
) -> dict[str, Any]:
    """Train candidate artifacts without registering or executing either model."""

    config.validate()
    validate_operational_training_dataset(dataset)
    partitions = build_training_partitions(dataset)
    supervised = train_supervised_model(
        dataset,
        partitions,
        seed=config.seed,
        maximum_false_positive_rate=config.maximum_false_positive_rate,
    )
    anomaly = train_anomaly_model(
        dataset,
        partitions,
        seed=config.seed,
        maximum_false_positive_rate=config.maximum_false_positive_rate,
    )
    return _write_candidate_bundle(dataset, config, partitions, supervised, anomaly)


def _write_candidate_bundle(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    partitions: TrainingPartitions,
    supervised: SupervisedTrainingResult,
    anomaly: AnomalyTrainingResult,
) -> dict[str, Any]:
    output = config.output_directory
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        supervised_directory = temporary / "supervised"
        anomaly_directory = temporary / "anomaly"
        supervised_directory.mkdir()
        anomaly_directory.mkdir()

        supervised_artifact_path = supervised_directory / "model.joblib"
        anomaly_artifact_path = anomaly_directory / "model.joblib"
        joblib.dump(supervised.artifact, supervised_artifact_path, compress=0, protocol=4)
        joblib.dump(anomaly.artifact, anomaly_artifact_path, compress=0, protocol=4)
        supervised_artifact_checksum = sha256_file(supervised_artifact_path)
        anomaly_artifact_checksum = sha256_file(anomaly_artifact_path)
        score_reference_checksum = canonical_json_checksum(
            [format(value, ".17g") for value in anomaly.artifact.reference_scores]
        )

        supervised_card_path = supervised_directory / "model-card.md"
        anomaly_card_path = anomaly_directory / "model-card.md"
        supervised_card_path.write_text(
            _supervised_model_card(dataset, config, supervised, supervised_artifact_checksum),
            encoding="utf-8",
        )
        anomaly_card_path.write_text(
            _anomaly_model_card(
                dataset,
                config,
                anomaly,
                anomaly_artifact_checksum,
                score_reference_checksum,
            ),
            encoding="utf-8",
        )

        supervised_registration = _supervised_registration(
            dataset,
            config,
            supervised,
            supervised_artifact_checksum,
            sha256_file(supervised_card_path),
        )
        anomaly_registration = _anomaly_registration(
            dataset,
            config,
            anomaly,
            anomaly_artifact_checksum,
            sha256_file(anomaly_card_path),
            score_reference_checksum,
        )
        _write_json(
            supervised_directory / "registration-payload.json",
            supervised_registration.model_dump(mode="json"),
        )
        _write_json(
            anomaly_directory / "registration-payload.json",
            anomaly_registration.model_dump(mode="json"),
        )

        evidence = _training_evidence(
            dataset,
            config,
            partitions,
            supervised,
            anomaly,
            supervised_artifact_checksum,
            anomaly_artifact_checksum,
            score_reference_checksum,
        )
        _write_json(temporary / "training-evidence.json", evidence)
        files = {
            str(path.relative_to(temporary)): sha256_file(path)
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        }
        _write_json(
            temporary / "run-manifest.json",
            {
                "pipeline_version": PIPELINE_VERSION,
                "candidate_only": True,
                "automatic_registration": False,
                "files": files,
            },
        )
        os.replace(temporary, output)
        return evidence
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _training_evidence(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    partitions: TrainingPartitions,
    supervised: SupervisedTrainingResult,
    anomaly: AnomalyTrainingResult,
    supervised_artifact_checksum: str,
    anomaly_artifact_checksum: str,
    score_reference_checksum: str,
) -> dict[str, Any]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "candidate_only": True,
        "automatic_registration": False,
        "automatic_shadow_promotion": False,
        "live_scoring": False,
        "dataset": {
            "id": dataset.display_id,
            "checksum": dataset.dataset_checksum,
            "integrity_verified": dataset.integrity_verified,
            "readiness_status": dataset.readiness_status.value,
            "feature_set_version": dataset.feature_set_version,
            "label_contract_version": dataset.label_contract_version,
            "split_contract_version": dataset.split_contract_version,
            "feature_names": list(dataset.feature_names),
            "row_count": dataset.row_count,
            "positive_count": dataset.positive_count,
        },
        "configuration": {
            "version": config.version,
            "seed": config.seed,
            "maximum_false_positive_rate": config.maximum_false_positive_rate,
        },
        "partitions": partitions.evidence(),
        "supervised": {
            "selected_model": supervised.artifact.model_name,
            "artifact_sha256": supervised_artifact_checksum,
            "threshold": supervised.artifact.threshold,
            "preprocessing": supervised.preprocessing_evidence,
            "candidates": {
                candidate.name: {"validation": candidate.validation_metrics.to_dict()}
                for candidate in supervised.candidates
            },
            "test": supervised.test_metrics.to_dict(),
            "explainability": {
                "method": "semantic validation permutation importance by PR-AUC decrease",
                "repeats": 3,
                "features": list(supervised.feature_importance),
            },
        },
        "anomaly": {
            "model": "isolation-forest",
            "artifact_sha256": anomaly_artifact_checksum,
            "training_partition": {
                "row_count": len(anomaly.artifact.reference_scores),
                "positive_count": sum(
                    row.label for row in partitions.estimator_train + partitions.calibration
                ),
                "source_partitions": ["estimator_train", "calibration"],
            },
            "contamination": anomaly.artifact.contamination,
            "score_reference_checksum": score_reference_checksum,
            "threshold": anomaly.artifact.threshold,
            "preprocessing": anomaly.preprocessing_evidence,
            "validation": anomaly.validation_metrics.to_dict(),
            "test": anomaly.test_metrics.to_dict(),
            "explainability": {
                "method": "semantic validation permutation importance by PR-AUC decrease",
                "repeats": 3,
                "features": list(anomaly.feature_importance),
            },
        },
        "runtime": {
            "python": platform.python_version(),
            "joblib": package_version("joblib"),
            "numpy": package_version("numpy"),
            "scikit_learn": package_version("scikit-learn"),
        },
    }


def _supervised_registration(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    result: SupervisedTrainingResult,
    artifact_checksum: str,
    card_checksum: str,
) -> ModelRegistrationCreate:
    metrics = result.test_metrics
    return ModelRegistrationCreate(
        model_key="canonical-fraud-classifier",
        version=config.version,
        kind=ModelKind.SUPERVISED,
        purpose=ModelPurpose.OPERATIONAL,
        runtime_contract=ModelRuntimeContract.BINARY_PROBABILITY,
        artifact_sha256=artifact_checksum,
        feature_set_version=dataset.feature_set_version,
        training_dataset_id=dataset.display_id,
        training_dataset_checksum=dataset.dataset_checksum,
        training_data_approved=True,
        operational_feature_compatible=True,
        decision_threshold=Decimal(f"{result.artifact.threshold:.10f}"),
        evaluation_metrics={
            "average_precision": metrics.average_precision,
            "roc_auc": metrics.roc_auc,
            "brier_score": metrics.brier_score,
            "recall": metrics.recall,
            "false_positive_rate": metrics.false_positive_rate,
            "evaluated_row_count": metrics.row_count,
            "evaluated_positive_count": metrics.positive_count,
            "precision": metrics.precision,
            "selected_estimator": result.artifact.model_name,
        },
        model_card_reference="supervised/model-card.md",
        model_card_checksum=card_checksum,
    )


def _anomaly_registration(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    result: AnomalyTrainingResult,
    artifact_checksum: str,
    card_checksum: str,
    score_reference_checksum: str,
) -> ModelRegistrationCreate:
    return ModelRegistrationCreate(
        model_key="canonical-transaction-anomaly",
        version=config.version,
        kind=ModelKind.ANOMALY,
        purpose=ModelPurpose.OPERATIONAL,
        runtime_contract=ModelRuntimeContract.ANOMALY_SCORE,
        artifact_sha256=artifact_checksum,
        feature_set_version=dataset.feature_set_version,
        training_dataset_id=dataset.display_id,
        training_dataset_checksum=dataset.dataset_checksum,
        training_data_approved=True,
        operational_feature_compatible=True,
        decision_threshold=Decimal(f"{result.artifact.threshold:.10f}"),
        evaluation_metrics={
            "training_row_count": len(result.artifact.reference_scores),
            "contamination": result.artifact.contamination,
            "score_reference_checksum": score_reference_checksum,
            "average_precision": result.test_metrics.average_precision,
            "roc_auc": result.test_metrics.roc_auc,
            "recall": result.test_metrics.recall,
            "false_positive_rate": result.test_metrics.false_positive_rate,
            "evaluated_row_count": result.test_metrics.row_count,
            "evaluated_positive_count": result.test_metrics.positive_count,
        },
        model_card_reference="anomaly/model-card.md",
        model_card_checksum=card_checksum,
    )


def _supervised_model_card(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    result: SupervisedTrainingResult,
    artifact_checksum: str,
) -> str:
    metrics = result.test_metrics
    return f"""# FIP operational supervised candidate

## Status and intended use

This is an **offline candidate artifact**. It is not registered, shadow-authorized, or permitted to
affect operational decisions. Independent registry and evaluator actions remain mandatory.

## Governed lineage

- Dataset: `{dataset.display_id}`
- Dataset SHA-256: `{dataset.dataset_checksum}`
- Feature contract: `{dataset.feature_set_version}`
- Label contract: `{dataset.label_contract_version}`
- Selected estimator: `{result.artifact.model_name}`
- Random seed: {config.seed}
- Artifact SHA-256: `{artifact_checksum}`

## Held-out test result

- Rows / positives: {metrics.row_count} / {metrics.positive_count}
- PR-AUC: {metrics.average_precision:.6f}
- ROC-AUC: {metrics.roc_auc:.6f}
- Brier score: {metrics.brier_score:.6f}
- Recall: {metrics.recall:.6f}
- False-positive rate: {metrics.false_positive_rate:.6f}
- Validation-selected threshold: {result.artifact.threshold:.10f}

## Limitations

Performance is limited to the frozen governed snapshot and its time range. Dataset shift, subgroup
behavior, calibration, alert capacity, and shadow behavior require independent review before any
lifecycle transition. Global permutation importance is diagnostic and is not a case-level reason.
"""


def _anomaly_model_card(
    dataset: OperationalTrainingDataset,
    config: OperationalTrainingConfig,
    result: AnomalyTrainingResult,
    artifact_checksum: str,
    score_reference_checksum: str,
) -> str:
    metrics = result.test_metrics
    return f"""# FIP operational anomaly candidate

## Status and intended use

This is an **offline candidate artifact**. It is not registered, shadow-authorized, or permitted to
affect operational decisions. It complements supervised evidence; it is not proof of fraud.

## Governed lineage

- Dataset: `{dataset.display_id}`
- Dataset SHA-256: `{dataset.dataset_checksum}`
- Feature contract: `{dataset.feature_set_version}`
- Model: Isolation Forest
- Random seed: {config.seed}
- Training contamination: {result.artifact.contamination:.6f}
- Score-reference SHA-256: `{score_reference_checksum}`
- Artifact SHA-256: `{artifact_checksum}`

## Held-out test result

- Rows / positives: {metrics.row_count} / {metrics.positive_count}
- PR-AUC: {metrics.average_precision:.6f}
- ROC-AUC: {metrics.roc_auc:.6f}
- Recall: {metrics.recall:.6f}
- False-positive rate: {metrics.false_positive_rate:.6f}
- Validation-selected threshold: {result.artifact.threshold:.10f}

## Limitations

Anomaly scores are empirical percentiles against the training reference distribution. Novelty is
not fraud, and changing traffic can alter score behavior. Shadow monitoring and independent review
are mandatory before lifecycle advancement.
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
