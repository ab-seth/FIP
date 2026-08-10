from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Self

import numpy as np
from numpy.typing import NDArray

from fip_api.training_datasets.service import TRAINING_FEATURE_NAMES

NUMERIC_FEATURE_NAMES = (
    "amount",
    "amount_to_median_ratio_30d",
    "occurred_day_of_week_utc",
    "occurred_hour_utc",
    "prior_same_currency_count_30d",
    "prior_same_currency_median_amount_30d",
    "prior_transaction_count_1h",
    "prior_transaction_count_24h",
    "prior_transaction_count_30d",
)
CATEGORICAL_FEATURE_NAMES = tuple(
    name for name in TRAINING_FEATURE_NAMES if name not in NUMERIC_FEATURE_NAMES
)
MISSING_CATEGORY = "<MISSING>"
UNKNOWN_CATEGORY = "<UNKNOWN>"


class OperationalPreprocessor:
    """Deterministic numeric scaling and categorical encoding for semantic features."""

    def __init__(self) -> None:
        self.numeric_medians: dict[str, float] = {}
        self.numeric_means: dict[str, float] = {}
        self.numeric_scales: dict[str, float] = {}
        self.category_values: dict[str, tuple[str, ...]] = {}
        self.output_feature_names: tuple[str, ...] = ()

    def fit(self, rows: Sequence[Mapping[str, object]]) -> Self:
        if not rows:
            raise ValueError("At least one row is required to fit preprocessing.")
        _validate_rows(rows)

        for name in NUMERIC_FEATURE_NAMES:
            present = [_numeric(row[name]) for row in rows]
            observed = np.asarray(
                [value for value in present if value is not None],
                dtype=np.float64,
            )
            median = float(np.median(observed)) if observed.size else 0.0
            imputed = np.asarray(
                [median if value is None else value for value in present],
                dtype=np.float64,
            )
            mean = float(np.mean(imputed))
            scale = float(np.std(imputed))
            self.numeric_medians[name] = median
            self.numeric_means[name] = mean
            self.numeric_scales[name] = scale if scale > 0 else 1.0

        for name in CATEGORICAL_FEATURE_NAMES:
            observed_categories = sorted({_category(row[name]) for row in rows})
            categories = tuple(
                [UNKNOWN_CATEGORY]
                + [value for value in observed_categories if value != UNKNOWN_CATEGORY]
            )
            self.category_values[name] = categories

        encoded_names = list(NUMERIC_FEATURE_NAMES)
        for name in CATEGORICAL_FEATURE_NAMES:
            encoded_names.extend(f"{name}={value}" for value in self.category_values[name])
        self.output_feature_names = tuple(encoded_names)
        return self

    def transform(self, rows: Sequence[Mapping[str, object]]) -> NDArray[np.float64]:
        if not self.output_feature_names:
            raise RuntimeError("Preprocessor has not been fitted.")
        _validate_rows(rows)
        result = np.zeros((len(rows), len(self.output_feature_names)), dtype=np.float64)
        for row_index, row in enumerate(rows):
            column = 0
            for name in NUMERIC_FEATURE_NAMES:
                value = _numeric(row[name])
                imputed = self.numeric_medians[name] if value is None else value
                result[row_index, column] = (
                    imputed - self.numeric_means[name]
                ) / self.numeric_scales[name]
                column += 1
            for name in CATEGORICAL_FEATURE_NAMES:
                categories = self.category_values[name]
                category_value = _category(row[name])
                try:
                    offset = categories.index(category_value)
                except ValueError:
                    offset = categories.index(UNKNOWN_CATEGORY)
                result[row_index, column + offset] = 1.0
                column += len(categories)
        return result

    def fit_transform(self, rows: Sequence[Mapping[str, object]]) -> NDArray[np.float64]:
        return self.fit(rows).transform(rows)

    def evidence(self) -> dict[str, object]:
        if not self.output_feature_names:
            raise RuntimeError("Preprocessor has not been fitted.")
        return {
            "numeric_feature_count": len(NUMERIC_FEATURE_NAMES),
            "categorical_feature_count": len(CATEGORICAL_FEATURE_NAMES),
            "encoded_feature_count": len(self.output_feature_names),
            "numeric_imputation": "training-partition median",
            "numeric_scaling": "training-partition population standard deviation",
            "categorical_encoding": "sorted one-hot with explicit unknown category",
        }


def _validate_rows(rows: Sequence[Mapping[str, object]]) -> None:
    expected = set(TRAINING_FEATURE_NAMES)
    for row in rows:
        if set(row) != expected:
            raise ValueError("Preprocessing input violates the operational feature allow-list.")


def _numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _category(value: object) -> str:
    if value is None:
        return MISSING_CATEGORY
    if isinstance(value, bool):
        return "true" if value else "false"
    normalized = str(value).strip().upper()
    return normalized or MISSING_CATEGORY
