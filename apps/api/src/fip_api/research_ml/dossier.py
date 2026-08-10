from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, cast

from fip_api.core.checksums import canonical_json_checksum
from fip_api.models import ModelKind, ModelPurpose, ModelRuntimeContract
from fip_api.research_ml import PIPELINE_VERSION
from fip_api.research_ml.artifact import sha256_file, write_model_artifact
from fip_api.research_ml.dataset import load_ulb_credit_card
from fip_api.research_ml.evaluation import evaluate_probabilities
from fip_api.research_ml.pipeline import build_model_card, partition_summary
from fip_api.research_ml.splitting import SplitFractions, build_temporal_partitions
from fip_api.research_ml.training import (
    explain_candidate,
    predict_candidate,
    select_candidate,
    train_candidates,
)
from fip_api.schemas.model_registry import ModelRegistrationCreate

DOSSIER_VERSION = "fip-research-candidate-dossier-v1"
BUNDLE_VERSION = "fip-research-candidate-bundle-v1"
REQUIRED_RUN_FILES = {"metrics.json", "model.joblib", "model-card.md"}
RESEARCH_FEATURE_SET_VERSION = "openml-1597-ulb-pca-v1"


class ResearchVerificationError(ValueError):
    """Raised when supplied research evidence cannot be independently reproduced."""


@dataclass(frozen=True)
class CandidateDossierConfig:
    input_path: Path
    dataset_manifest_path: Path
    run_directory: Path
    output_directory: Path
    model_key: str
    version: str
    model_card_reference: str

    def validate(self) -> None:
        if not self.input_path.is_file():
            raise FileNotFoundError(self.input_path)
        if not self.dataset_manifest_path.is_file():
            raise FileNotFoundError(self.dataset_manifest_path)
        if not self.run_directory.is_dir():
            raise FileNotFoundError(self.run_directory)
        if self.output_directory.exists():
            raise FileExistsError(self.output_directory)


