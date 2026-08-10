from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import joblib  # type: ignore[import-untyped]
import numpy as np
import pytest

from fip_api.features import FEATURE_SET_VERSION
from fip_api.models import DatasetReadinessStatus, DatasetSplit
from fip_api.operational_ml.dataset import (
    OperationalTrainingBlocked,
    OperationalTrainingContractError,
    OperationalTrainingDataset,
    OperationalTrainingRow,
    validate_operational_training_dataset,
)
from fip_api.operational_ml.models import (
    AnomalyModelArtifact,
    SupervisedModelArtifact,
    build_training_partitions,
)
from fip_api.operational_ml.pipeline import (
    OperationalTrainingConfig,
    run_operational_training_dataset,
    sha256_file,
)
from fip_api.schemas.model_registry import ModelRegistrationCreate
from fip_api.training_datasets.service import (
    LABEL_CONTRACT_VERSION,
    SPLIT_CONTRACT_VERSION,
    TRAINING_FEATURE_NAMES,
)


@pytest.fixture(scope="module")
def operational_dataset() -> OperationalTrainingDataset:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[OperationalTrainingRow] = []
    for index in range(180):
        label = int(index % 5 == 0)
        split = (
            DatasetSplit.TRAIN
            if index < 126
            else DatasetSplit.VALIDATION
            if index < 153
            else DatasetSplit.TEST
        )
        rows.append(
            OperationalTrainingRow(
                row_index=index + 1,
                occurred_at=started_at + timedelta(hours=index * 2),
                split=split,
                label=label,
                feature_values=_feature_values(index, label),
                row_checksum=f"{index + 1:064x}",
            )
        )
    return OperationalTrainingDataset(
        dataset_id="00000000-0000-0000-0000-000000000001",
        display_id="ODS-TEST-0001",
        dataset_checksum="a" * 64,
        feature_set_version=FEATURE_SET_VERSION,
        label_contract_version=LABEL_CONTRACT_VERSION,
        split_contract_version=SPLIT_CONTRACT_VERSION,
        feature_names=TRAINING_FEATURE_NAMES,
        readiness_status=DatasetReadinessStatus.READY,
        integrity_verified=True,
        rows=tuple(rows),
    )


