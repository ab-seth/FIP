from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray
from sklearn.metrics import (  # type: ignore[import-untyped]
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
)


@dataclass(frozen=True)
class EvaluationMetrics:
    row_count: int
    positive_count: int
    prevalence: float
    average_precision: float
    roc_auc: float
    brier_score: float
    expected_calibration_error: float
    threshold: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    alert_rate: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def select_threshold_at_fpr(
    labels: NDArray[np.int64],
    probabilities: NDArray[np.float64],
    maximum_false_positive_rate: float,
) -> float:
    if not 0 < maximum_false_positive_rate < 1:
        raise ValueError("maximum_false_positive_rate must be between 0 and 1")

    false_positive_rates, true_positive_rates, thresholds = roc_curve(
        labels,
        probabilities,
        drop_intermediate=False,
    )
    eligible = np.flatnonzero(
        (false_positive_rates <= maximum_false_positive_rate) & np.isfinite(thresholds)
    )
    if eligible.size == 0:
        return float(np.nextafter(np.max(probabilities), np.inf))

    eligible_true_positive_rates = true_positive_rates[eligible]
    best_recall = float(np.max(eligible_true_positive_rates))
    best = eligible[np.flatnonzero(eligible_true_positive_rates == best_recall)]
    return float(np.max(thresholds[best]))


def evaluate_probabilities(
    labels: NDArray[np.int64],
    probabilities: NDArray[np.float64],
    threshold: float,
) -> EvaluationMetrics:
    predictions = (probabilities >= threshold).astype(np.int64)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        predictions,
        average="binary",
        zero_division=0,
    )
    true_negatives, false_positives, false_negatives, true_positives = confusion_matrix(
        labels,
        predictions,
        labels=[0, 1],
    ).ravel()
    negative_count = true_negatives + false_positives

    return EvaluationMetrics(
        row_count=int(labels.size),
        positive_count=int(np.sum(labels)),
        prevalence=float(np.mean(labels)),
        average_precision=float(average_precision_score(labels, probabilities)),
        roc_auc=float(roc_auc_score(labels, probabilities)),
        brier_score=float(brier_score_loss(labels, probabilities)),
        expected_calibration_error=_expected_calibration_error(labels, probabilities),
        threshold=float(threshold),
        precision=float(precision),
        recall=float(recall),
        f1=float(f1),
        false_positive_rate=float(false_positives / negative_count),
        alert_rate=float(np.mean(predictions)),
        true_positives=int(true_positives),
        false_positives=int(false_positives),
        true_negatives=int(true_negatives),
        false_negatives=int(false_negatives),
    )


def _expected_calibration_error(
    labels: NDArray[np.int64],
    probabilities: NDArray[np.float64],
    bins: int = 10,
) -> float:
    bin_ids = np.minimum((probabilities * bins).astype(np.int64), bins - 1)
    error = 0.0
    for bin_id in range(bins):
        mask = bin_ids == bin_id
        if not np.any(mask):
            continue
        confidence = float(np.mean(probabilities[mask]))
        observed_rate = float(np.mean(labels[mask]))
        error += float(np.mean(mask)) * abs(confidence - observed_rate)
    return error
