from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from fip_api.core.checksums import canonical_json_checksum
from fip_api.core.object_store import (
    ObjectStoreError,
    ObjectStoreObjectMissing,
    S3ObjectStore,
)
from fip_api.operational_ml import PIPELINE_VERSION
from fip_api.operational_ml.pipeline import sha256_file
from fip_api.schemas.model_registry import ModelRegistrationCreate

EXPECTED_BUNDLE_FILES = {
    "training-evidence.json",
    "supervised/model.joblib",
    "supervised/model-card.md",
    "supervised/registration-payload.json",
    "anomaly/model.joblib",
    "anomaly/model-card.md",
    "anomaly/registration-payload.json",
}
ARTIFACT_PATHS = {
    ("supervised", "model"): "supervised/model.joblib",
    ("supervised", "model-card"): "supervised/model-card.md",
    ("supervised", "registration"): "supervised/registration-payload.json",
    ("anomaly", "model"): "anomaly/model.joblib",
    ("anomaly", "model-card"): "anomaly/model-card.md",
    ("anomaly", "registration"): "anomaly/registration-payload.json",
}
EVIDENCE_PATHS = {
    "training-evidence": "training-evidence.json",
    "run-manifest": "run-manifest.json",
}
BUNDLE_KEY_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_JSON_BYTES = 4 * 1024 * 1024
EXPECTED_CANDIDATE_CONTRACTS = {
    "supervised": ("canonical-fraud-classifier", "binary-probability-v1"),
    "anomaly": ("canonical-transaction-anomaly", "anomaly-score-v1"),
}


class TrainingBundleError(ValueError):
    pass


class TrainingBundleMissing(TrainingBundleError):
    pass


class TrainingBundleIntegrityError(TrainingBundleError):
    pass


@dataclass(frozen=True)
class TrainingBundleInspection:
    bundle_key: str
    summary: dict[str, object]
    evidence_checksum: str
    manifest_checksum: str
    bundle_checksum: str


