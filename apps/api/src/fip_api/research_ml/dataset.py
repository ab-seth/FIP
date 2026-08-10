from __future__ import annotations

import csv
import shlex
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

ULB_FEATURE_NAMES = ("Time", *(f"V{index}" for index in range(1, 29)), "Amount")
ULB_TARGET_NAME = "Class"
ULB_REQUIRED_COLUMNS = (*ULB_FEATURE_NAMES, ULB_TARGET_NAME)


@dataclass(frozen=True)
class ResearchDataset:
    dataset_id: str
    features: NDArray[np.float64]
    labels: NDArray[np.int64]
    event_time: NDArray[np.float64]
    feature_names: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return int(self.labels.shape[0])

    @property
    def positive_count(self) -> int:
        return int(np.sum(self.labels))


def load_ulb_credit_card(path: Path) -> ResearchDataset:
    """Load the real ULB/OpenML fraud benchmark from CSV or ARFF."""

    if not path.is_file():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".csv":
        columns, matrix = _load_csv(path)
    elif suffix == ".arff":
        columns, matrix = _load_arff(path)
    else:
        raise ValueError("ULB input must use the .csv or .arff extension")

    missing = [name for name in ULB_REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise ValueError(f"ULB dataset is missing required columns: {', '.join(missing)}")
    if matrix.shape[0] < 20:
        raise ValueError("ULB dataset must contain at least 20 rows")

    column_positions = {name: index for index, name in enumerate(columns)}
    feature_positions = [column_positions[name] for name in ULB_FEATURE_NAMES]
    features = np.asarray(matrix[:, feature_positions], dtype=np.float64)
    labels_raw = np.asarray(matrix[:, column_positions[ULB_TARGET_NAME]], dtype=np.float64)

    if not np.all(np.isfinite(features)) or not np.all(np.isfinite(labels_raw)):
        raise ValueError("ULB dataset contains non-finite values")
    if not np.all(np.isin(labels_raw, (0.0, 1.0))):
        raise ValueError("ULB Class must contain only 0 and 1")

    labels = labels_raw.astype(np.int64)
    if np.unique(labels).size != 2:
        raise ValueError("ULB dataset must contain both fraud and non-fraud labels")

    return ResearchDataset(
        dataset_id="openml-1597-v1",
        features=features,
        labels=labels,
        event_time=np.asarray(features[:, 0], dtype=np.float64),
        feature_names=ULB_FEATURE_NAMES,
    )


def _load_csv(path: Path) -> tuple[tuple[str, ...], NDArray[np.float64]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header_line = handle.readline()
        if not header_line:
            raise ValueError("ULB CSV is empty")
        header = next(csv.reader([header_line]))
        matrix = np.loadtxt(
            handle,
            delimiter=",",
            dtype=np.float64,
            ndmin=2,
            quotechar="'",
        )
    return tuple(value.strip() for value in header), np.asarray(matrix, dtype=np.float64)


def _load_arff(path: Path) -> tuple[tuple[str, ...], NDArray[np.float64]]:
    attributes: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("%"):
                continue
            lowered = line.lower()
            if lowered.startswith("@attribute"):
                parts = shlex.split(line)
                if len(parts) < 3:
                    raise ValueError(f"Invalid ARFF attribute declaration: {line}")
                attributes.append(parts[1])
            elif lowered == "@data":
                break
        else:
            raise ValueError("ULB ARFF does not contain an @data section")

        matrix = np.loadtxt(
            handle,
            delimiter=",",
            dtype=np.float64,
            ndmin=2,
            quotechar="'",
        )

    if matrix.shape[1] != len(attributes):
        raise ValueError("ULB ARFF column count does not match its attributes")
    return tuple(attributes), np.asarray(matrix, dtype=np.float64)
