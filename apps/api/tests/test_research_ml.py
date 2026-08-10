from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from fip_api.research_ml.cli import build_parser
from fip_api.research_ml.dataset import ULB_REQUIRED_COLUMNS, load_ulb_credit_card
from fip_api.research_ml.evaluation import (
    evaluate_probabilities,
    select_threshold_at_fpr,
)
from fip_api.research_ml.fetch_ulb import fetch_ulb
from fip_api.research_ml.pipeline import ExperimentConfig, run_experiment
from fip_api.research_ml.splitting import SplitFractions, build_temporal_partitions
from fip_api.research_ml.training import SigmoidCalibrator


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
