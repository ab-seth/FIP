from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.features import FEATURE_SET_VERSION
from fip_api.models import (
    DatasetReadinessStatus,
    DatasetSplit,
    OperationalDatasetRow,
)
from fip_api.training_datasets.service import (
    LABEL_CONTRACT_VERSION,
    SPLIT_CONTRACT_VERSION,
    TRAINING_FEATURE_NAMES,
    get_dataset,
    verify_dataset_integrity,
)


class OperationalTrainingBlocked(ValueError):
    """Raised when governance or integrity gates prohibit operational training."""


class OperationalTrainingContractError(ValueError):
    """Raised when a loaded snapshot does not satisfy the training contract."""


@dataclass(frozen=True)
class OperationalTrainingRow:
    row_index: int
    occurred_at: datetime
    split: DatasetSplit
    label: int
    feature_values: dict[str, object]
    row_checksum: str


@dataclass(frozen=True)
class OperationalTrainingDataset:
    dataset_id: str
    display_id: str
    dataset_checksum: str
    feature_set_version: str
    label_contract_version: str
    split_contract_version: str
    feature_names: tuple[str, ...]
    readiness_status: DatasetReadinessStatus
    integrity_verified: bool
    rows: tuple[OperationalTrainingRow, ...]

    def rows_for(self, split: DatasetSplit) -> tuple[OperationalTrainingRow, ...]:
        return tuple(row for row in self.rows if row.split == split)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def positive_count(self) -> int:
        return sum(row.label for row in self.rows)


def load_operational_training_dataset(
    db: Session,
    dataset_id: str,
) -> OperationalTrainingDataset:
    snapshot = get_dataset(db, dataset_id)
    if snapshot.readiness_status != DatasetReadinessStatus.READY.value:
        raise OperationalTrainingBlocked("The operational dataset snapshot is not ready.")
    integrity_verified = verify_dataset_integrity(db, snapshot)
    if not integrity_verified:
        raise OperationalTrainingBlocked(
            "The operational dataset snapshot failed integrity checks."
        )

    stored_rows = tuple(
        db.scalars(
            select(OperationalDatasetRow)
            .where(OperationalDatasetRow.dataset_id == snapshot.id)
            .order_by(OperationalDatasetRow.row_index)
        ).all()
    )
    dataset = OperationalTrainingDataset(
        dataset_id=snapshot.id,
        display_id=snapshot.display_id,
        dataset_checksum=snapshot.dataset_checksum,
        feature_set_version=snapshot.feature_set_version,
        label_contract_version=snapshot.label_contract_version,
        split_contract_version=snapshot.split_contract_version,
        feature_names=tuple(snapshot.feature_names),
        readiness_status=DatasetReadinessStatus(snapshot.readiness_status),
        integrity_verified=integrity_verified,
        rows=tuple(
            OperationalTrainingRow(
                row_index=row.row_index,
                occurred_at=row.occurred_at,
                split=DatasetSplit(row.split),
                label=row.label,
                feature_values=dict(row.feature_values),
                row_checksum=row.row_checksum,
            )
            for row in stored_rows
        ),
    )
    validate_operational_training_dataset(dataset)
    return dataset


def validate_operational_training_dataset(dataset: OperationalTrainingDataset) -> None:
    if dataset.readiness_status is not DatasetReadinessStatus.READY:
        raise OperationalTrainingBlocked("The operational dataset snapshot is not ready.")
    if not dataset.integrity_verified:
        raise OperationalTrainingBlocked(
            "The operational dataset snapshot failed integrity checks."
        )
    if dataset.feature_set_version != FEATURE_SET_VERSION:
        raise OperationalTrainingContractError("The feature-set version is not current.")
    if dataset.label_contract_version != LABEL_CONTRACT_VERSION:
        raise OperationalTrainingContractError("The label contract is not current.")
    if dataset.split_contract_version != SPLIT_CONTRACT_VERSION:
        raise OperationalTrainingContractError("The temporal split contract is not current.")
    if dataset.feature_names != TRAINING_FEATURE_NAMES:
        raise OperationalTrainingContractError("The operational feature allow-list does not match.")
    if len(dataset.dataset_checksum) != 64:
        raise OperationalTrainingContractError("The dataset checksum is not a SHA-256 value.")
    if not dataset.rows:
        raise OperationalTrainingContractError("The operational dataset is empty.")

    expected_indices = list(range(1, len(dataset.rows) + 1))
    if [row.row_index for row in dataset.rows] != expected_indices:
        raise OperationalTrainingContractError("Dataset row indices are not contiguous.")
    if list(dataset.rows) != sorted(
        dataset.rows,
        key=lambda row: (row.occurred_at, row.row_index),
    ):
        raise OperationalTrainingContractError("Dataset rows are not in chronological order.")

    expected_features = set(TRAINING_FEATURE_NAMES)
    for row in dataset.rows:
        if row.label not in {0, 1}:
            raise OperationalTrainingContractError("Operational labels must be binary.")
        if set(row.feature_values) != expected_features:
            raise OperationalTrainingContractError("A row violates the feature allow-list.")
        if len(row.row_checksum) != 64:
            raise OperationalTrainingContractError("A row checksum is not a SHA-256 value.")

    _validate_split_sequence(dataset.rows)
    for split in DatasetSplit:
        labels = {row.label for row in dataset.rows_for(split)}
        if labels != {0, 1}:
            raise OperationalTrainingContractError(
                f"The {split.value} partition must contain both binary classes."
            )


def _validate_split_sequence(rows: Sequence[OperationalTrainingRow]) -> None:
    counts = Counter(row.split for row in rows)
    if set(counts) != set(DatasetSplit):
        raise OperationalTrainingContractError(
            "Train, validation, and test partitions are required."
        )
    split_rank = {
        DatasetSplit.TRAIN: 0,
        DatasetSplit.VALIDATION: 1,
        DatasetSplit.TEST: 2,
    }
    ranks = [split_rank[row.split] for row in rows]
    if ranks != sorted(ranks):
        raise OperationalTrainingContractError("Dataset partitions violate chronological ordering.")