def test_training_writes_candidate_only_auditable_bundle(
    tmp_path: Path,
    operational_dataset: OperationalTrainingDataset,
) -> None:
    output = tmp_path / "candidate-v1"
    evidence = run_operational_training_dataset(
        operational_dataset,
        OperationalTrainingConfig(output_directory=output, version="2026.08.1"),
    )

    expected_files = {
        "training-evidence.json",
        "run-manifest.json",
        "supervised/model.joblib",
        "supervised/model-card.md",
        "supervised/registration-payload.json",
        "anomaly/model.joblib",
        "anomaly/model-card.md",
        "anomaly/registration-payload.json",
    }
    assert expected_files == {
        str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()
    }
    assert evidence["candidate_only"] is True
    assert evidence["automatic_registration"] is False
    assert evidence["automatic_shadow_promotion"] is False
    assert evidence["live_scoring"] is False
    assert evidence["dataset"]["integrity_verified"] is True
    assert evidence["anomaly"]["training_partition"] == {
        "row_count": 126,
        "positive_count": 26,
        "source_partitions": ["estimator_train", "calibration"],
    }
    assert (
        evidence["partitions"]["estimator_train"]["last_occurred_at"]
        < evidence["partitions"]["calibration"]["first_occurred_at"]
    )
    assert (
        evidence["partitions"]["calibration"]["last_occurred_at"]
        < evidence["partitions"]["validation"]["first_occurred_at"]
    )
    assert (
        evidence["partitions"]["validation"]["last_occurred_at"]
        < evidence["partitions"]["test"]["first_occurred_at"]
    )

    for kind in ("supervised", "anomaly"):
        payload = ModelRegistrationCreate.model_validate_json(
            (output / kind / "registration-payload.json").read_text(encoding="utf-8")
        )
        assert payload.training_dataset_id == operational_dataset.display_id
        assert payload.training_dataset_checksum == operational_dataset.dataset_checksum
        assert payload.training_data_approved is True
        assert payload.operational_feature_compatible is True
        assert payload.decision_threshold is not None

    manifest = json.loads((output / "run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["candidate_only"] is True
    for relative_path, checksum in manifest["files"].items():
        assert sha256_file(output / relative_path) == checksum

    forbidden = {
        "account_reference",
        "external_transaction_id",
        "merchant_reference",
        "case_id",
        "outcome_id",
        "review_id",
    }
    assert forbidden.isdisjoint(evidence["dataset"]["feature_names"])
    evidence_text = (output / "training-evidence.json").read_text(encoding="utf-8")
    assert forbidden.isdisjoint(evidence_text)


def test_written_artifacts_score_raw_operational_features(
    tmp_path: Path,
    operational_dataset: OperationalTrainingDataset,
) -> None:
    output = tmp_path / "scoring-artifacts"
    run_operational_training_dataset(
        operational_dataset,
        OperationalTrainingConfig(output_directory=output, version="2026.08.2"),
    )
    supervised = cast(
        SupervisedModelArtifact,
        joblib.load(output / "supervised" / "model.joblib"),
    )
    anomaly = cast(
        AnomalyModelArtifact,
        joblib.load(output / "anomaly" / "model.joblib"),
    )
    features = [row.feature_values for row in operational_dataset.rows[-8:]]

    supervised_scores = supervised.predict_scores(features)
    anomaly_scores = anomaly.predict_scores(features)

    assert supervised_scores.shape == (8,)
    assert anomaly_scores.shape == (8,)
    assert np.all((supervised_scores >= 0) & (supervised_scores <= 1))
    assert np.all((anomaly_scores >= 0) & (anomaly_scores <= 1))
    assert anomaly.reference_scores.shape == (126,)
    assert np.all(anomaly.reference_scores[:-1] <= anomaly.reference_scores[1:])


def test_same_seed_produces_reproducible_artifacts(
    tmp_path: Path,
    operational_dataset: OperationalTrainingDataset,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_evidence = run_operational_training_dataset(
        operational_dataset,
        OperationalTrainingConfig(output_directory=first, version="2026.08.3", seed=17),
    )
    second_evidence = run_operational_training_dataset(
        operational_dataset,
        OperationalTrainingConfig(output_directory=second, version="2026.08.3", seed=17),
    )

    assert (
        first_evidence["supervised"]["selected_model"]
        == second_evidence["supervised"]["selected_model"]
    )
    assert first_evidence["supervised"]["test"] == second_evidence["supervised"]["test"]
    assert first_evidence["anomaly"]["test"] == second_evidence["anomaly"]["test"]
    assert sha256_file(first / "supervised" / "model.joblib") == sha256_file(
        second / "supervised" / "model.joblib"
    )
    assert sha256_file(first / "anomaly" / "model.joblib") == sha256_file(
        second / "anomaly" / "model.joblib"
    )


@pytest.mark.parametrize(
    ("change", "exception"),
    [
        ({"readiness_status": DatasetReadinessStatus.BLOCKED}, OperationalTrainingBlocked),
        ({"integrity_verified": False}, OperationalTrainingBlocked),
        ({"feature_set_version": "incompatible-v2"}, OperationalTrainingContractError),
        ({"label_contract_version": "unreviewed-labels-v1"}, OperationalTrainingContractError),
        ({"split_contract_version": "random-split-v1"}, OperationalTrainingContractError),
        (
            {"feature_names": tuple(reversed(TRAINING_FEATURE_NAMES))},
            OperationalTrainingContractError,
        ),
    ],
)
def test_training_blocks_unready_or_incompatible_datasets(
    operational_dataset: OperationalTrainingDataset,
    change: dict[str, Any],
    exception: type[Exception],
) -> None:
    with pytest.raises(exception):
        validate_operational_training_dataset(replace(operational_dataset, **change))


def test_calibration_is_a_chronological_training_tail(
    operational_dataset: OperationalTrainingDataset,
) -> None:
    partitions = build_training_partitions(operational_dataset)

    assert len(partitions.estimator_train) == 100
    assert len(partitions.calibration) == 26
    assert partitions.estimator_train[-1].row_index + 1 == partitions.calibration[0].row_index
    assert partitions.calibration[-1].row_index + 1 == partitions.validation[0].row_index
    assert {row.label for row in partitions.estimator_train} == {0, 1}
    assert {row.label for row in partitions.calibration} == {0, 1}


def test_existing_output_directory_is_never_overwritten(
    tmp_path: Path,
    operational_dataset: OperationalTrainingDataset,
) -> None:
    output = tmp_path / "existing"
    output.mkdir()

    with pytest.raises(FileExistsError):
        run_operational_training_dataset(
            operational_dataset,
            OperationalTrainingConfig(output_directory=output, version="2026.08.4"),
        )


def _feature_values(index: int, label: int) -> dict[str, object]:
    values: dict[str, object] = {
        "amount": f"{900 + index * 2:.2f}" if label else f"{20 + index % 80:.2f}",
        "amount_to_median_ratio_30d": "8.50" if label else "1.05",
        "channel": "card_not_present" if label else "card_present",
        "currency": "USD" if index % 3 else "RWF",
        "destination_country": "KE" if label else "RW",
        "is_cross_border": bool(label),
        "is_off_hours_utc": bool(label),
        "is_weekend_utc": index % 7 >= 5,
        "merchant_category_code": "6011" if label else "5411",
        "merchant_seen_before_30d": not bool(label),
        "occurred_day_of_week_utc": index % 7,
        "occurred_hour_utc": 2 if label else 14,
        "prior_same_currency_count_30d": index % 12,
        "prior_same_currency_median_amount_30d": "75.00" if index else None,
        "prior_transaction_count_1h": 8 if label else index % 2,
        "prior_transaction_count_24h": 20 if label else index % 6,
        "prior_transaction_count_30d": 40 if label else index % 20,
        "source_country": "RW",
    }
    assert tuple(values) == TRAINING_FEATURE_NAMES
    return values
