from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from fip_api.core.checksums import canonical_json_checksum
from fip_api.research_ml.artifact import sha256_file
from fip_api.research_ml.cli import build_parser
from fip_api.research_ml.dataset import ULB_REQUIRED_COLUMNS, load_ulb_credit_card
from fip_api.research_ml.dossier import (
    CandidateDossierConfig,
    ResearchVerificationError,
    build_candidate_dossier,
)
from fip_api.research_ml.dossier_cli import build_parser as build_dossier_parser
from fip_api.research_ml.evaluation import (
    evaluate_probabilities,
    select_threshold_at_fpr,
)
from fip_api.research_ml.fetch_ulb import fetch_ulb
from fip_api.research_ml.pipeline import ExperimentConfig, run_experiment
from fip_api.research_ml.splitting import SplitFractions, build_temporal_partitions
from fip_api.research_ml.training import SigmoidCalibrator
from fip_api.schemas.model_registry import ModelRegistrationCreate


def _write_ulb_csv(path: Path, row_count: int = 240) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(ULB_REQUIRED_COLUMNS)
        for index in range(row_count):
            label = int(index % 10 == 3)
            event_time = float(index // 2)
            pca_features = [
                (4.0 * label if feature_index == 1 else 0.0)
                + ((index * (feature_index + 3)) % 17) / 20.0
                for feature_index in range(1, 29)
            ]
            amount = 800.0 + index if label else 20.0 + (index % 13)
            writer.writerow([event_time, *pca_features, amount, label])


@pytest.fixture(scope="module")
def completed_research_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, Path]:
    root = tmp_path_factory.mktemp("completed-research-run")
    source = root / "creditcard.csv"
    dataset_manifest = root / "ulb-manifest.json"
    run_directory = root / "run"
    _write_ulb_csv(source)
    dataset_manifest.write_text(
        json.dumps(
            {
                "dataset_id": "openml-1597-v1",
                "provider_md5": hashlib.md5(
                    source.read_bytes(),
                    usedforsecurity=False,
                ).hexdigest(),
                "provider_license_value": "Public",
                "access_status": "approved_for_research_methodology",
                "operational_feature_compatible": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    run_experiment(
        ExperimentConfig(
            input_path=source,
            output_directory=run_directory,
            seed=17,
            maximum_false_positive_rate=0.10,
        )
    )
    return source, dataset_manifest, run_directory


def _dossier_config(
    *,
    input_path: Path,
    dataset_manifest_path: Path,
    run_directory: Path,
    output_directory: Path,
) -> CandidateDossierConfig:
    return CandidateDossierConfig(
        input_path=input_path,
        dataset_manifest_path=dataset_manifest_path,
        run_directory=run_directory,
        output_directory=output_directory,
        model_key="ulb-fraud-research",
        version="openml-1597-v1-seed-17",
        model_card_reference="docs/evidence/ulb-credit-card-v1-seed-17.md",
    )


def _rewrite_manifest_checksum(run_directory: Path, name: str) -> None:
    manifest_path = run_directory / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name] = sha256_file(run_directory / name)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_load_and_split_ulb_without_timestamp_leakage(tmp_path: Path) -> None:
    source = tmp_path / "creditcard.csv"
    _write_ulb_csv(source)

    dataset = load_ulb_credit_card(source)
    partitions = build_temporal_partitions(dataset)

    assert dataset.row_count == 240
    assert dataset.positive_count == 24
    assert dataset.features.shape == (240, 30)
    partition_indices = [indices for _, indices in partitions.named()]
    assert sum(indices.size for indices in partition_indices) == 240

    for earlier, later in zip(partition_indices, partition_indices[1:], strict=False):
        assert np.max(dataset.event_time[earlier]) < np.min(dataset.event_time[later])


def test_load_ulb_arff_with_quoted_class_values(tmp_path: Path) -> None:
    source_csv = tmp_path / "creditcard.csv"
    _write_ulb_csv(source_csv, row_count=20)
    rows = list(csv.reader(source_csv.read_text(encoding="utf-8").splitlines()))
    source_arff = tmp_path / "creditcard.arff"
    header = ["@relation creditcard"]
    for column in ULB_REQUIRED_COLUMNS:
        data_type = "{'0','1'}" if column == "Class" else "numeric"
        header.append(f"@attribute {column} {data_type}")
    header.append("@data")
    data_rows = [",".join((*row[:-1], f"'{row[-1]}'")) for row in rows[1:]]
    source_arff.write_text("\n".join((*header, *data_rows)), encoding="utf-8")

    dataset = load_ulb_credit_card(source_arff)

    assert dataset.row_count == 20
    assert dataset.positive_count == 2


def test_research_pipeline_writes_reproducible_evidence(tmp_path: Path) -> None:
    source = tmp_path / "creditcard.csv"
    output = tmp_path / "run"
    _write_ulb_csv(source)

    result = run_experiment(
        ExperimentConfig(
            input_path=source,
            output_directory=output,
            seed=17,
            maximum_false_positive_rate=0.10,
        )
    )

    assert result["research_only"] is True
    assert result["selected_model"] in {"logistic-regression", "hist-gradient-boosting"}
    assert len(result["explainability"]["features"]) == 30
    assert 0.0 <= result["test"]["false_positive_rate"] <= 1.0
    assert (
        result["dataset"]["source_file_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert {path.name for path in output.iterdir()} == {
        "metrics.json",
        "model.joblib",
        "model-card.md",
        "run-manifest.json",
    }
    model_card = (output / "model-card.md").read_text(encoding="utf-8")
    assert "research-only methodology benchmark" in model_card
    assert "Global research explanation" in model_card
    assert "Not eligible for operational promotion" in model_card

    manifest = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["research_only"] is True
    assert len(manifest["files"]["model.joblib"]) == 64

    with pytest.raises(FileExistsError):
        run_experiment(ExperimentConfig(input_path=source, output_directory=output))


def test_candidate_dossier_replays_training_and_exports_research_registration(
    tmp_path: Path,
    completed_research_run: tuple[Path, Path, Path],
) -> None:
    source, dataset_manifest, run_directory = completed_research_run
    output = tmp_path / "candidate-bundle"

    dossier = build_candidate_dossier(
        _dossier_config(
            input_path=source,
            dataset_manifest_path=dataset_manifest,
            run_directory=run_directory,
            output_directory=output,
        )
    )

    assert output.is_dir()
    assert {path.name for path in output.iterdir()} == {
        "bundle-manifest.json",
        "candidate-dossier.json",
        "candidate-registration.json",
        "model-card.md",
        "model.joblib",
    }
    assert dossier["verification"] == {
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
    }
    registration = ModelRegistrationCreate.model_validate(dossier["candidate_registration"])
    assert registration.purpose.value == "research"
    assert registration.training_data_approved is False
    assert registration.operational_feature_compatible is False
    assert registration.feature_set_version == "openml-1597-ulb-pca-v1"
    assert int(registration.evaluation_metrics["evaluated_row_count"]) > 0
    assert registration.evaluation_metrics["verification_method"] == ("full-deterministic-replay")
    assert (
        registration.evaluation_metrics["dataset_manifest_checksum"]
        == dossier["dataset_manifest_sha256"]
    )
    assert registration.artifact_sha256 == sha256_file(output / "model.joblib")
    assert registration.model_card_checksum == sha256_file(output / "model-card.md")
    assert (
        json.loads((output / "candidate-registration.json").read_text(encoding="utf-8"))
        == dossier["candidate_registration"]
    )
    bundle_manifest = json.loads((output / "bundle-manifest.json").read_text(encoding="utf-8"))
    assert bundle_manifest["research_only"] is True
    assert bundle_manifest["files"]["model.joblib"] == registration.artifact_sha256
    checksum_facts = dict(dossier)
    dossier_checksum = checksum_facts.pop("dossier_checksum")
    assert dossier_checksum == canonical_json_checksum(checksum_facts)

    with pytest.raises(FileExistsError):
        build_candidate_dossier(
            _dossier_config(
                input_path=source,
                dataset_manifest_path=dataset_manifest,
                run_directory=run_directory,
                output_directory=output,
            )
        )


def test_candidate_dossier_rejects_rechecksummed_artifact_tampering(
    tmp_path: Path,
    completed_research_run: tuple[Path, Path, Path],
) -> None:
    source, dataset_manifest, original_run = completed_research_run
    run_directory = tmp_path / "tampered-artifact-run"
    shutil.copytree(original_run, run_directory)
    artifact_path = run_directory / "model.joblib"
    artifact_path.write_bytes(artifact_path.read_bytes() + b"tampered")
    _rewrite_manifest_checksum(run_directory, "model.joblib")

    with pytest.raises(ResearchVerificationError, match="source model-card checksum"):
        build_candidate_dossier(
            _dossier_config(
                input_path=source,
                dataset_manifest_path=dataset_manifest,
                run_directory=run_directory,
                output_directory=tmp_path / "artifact-candidate-bundle",
            )
        )


def test_candidate_dossier_rejects_rechecksummed_metric_tampering(
    tmp_path: Path,
    completed_research_run: tuple[Path, Path, Path],
) -> None:
    source, dataset_manifest, original_run = completed_research_run
    run_directory = tmp_path / "tampered-metrics-run"
    shutil.copytree(original_run, run_directory)
    metrics_path = run_directory / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["test"]["average_precision"] += 0.01
    metrics_path.write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _rewrite_manifest_checksum(run_directory, "metrics.json")

    with pytest.raises(ResearchVerificationError, match="held-out test evaluation"):
        build_candidate_dossier(
            _dossier_config(
                input_path=source,
                dataset_manifest_path=dataset_manifest,
                run_directory=run_directory,
                output_directory=tmp_path / "metrics-candidate-bundle",
            )
        )


def test_candidate_dossier_rejects_rechecksummed_model_card_tampering(
    tmp_path: Path,
    completed_research_run: tuple[Path, Path, Path],
) -> None:
    source, dataset_manifest, original_run = completed_research_run
    run_directory = tmp_path / "tampered-card-run"
    shutil.copytree(original_run, run_directory)
    card_path = run_directory / "model-card.md"
    card_path.write_text(
        card_path.read_text(encoding="utf-8") + "\nOperationally approved.\n",
        encoding="utf-8",
    )
    _rewrite_manifest_checksum(run_directory, "model-card.md")

    with pytest.raises(ResearchVerificationError, match="source model-card checksum"):
        build_candidate_dossier(
            _dossier_config(
                input_path=source,
                dataset_manifest_path=dataset_manifest,
                run_directory=run_directory,
                output_directory=tmp_path / "card-candidate-bundle",
            )
        )


def test_candidate_dossier_rejects_different_raw_dataset(
    tmp_path: Path,
    completed_research_run: tuple[Path, Path, Path],
) -> None:
    _, dataset_manifest, run_directory = completed_research_run
    different_source = tmp_path / "different-creditcard.csv"
    _write_ulb_csv(different_source, row_count=260)

    with pytest.raises(ResearchVerificationError, match="approved provider MD5"):
        build_candidate_dossier(
            _dossier_config(
                input_path=different_source,
                dataset_manifest_path=dataset_manifest,
                run_directory=run_directory,
                output_directory=tmp_path / "dataset-candidate-bundle",
            )
        )


def test_evaluation_selects_threshold_under_false_positive_limit() -> None:
    labels = np.asarray([0, 0, 0, 0, 1, 1], dtype=np.int64)
    probabilities = np.asarray([0.01, 0.05, 0.10, 0.20, 0.80, 0.95], dtype=np.float64)

    threshold = select_threshold_at_fpr(labels, probabilities, 0.01)
    metrics = evaluate_probabilities(labels, probabilities, threshold)

    assert threshold == pytest.approx(0.80)
    assert metrics.false_positive_rate == 0.0
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0


def test_research_validation_rejects_unsafe_inputs(tmp_path: Path) -> None:
    unsupported = tmp_path / "creditcard.txt"
    unsupported.write_text("not a dataset", encoding="utf-8")
    with pytest.raises(ValueError, match="extension"):
        load_ulb_credit_card(unsupported)

    incomplete = tmp_path / "incomplete.csv"
    incomplete.write_text("Time,Class\n0,0\n1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_ulb_credit_card(incomplete)

    with pytest.raises(ValueError, match="sum to 1"):
        SplitFractions(test=0.20).validate()
    with pytest.raises(ValueError, match="between 0 and 1"):
        select_threshold_at_fpr(
            np.asarray([0, 1], dtype=np.int64),
            np.asarray([0.1, 0.9], dtype=np.float64),
            1.0,
        )
    with pytest.raises(RuntimeError, match="not been fitted"):
        SigmoidCalibrator().predict(np.asarray([0.5], dtype=np.float64))


def test_fetch_ulb_verifies_provider_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"@relation creditcard\n@data\n0,1\n"
    expected_md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    monkeypatch.setattr("fip_api.research_ml.fetch_ulb.ULB_OPENML_MD5", expected_md5)
    monkeypatch.setattr(
        "fip_api.research_ml.fetch_ulb.urllib.request.urlopen",
        lambda request, timeout: io.BytesIO(payload),
    )
    output = tmp_path / "creditcard.arff"

    metadata = fetch_ulb(output)

    assert output.read_bytes() == payload
    assert metadata["provider_md5"] == expected_md5
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    with pytest.raises(FileExistsError):
        fetch_ulb(output)


def test_cli_requires_input_and_output() -> None:
    arguments = build_parser().parse_args(
        ["--input", "data/raw/creditcard.arff", "--output", "artifacts/run"]
    )
    assert arguments.dataset == "ulb-credit-card"
    assert arguments.seed == 42

    dossier_arguments = build_dossier_parser().parse_args(
        [
            "--input",
            "data/raw/creditcard.arff",
            "--dataset-manifest",
            "data/manifests/ulb-credit-card-v1.json",
            "--run",
            "artifacts/research/ulb-seed-42",
            "--output",
            "artifacts/research/ulb-seed-42-candidate",
            "--model-key",
            "ulb-fraud-research",
            "--version",
            "openml-1597-v1-seed-42",
            "--model-card-reference",
            "artifacts/research/ulb-seed-42-candidate/model-card.md",
        ]
    )
    assert dossier_arguments.model_key == "ulb-fraud-research"
    assert dossier_arguments.version == "openml-1597-v1-seed-42"
    assert dossier_arguments.dataset_manifest == Path("data/manifests/ulb-credit-card-v1.json")