class TrainingArtifactStore:
    def __init__(self, root: Path, *, max_artifact_bytes: int) -> None:
        self.root = root
        self.max_artifact_bytes = max_artifact_bytes

    def output_directory(self, bundle_key: str) -> Path:
        key = _validated_bundle_key(bundle_key)
        return self.root / key

    def inspect(  # noqa: PLR0913
        self,
        bundle_key: str,
        *,
        candidate_version: str,
        configuration_checksum: str,
        dataset_checksum: str,
        dataset_display_id: str,
        dataset_feature_set_version: str,
        maximum_false_positive_rate: str,
        seed: int,
    ) -> TrainingBundleInspection:
        directory = self.output_directory(bundle_key)
        _verify_directory(directory)
        manifest_path = directory / "run-manifest.json"
        manifest = _read_json(manifest_path)
        files = manifest.get("files")
        if (
            manifest.get("pipeline_version") != PIPELINE_VERSION
            or manifest.get("candidate_only") is not True
            or manifest.get("automatic_registration") is not False
            or manifest.get("automatic_shadow_promotion") is not False
            or manifest.get("live_scoring") is not False
            or not isinstance(files, dict)
            or set(files) != EXPECTED_BUNDLE_FILES
        ):
            raise TrainingBundleIntegrityError("The candidate run manifest is not governed.")

        normalized_files: dict[str, str] = {}
        for relative_path, expected_checksum in files.items():
            if not isinstance(relative_path, str) or not isinstance(expected_checksum, str):
                raise TrainingBundleIntegrityError("The candidate manifest contains invalid data.")
            path = _safe_file(directory, relative_path, max_bytes=self.max_artifact_bytes)
            actual_checksum = sha256_file(path)
            if actual_checksum != expected_checksum:
                raise TrainingBundleIntegrityError(
                    f"Candidate artifact integrity failed for {relative_path}."
                )
            normalized_files[relative_path] = actual_checksum
        expected_paths = EXPECTED_BUNDLE_FILES | {"run-manifest.json"}
        if {path for path in directory.rglob("*") if path.is_file()} != {
            directory / relative_path for relative_path in expected_paths
        }:
            raise TrainingBundleIntegrityError("The candidate bundle contains unexpected files.")
        if {path for path in directory.rglob("*") if path.is_dir()} != {
            directory / "supervised",
            directory / "anomaly",
        }:
            raise TrainingBundleIntegrityError(
                "The candidate bundle contains unexpected directories."
            )

        evidence = _read_json(directory / "training-evidence.json")
        dataset = evidence.get("dataset")
        configuration = evidence.get("configuration")
        if (
            evidence.get("pipeline_version") != PIPELINE_VERSION
            or evidence.get("candidate_only") is not True
            or evidence.get("automatic_registration") is not False
            or evidence.get("automatic_shadow_promotion") is not False
            or evidence.get("live_scoring") is not False
            or not isinstance(dataset, dict)
            or dataset.get("id") != dataset_display_id
            or dataset.get("checksum") != dataset_checksum
            or dataset.get("integrity_verified") is not True
            or dataset.get("readiness_status") != "ready"
            or dataset.get("feature_set_version") != dataset_feature_set_version
            or not isinstance(configuration, dict)
            or configuration.get("version") != candidate_version
            or configuration.get("seed") != seed
            or _number_text(configuration.get("maximum_false_positive_rate"))
            != _number_text(maximum_false_positive_rate)
        ):
            raise TrainingBundleIntegrityError("The candidate training evidence is inconsistent.")

        summary: dict[str, object] = {}
        for kind in ("supervised", "anomaly"):
            try:
                registration = ModelRegistrationCreate.model_validate(
                    _read_json(directory / kind / "registration-payload.json")
                )
            except ValidationError as exc:
                raise TrainingBundleIntegrityError(
                    f"The {kind} registration handoff is malformed."
                ) from exc
            expected_model_key, expected_runtime_contract = EXPECTED_CANDIDATE_CONTRACTS[kind]
            if (
                registration.model_key != expected_model_key
                or registration.kind.value != kind
                or registration.purpose.value != "operational"
                or registration.runtime_contract.value != expected_runtime_contract
                or registration.version != candidate_version
                or registration.feature_set_version != dataset_feature_set_version
                or registration.training_dataset_id != dataset_display_id
                or registration.training_dataset_checksum != dataset_checksum
                or registration.artifact_sha256 != normalized_files[f"{kind}/model.joblib"]
                or registration.model_card_checksum != normalized_files[f"{kind}/model-card.md"]
                or registration.model_card_reference != f"{kind}/model-card.md"
                or registration.training_data_approved is not True
                or registration.operational_feature_compatible is not True
                or registration.decision_threshold is None
            ):
                raise TrainingBundleIntegrityError(
                    f"The {kind} registration handoff is inconsistent."
                )
            kind_evidence = evidence.get(kind)
            if not isinstance(kind_evidence, dict):
                raise TrainingBundleIntegrityError(f"The {kind} evidence is missing.")
            selected_model = (
                kind_evidence.get("selected_model")
                if kind == "supervised"
                else kind_evidence.get("model")
            )
            if (
                not isinstance(selected_model, str)
                or not selected_model
                or kind_evidence.get("artifact_sha256") != registration.artifact_sha256
                or _number_text(kind_evidence.get("threshold"))
                != _number_text(registration.decision_threshold)
            ):
                raise TrainingBundleIntegrityError(f"The {kind} evidence is inconsistent.")
            summary[kind] = {
                "model_key": registration.model_key,
                "version": registration.version,
                "kind": registration.kind.value,
                "runtime_contract": registration.runtime_contract.value,
                "artifact_sha256": registration.artifact_sha256,
                "model_card_checksum": registration.model_card_checksum,
                "registration_payload_checksum": normalized_files[
                    f"{kind}/registration-payload.json"
                ],
                "decision_threshold": (
                    str(registration.decision_threshold)
                    if registration.decision_threshold is not None
                    else None
                ),
                "evaluation_metrics": registration.evaluation_metrics,
                "selected_model": selected_model,
            }

        evidence_checksum = normalized_files["training-evidence.json"]
        manifest_checksum = sha256_file(manifest_path)
        bundle_checksum = canonical_json_checksum(
            {
                "pipeline_version": PIPELINE_VERSION,
                "configuration_checksum": configuration_checksum,
                "dataset_checksum": dataset_checksum,
                "evidence_checksum": evidence_checksum,
                "manifest_checksum": manifest_checksum,
                "files": normalized_files,
                "summary": summary,
            }
        )
        return TrainingBundleInspection(
            bundle_key=bundle_key,
            summary=summary,
            evidence_checksum=evidence_checksum,
            manifest_checksum=manifest_checksum,
            bundle_checksum=bundle_checksum,
        )

    def artifact_path(
        self,
        bundle_key: str,
        *,
        model_kind: str,
        artifact_name: str,
    ) -> Path:
        relative_path = ARTIFACT_PATHS.get((model_kind, artifact_name))
        if relative_path is None:
            raise TrainingBundleMissing("Candidate artifact not found.")
        return _safe_file(
            self.output_directory(bundle_key),
            relative_path,
            max_bytes=self.max_artifact_bytes,
        )

    def evidence_path(self, bundle_key: str, *, evidence_name: str) -> Path:
        relative_path = EVIDENCE_PATHS.get(evidence_name)
        if relative_path is None:
            raise TrainingBundleMissing("Candidate evidence not found.")
        return _safe_file(
            self.output_directory(bundle_key),
            relative_path,
            max_bytes=MAX_JSON_BYTES,
        )

    def make_immutable(self, bundle_key: str) -> None:
        directory = self.output_directory(bundle_key)
        _verify_directory(directory)
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_symlink():
                raise TrainingBundleIntegrityError("Candidate bundles cannot contain symlinks.")
            path.chmod(0o440 if path.is_file() else 0o550)
        directory.chmod(0o550)