def build_candidate_dossier(config: CandidateDossierConfig) -> dict[str, Any]:
    """Replay a research run and export a governed, research-only candidate payload.

    The supplied joblib file is never deserialized. A fresh candidate artifact is trained from the
    pinned raw dataset and placed in a new, checksummed bundle.
    """

    config.validate()
    metrics_path = config.run_directory / "metrics.json"
    manifest_path = config.run_directory / "run-manifest.json"
    metrics = _load_json_object(metrics_path)
    manifest = _load_json_object(manifest_path)
    dataset_manifest = _load_json_object(config.dataset_manifest_path)
    file_checksums = _verify_run_manifest(config.run_directory, manifest)

    _require_equal(manifest.get("pipeline_version"), PIPELINE_VERSION, "manifest pipeline version")
    _require_equal(metrics.get("pipeline_version"), PIPELINE_VERSION, "metrics pipeline version")
    _require_equal(manifest.get("research_only"), True, "manifest research-only flag")
    _require_equal(metrics.get("research_only"), True, "metrics research-only flag")

    dataset_facts = _require_mapping(metrics, "dataset")
    configuration = _require_mapping(metrics, "configuration")
    _verify_dataset_manifest(config.input_path, dataset_manifest, dataset_facts)
    dataset_checksum = sha256_file(config.input_path)
    _require_equal(
        dataset_facts.get("source_file_sha256"),
        dataset_checksum,
        "raw dataset checksum",
    )
    _require_equal(
        dataset_facts.get("operational_feature_compatible"),
        False,
        "operational feature compatibility",
    )

    dataset = load_ulb_credit_card(config.input_path)
    _require_equal(dataset_facts.get("dataset_id"), dataset.dataset_id, "dataset identifier")
    _require_equal(dataset_facts.get("row_count"), dataset.row_count, "dataset row count")
    _require_equal(
        dataset_facts.get("positive_count"),
        dataset.positive_count,
        "dataset positive count",
    )
    _assert_equivalent(
        dataset_facts.get("feature_names"),
        list(dataset.feature_names),
        "dataset feature names",
    )

    seed = _require_integer(configuration, "seed")
    maximum_fpr = _require_number(configuration, "maximum_false_positive_rate")
    split_values = _require_mapping(configuration, "split_fractions")
    split_fractions = SplitFractions(
        train=_require_number(split_values, "train"),
        calibration=_require_number(split_values, "calibration"),
        validation=_require_number(split_values, "validation"),
        test=_require_number(split_values, "test"),
    )
    split_fractions.validate()
    partitions = build_temporal_partitions(dataset, split_fractions)
    _assert_equivalent(
        metrics.get("partitions"),
        partition_summary(dataset, partitions),
        "temporal partitions",
    )

    candidates = train_candidates(
        dataset.features[partitions.train],
        dataset.labels[partitions.train],
        dataset.features[partitions.calibration],
        dataset.labels[partitions.calibration],
        dataset.features[partitions.validation],
        dataset.labels[partitions.validation],
        seed=seed,
        maximum_false_positive_rate=maximum_fpr,
    )
    selected = select_candidate(candidates)
    replayed_candidates = {
        candidate.name: {"validation": candidate.validation_metrics.to_dict()}
        for candidate in candidates
    }
    _assert_equivalent(metrics.get("candidates"), replayed_candidates, "candidate evaluation")
    _require_equal(metrics.get("selected_model"), selected.name, "selected model")

    test_probabilities = predict_candidate(selected, dataset.features[partitions.test])
    test_metrics = evaluate_probabilities(
        dataset.labels[partitions.test],
        test_probabilities,
        selected.threshold,
    ).to_dict()
    _assert_equivalent(metrics.get("test"), test_metrics, "held-out test evaluation")

    feature_importance = explain_candidate(
        selected,
        dataset.features[partitions.validation],
        dataset.labels[partitions.validation],
        dataset.feature_names,
        seed=seed,
    )
    explanation = _require_mapping(metrics, "explainability")
    _assert_equivalent(
        explanation.get("features"),
        feature_importance,
        "validation explanation",
    )

    expected_artifact_checksum = file_checksums["model.joblib"]
    regenerated_source_card = build_model_card(metrics, expected_artifact_checksum)
    regenerated_card_checksum = hashlib.sha256(regenerated_source_card.encode("utf-8")).hexdigest()
    _require_equal(
        file_checksums["model-card.md"],
        regenerated_card_checksum,
        "regenerated source model-card checksum",
    )

    config.output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{config.output_directory.name}-",
            dir=config.output_directory.parent,
        )
    )
    try:
        candidate_artifact_path = temporary_directory / "model.joblib"
        write_model_artifact(candidate_artifact_path, selected)
        candidate_artifact_checksum = sha256_file(candidate_artifact_path)
        candidate_model_card = build_model_card(metrics, candidate_artifact_checksum)
        candidate_model_card_path = temporary_directory / "model-card.md"
        candidate_model_card_path.write_text(candidate_model_card, encoding="utf-8")
        candidate_model_card_checksum = sha256_file(candidate_model_card_path)

        dataset_manifest_checksum = sha256_file(config.dataset_manifest_path)
        run_manifest_checksum = sha256_file(manifest_path)
        registration = _build_registration(
            config=config,
            metrics=metrics,
            dataset_checksum=dataset_checksum,
            dataset_manifest_checksum=dataset_manifest_checksum,
            artifact_checksum=candidate_artifact_checksum,
            source_artifact_checksum=expected_artifact_checksum,
            run_manifest_checksum=run_manifest_checksum,
            model_card_checksum=candidate_model_card_checksum,
            test_metrics=test_metrics,
        )
        registration_facts = registration.model_dump(mode="json")
        registration_path = temporary_directory / "candidate-registration.json"
        _write_json(registration_path, registration_facts)

        dossier: dict[str, Any] = {
            "dossier_version": DOSSIER_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "dataset_id": dataset.dataset_id,
            "dataset_manifest_sha256": dataset_manifest_checksum,
            "source_run_manifest_sha256": run_manifest_checksum,
            "source_artifact_sha256": expected_artifact_checksum,
            "candidate_artifact_sha256": candidate_artifact_checksum,
            "candidate_artifact_matches_source_bytes": _secure_text_equal(
                expected_artifact_checksum,
                candidate_artifact_checksum,
            ),
            "verification": {
                "run_file_checksums_verified": True,
                "approved_dataset_manifest_verified": True,
                "raw_dataset_checksum_verified": True,
                "temporal_partitions_reproduced": True,
                "candidate_selection_reproduced": True,
                "validation_metrics_reproduced": True,
                "held_out_test_metrics_reproduced": True,
                "validation_explanation_reproduced": True,
                "source_model_card_regenerated": True,
                "candidate_artifact_retrained": True,
                "supplied_artifact_deserialized": False,
            },
            "candidate_registration": registration_facts,
        }
        dossier["dossier_checksum"] = canonical_json_checksum(dossier)
        dossier_path = temporary_directory / "candidate-dossier.json"
        _write_json(dossier_path, dossier)
        bundle_manifest = {
            "bundle_version": BUNDLE_VERSION,
            "research_only": True,
            "files": {
                "candidate-dossier.json": sha256_file(dossier_path),
                "candidate-registration.json": sha256_file(registration_path),
                "model-card.md": candidate_model_card_checksum,
                "model.joblib": candidate_artifact_checksum,
            },
        }
        _write_json(temporary_directory / "bundle-manifest.json", bundle_manifest)
        os.replace(temporary_directory, config.output_directory)
        return dossier
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def _build_registration(
    *,
    config: CandidateDossierConfig,
    metrics: Mapping[str, Any],
    dataset_checksum: str,
    dataset_manifest_checksum: str,
    artifact_checksum: str,
    source_artifact_checksum: str,
    run_manifest_checksum: str,
    model_card_checksum: str,
    test_metrics: Mapping[str, float | int],
) -> ModelRegistrationCreate:
    threshold = Decimal(str(test_metrics["threshold"])).quantize(
        Decimal("0.0000000001"),
        rounding=ROUND_HALF_EVEN,
    )
    evaluation_metrics: dict[str, float | int | str | bool] = {
        "average_precision": test_metrics["average_precision"],
        "roc_auc": test_metrics["roc_auc"],
        "brier_score": test_metrics["brier_score"],
        "recall": test_metrics["recall"],
        "false_positive_rate": test_metrics["false_positive_rate"],
        "evaluated_row_count": test_metrics["row_count"],
        "evaluated_positive_count": test_metrics["positive_count"],
        "precision": test_metrics["precision"],
        "expected_calibration_error": test_metrics["expected_calibration_error"],
        "selected_model": str(metrics["selected_model"]),
        "evidence_scope": "public-real-data-research-only",
        "dataset_access_approval": "research-methodology-only",
        "dataset_manifest_checksum": dataset_manifest_checksum,
        "source_run_manifest_checksum": run_manifest_checksum,
        "source_artifact_checksum": source_artifact_checksum,
        "verification_method": "full-deterministic-replay",
    }
    return ModelRegistrationCreate(
        model_key=config.model_key,
        version=config.version,
        kind=ModelKind.SUPERVISED,
        purpose=ModelPurpose.RESEARCH,
        runtime_contract=ModelRuntimeContract.BINARY_PROBABILITY,
        artifact_sha256=artifact_checksum,
        feature_set_version=RESEARCH_FEATURE_SET_VERSION,
        training_dataset_id=str(_require_mapping(metrics, "dataset")["dataset_id"]),
        training_dataset_checksum=dataset_checksum,
        training_data_approved=False,
        operational_feature_compatible=False,
        decision_threshold=threshold,
        evaluation_metrics=evaluation_metrics,
        model_card_reference=config.model_card_reference,
        model_card_checksum=model_card_checksum,
    )


