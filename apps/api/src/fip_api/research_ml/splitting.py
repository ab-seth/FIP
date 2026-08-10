from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from fip_api.research_ml.dataset import ResearchDataset


@dataclass(frozen=True)
class SplitFractions:
    train: float = 0.60
    calibration: float = 0.15
    validation: float = 0.10
    test: float = 0.15

    def validate(self) -> None:
        values = (self.train, self.calibration, self.validation, self.test)
        if any(value <= 0 for value in values):
            raise ValueError("All temporal split fractions must be positive")
        if not np.isclose(sum(values), 1.0):
            raise ValueError("Temporal split fractions must sum to 1")


@dataclass(frozen=True)
class TemporalPartitions:
    train: NDArray[np.int64]
    calibration: NDArray[np.int64]
    validation: NDArray[np.int64]
    test: NDArray[np.int64]

    def named(self) -> tuple[tuple[str, NDArray[np.int64]], ...]:
        return (
            ("train", self.train),
            ("calibration", self.calibration),
            ("validation", self.validation),
            ("test", self.test),
        )


def build_temporal_partitions(
    dataset: ResearchDataset,
    fractions: SplitFractions | None = None,
) -> TemporalPartitions:
    """Build time-ordered partitions without dividing equal timestamps."""

    selected_fractions = fractions or SplitFractions()
    selected_fractions.validate()

    order = np.argsort(dataset.event_time, kind="stable").astype(np.int64)
    ordered_times = dataset.event_time[order]
    row_count = dataset.row_count

    train_target = int(row_count * selected_fractions.train)
    calibration_target = int(
        row_count * (selected_fractions.train + selected_fractions.calibration)
    )
    validation_target = int(
        row_count
        * (
            selected_fractions.train
            + selected_fractions.calibration
            + selected_fractions.validation
        )
    )

    train_end = _move_after_timestamp(ordered_times, train_target)
    calibration_end = _move_after_timestamp(ordered_times, calibration_target)
    validation_end = _move_after_timestamp(ordered_times, validation_target)

    if not 0 < train_end < calibration_end < validation_end < row_count:
        raise ValueError("Timestamps do not permit four non-empty temporal partitions")

    partitions = TemporalPartitions(
        train=order[:train_end],
        calibration=order[train_end:calibration_end],
        validation=order[calibration_end:validation_end],
        test=order[validation_end:],
    )
    _validate_partitions(dataset, partitions)
    return partitions


def _move_after_timestamp(times: NDArray[np.float64], target: int) -> int:
    bounded_target = min(max(target, 1), int(times.shape[0]) - 1)
    boundary_time = times[bounded_target - 1]
    return int(np.searchsorted(times, boundary_time, side="right"))


def _validate_partitions(dataset: ResearchDataset, partitions: TemporalPartitions) -> None:
    previous_maximum: float | None = None
    combined: list[NDArray[np.int64]] = []

    for name, indices in partitions.named():
        if indices.size == 0:
            raise ValueError(f"Temporal {name} partition is empty")
        labels = dataset.labels[indices]
        if np.unique(labels).size != 2:
            raise ValueError(f"Temporal {name} partition must contain both classes")
        minimum = float(np.min(dataset.event_time[indices]))
        maximum = float(np.max(dataset.event_time[indices]))
        if previous_maximum is not None and minimum <= previous_maximum:
            raise ValueError("Temporal partitions overlap at a timestamp boundary")
        previous_maximum = maximum
        combined.append(indices)

    all_indices = np.concatenate(combined)
    if np.unique(all_indices).size != dataset.row_count:
        raise ValueError("Temporal partitions do not cover each row exactly once")