class S3TrainingArtifactStore(TrainingArtifactStore):
    """Verified local training-bundle cache backed by S3-compatible storage."""

    def __init__(
        self,
        root: Path,
        *,
        max_artifact_bytes: int,
        object_store: S3ObjectStore,
    ) -> None:
        super().__init__(root, max_artifact_bytes=max_artifact_bytes)
        self.object_store = object_store

    def inspect(  # noqa: PLR0913
        self,
        bundle_key: str,
        *,
        candidate_version: str,
        configuration_checksum: str,
        dataset_checksum: str,
        dataset_display_id: str,
        dataset_feature_set_version: str,
        maximum_false_positive_rate: str,
        seed: int,
    ) -> TrainingBundleInspection:
        self._ensure_local(bundle_key)
        return super().inspect(
            bundle_key,
            candidate_version=candidate_version,
            configuration_checksum=configuration_checksum,
            dataset_checksum=dataset_checksum,
            dataset_display_id=dataset_display_id,
            dataset_feature_set_version=dataset_feature_set_version,
            maximum_false_positive_rate=maximum_false_positive_rate,
            seed=seed,
        )

    def artifact_path(
        self,
        bundle_key: str,
        *,
        model_kind: str,
        artifact_name: str,
    ) -> Path:
        self._ensure_local(bundle_key)
        return super().artifact_path(
            bundle_key,
            model_kind=model_kind,
            artifact_name=artifact_name,
        )

    def evidence_path(self, bundle_key: str, *, evidence_name: str) -> Path:
        self._ensure_local(bundle_key)
        return super().evidence_path(bundle_key, evidence_name=evidence_name)

    def make_immutable(self, bundle_key: str) -> None:
        key = _validated_bundle_key(bundle_key)
        super().make_immutable(key)
        directory = self.output_directory(key)
        try:
            for relative_path in sorted(EXPECTED_BUNDLE_FILES | {"run-manifest.json"}):
                path = _safe_file(
                    directory,
                    relative_path,
                    max_bytes=self.max_artifact_bytes,
                )
                self.object_store.upload_file(
                    self._remote_key(key, relative_path),
                    path,
                    checksum=sha256_file(path),
                    content_type=_content_type(relative_path),
                )
        except ObjectStoreError as exc:
            raise TrainingBundleIntegrityError(
                "The verified candidate bundle could not be persisted remotely."
            ) from exc

    def _ensure_local(self, bundle_key: str) -> None:
        key = _validated_bundle_key(bundle_key)
        destination = self.output_directory(key)
        if destination.exists() or destination.is_symlink():
            return
        self.root.mkdir(mode=0o750, parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=self.root))
        try:
            for relative_path in sorted(EXPECTED_BUNDLE_FILES | {"run-manifest.json"}):
                local_path = temporary / relative_path
                local_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
                self.object_store.download_file(
                    self._remote_key(key, relative_path),
                    local_path,
                    max_bytes=(
                        MAX_JSON_BYTES
                        if relative_path.endswith(".json")
                        else self.max_artifact_bytes
                    ),
                )
            for path in sorted(temporary.rglob("*"), reverse=True):
                path.chmod(0o440 if path.is_file() else 0o550)
            temporary.chmod(0o550)
            try:
                os.rename(temporary, destination)
            except FileExistsError:
                shutil.rmtree(temporary)
        except ObjectStoreObjectMissing as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            raise TrainingBundleMissing("The candidate bundle is not available.") from exc
        except ObjectStoreError as exc:
            shutil.rmtree(temporary, ignore_errors=True)
            raise TrainingBundleIntegrityError(
                "The remote candidate bundle could not be cached safely."
            ) from exc
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    @staticmethod
    def _remote_key(bundle_key: str, relative_path: str) -> str:
        return f"training-artifacts/{bundle_key}/{relative_path}"