def _verify_dataset_manifest(
    input_path: Path,
    dataset_manifest: Mapping[str, Any],
    run_dataset_facts: Mapping[str, Any],
) -> None:
    _require_equal(
        dataset_manifest.get("dataset_id"),
        run_dataset_facts.get("dataset_id"),
        "dataset manifest identifier",
    )
    _require_equal(
        dataset_manifest.get("access_status"),
        "approved_for_research_methodology",
        "dataset manifest access status",
    )
    _require_equal(
        dataset_manifest.get("provider_license_value"),
        "Public",
        "dataset manifest license",
    )
    _require_equal(
        dataset_manifest.get("operational_feature_compatible"),
        False,
        "dataset manifest operational compatibility",
    )
    provider_md5 = dataset_manifest.get("provider_md5")
    if not isinstance(provider_md5, str) or len(provider_md5) != 32:
        raise ResearchVerificationError("Dataset manifest provider MD5 is invalid.")
    actual_md5 = _md5_file(input_path)
    if not _secure_text_equal(provider_md5.lower(), actual_md5):
        raise ResearchVerificationError("Raw dataset does not match the approved provider MD5.")


def _verify_run_manifest(run_directory: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    files = _require_mapping(manifest, "files")
    if set(files) != REQUIRED_RUN_FILES:
        raise ResearchVerificationError(
            "Run manifest must contain exactly metrics.json, model.joblib, and model-card.md."
        )
    verified: dict[str, str] = {}
    for name in sorted(REQUIRED_RUN_FILES):
        expected = files[name]
        if not isinstance(expected, str) or len(expected) != 64:
            raise ResearchVerificationError(f"Run manifest checksum is invalid for {name}.")
        path = run_directory / name
        if not path.is_file():
            raise ResearchVerificationError(f"Run evidence file is missing: {name}.")
        actual = sha256_file(path)
        if not _secure_text_equal(expected, actual):
            raise ResearchVerificationError(f"Run evidence checksum failed for {name}.")
        verified[name] = actual
    return verified


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ResearchVerificationError(f"Required research evidence is missing: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchVerificationError(
            f"Research evidence is not valid JSON: {path.name}."
        ) from error
    if not isinstance(value, dict):
        raise ResearchVerificationError(f"Research evidence must be a JSON object: {path.name}.")
    return cast(dict[str, Any], value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require_mapping(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise ResearchVerificationError(f"Research evidence field must be an object: {key}.")
    return cast(Mapping[str, Any], value)


def _require_integer(container: Mapping[str, Any], key: str) -> int:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchVerificationError(f"Research evidence field must be an integer: {key}.")
    return value


def _require_number(container: Mapping[str, Any], key: str) -> float:
    value = container.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchVerificationError(f"Research evidence field must be numeric: {key}.")
    number = float(value)
    if not math.isfinite(number):
        raise ResearchVerificationError(f"Research evidence field must be finite: {key}.")
    return number


def _require_equal(actual: object, expected: object, path: str) -> None:
    if isinstance(actual, str) and isinstance(expected, str):
        matches = _secure_text_equal(actual, expected)
    else:
        matches = actual == expected
    if not matches:
        raise ResearchVerificationError(f"Research replay mismatch at {path}.")


def _assert_equivalent(expected: object, actual: object, path: str) -> None:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        if set(expected) != set(actual):
            raise ResearchVerificationError(f"Research replay keys differ at {path}.")
        for key in sorted(expected, key=str):
            _assert_equivalent(expected[key], actual[key], f"{path}.{key}")
        return
    if _is_sequence(expected) and _is_sequence(actual):
        expected_values = cast(Sequence[object], expected)
        actual_values = cast(Sequence[object], actual)
        if len(expected_values) != len(actual_values):
            raise ResearchVerificationError(f"Research replay length differs at {path}.")
        for index, (expected_value, actual_value) in enumerate(
            zip(expected_values, actual_values, strict=True)
        ):
            _assert_equivalent(expected_value, actual_value, f"{path}[{index}]")
        return
    if _is_number(expected) and _is_number(actual):
        expected_number = float(cast(float | int, expected))
        actual_number = float(cast(float | int, actual))
        if not math.isfinite(expected_number) or not math.isclose(
            expected_number,
            actual_number,
            rel_tol=1e-10,
            abs_tol=1e-12,
        ):
            raise ResearchVerificationError(f"Research replay value differs at {path}.")
        return
    if expected != actual:
        raise ResearchVerificationError(f"Research replay value differs at {path}.")


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _secure_text_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
