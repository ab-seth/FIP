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
    scores: NDArray[np.float64],
    maximum_false_positive_rate: float,
) -> float:
    if not 0 < maximum_false_positive_rate < 1:
        raise ValueError("maximum_false_positive_rate must be between 0 and 1")
    _validate_binary_evaluation(labels, scores)
    false_positive_rates, true_positive_rates, thresholds = roc_curve(
        labels,
        scores,
        drop_intermediate=False,
    )
    eligible = np.flatnonzero(
        (false_positive_rates <= maximum_false_positive_rate) & np.isfinite(thresholds)
    )
    if eligible.size == 0:
        return float(np.nextafter(np.max(scores), np.inf))
    eligible_recall = true_positive_rates[eligible]
    best_recall = float(np.max(eligible_recall))
    best = eligible[np.flatnonzero(eligible_recall == best_recall)]
    return float(np.max(thresholds[best]))


def evaluate_scores(
    labels: NDArray[np.int64],
    scores: NDArray[np.float64],
    threshold: float,
) -> EvaluationMetrics:
    _validate_binary_evaluation(labels, scores)
    predictions = (scores >= threshold).astype(np.int64)
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
        average_precision=float(average_precision_score(labels, scores)),
        roc_auc=float(roc_auc_score(labels, scores)),
        brier_score=float(brier_score_loss(labels, scores)),
        expected_calibration_error=_expected_calibration_error(labels, scores),
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


def _validate_binary_evaluation(
    labels: NDArray[np.int64],
    scores: NDArray[np.float64],
) -> None:
    if labels.ndim != 1 or scores.ndim != 1 or labels.shape != scores.shape:
        raise ValueError("Labels and scores must be equal-length vectors.")
    if set(np.unique(labels).tolist()) != {0, 1}:
        raise ValueError("Evaluation requires both binary classes.")
    if not np.all(np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("Evaluation scores must be finite values between zero and one.")


def _expected_calibration_error(
    labels: NDArray[np.int64],
    scores: NDArray[np.float64],
    bins: int = 10,
) -> float:
    bin_ids = np.minimum((scores * bins).astype(np.int64), bins - 1)
    error = 0.0
    for bin_id in range(bins):
        mask = bin_ids == bin_id
        if not np.any(mask):
            continue
        error += float(np.mean(mask)) * abs(
            float(np.mean(scores[mask])) - float(np.mean(labels[mask]))
        )
    return error