def _validated_bundle_key(value: str) -> str:
    if not BUNDLE_KEY_PATTERN.fullmatch(value):
        raise TrainingBundleIntegrityError("The candidate bundle key is invalid.")
    return value


def _verify_directory(directory: Path) -> None:
    try:
        metadata = directory.lstat()
    except FileNotFoundError as exc:
        raise TrainingBundleMissing("The candidate bundle is not available.") from exc
    if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink():
        raise TrainingBundleIntegrityError("The candidate bundle path is unsafe.")


def _safe_file(directory: Path, relative_path: str, *, max_bytes: int) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise TrainingBundleIntegrityError("The candidate manifest contains an unsafe path.")
    current = directory
    for part in relative.parts[:-1]:
        current /= part
        try:
            parent_metadata = current.lstat()
        except FileNotFoundError as exc:
            raise TrainingBundleMissing(f"Candidate artifact directory {part} is missing.") from exc
        if current.is_symlink() or not stat.S_ISDIR(parent_metadata.st_mode):
            raise TrainingBundleIntegrityError(f"Candidate artifact directory {part} is unsafe.")
    path = directory / relative
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise TrainingBundleMissing(f"Candidate artifact {relative_path} is missing.") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise TrainingBundleIntegrityError(f"Candidate artifact {relative_path} is unsafe.")
    if metadata.st_size <= 0 or metadata.st_size > max_bytes:
        raise TrainingBundleIntegrityError(f"Candidate artifact {relative_path} has invalid size.")
    return path


def _read_json(path: Path) -> dict[str, object]:
    safe = _safe_file(path.parent, path.name, max_bytes=MAX_JSON_BYTES)
    try:
        value = json.loads(safe.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrainingBundleIntegrityError(f"Candidate evidence {path.name} is invalid.") from exc
    if not isinstance(value, dict):
        raise TrainingBundleIntegrityError(f"Candidate evidence {path.name} must be an object.")
    return value


def _number_text(value: object) -> str:
    try:
        return format(float(str(value)), ".12g")
    except ValueError:
        return str(value)


def _content_type(relative_path: str) -> str:
    if relative_path.endswith(".json"):
        return "application/json"
    if relative_path.endswith(".md"):
        return "text/markdown; charset=utf-8"
    return "application/octet-stream"
