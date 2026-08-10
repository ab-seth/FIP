from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.inspection import permutation_importance  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]
from sklearn.utils.class_weight import compute_sample_weight  # type: ignore[import-untyped]

from fip_api.research_ml.evaluation import (
    EvaluationMetrics,
    evaluate_probabilities,
    select_threshold_at_fpr,
)


class SigmoidCalibrator:
    """Platt-style calibration fit only on the chronological calibration partition."""

    def __init__(self) -> None:
        self._model: LogisticRegression | None = None

    def fit(
        self,
        probabilities: NDArray[np.float64],
        labels: NDArray[np.int64],
    ) -> SigmoidCalibrator:
        logits = _probability_logits(probabilities)
        model = LogisticRegression(C=1_000_000.0, max_iter=1_000, random_state=0)
        model.fit(logits, labels)
        self._model = model
        return self

    def predict(self, probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
        if self._model is None:
            raise RuntimeError("Calibrator has not been fitted")
        calibrated = self._model.predict_proba(_probability_logits(probabilities))[:, 1]
        return np.asarray(calibrated, dtype=np.float64)


@dataclass(frozen=True)
class CandidateResult:
    name: str
    estimator: Any
    calibrator: SigmoidCalibrator
    threshold: float
    validation_metrics: EvaluationMetrics


def train_candidates(
    train_features: NDArray[np.float64],
    train_labels: NDArray[np.int64],
    calibration_features: NDArray[np.float64],
    calibration_labels: NDArray[np.int64],
    validation_features: NDArray[np.float64],
    validation_labels: NDArray[np.int64],
    *,
    seed: int,
    maximum_false_positive_rate: float,
) -> list[CandidateResult]:
    sample_weights = np.asarray(
        compute_sample_weight(class_weight="balanced", y=train_labels),
        dtype=np.float64,
    )
    candidates: list[tuple[str, Any, dict[str, object]]] = [
        (
            "logistic-regression",
            make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=1_000, random_state=seed),
            ),
            {"logisticregression__sample_weight": sample_weights},
        ),
        (
            "hist-gradient-boosting",
            HistGradientBoostingClassifier(
                learning_rate=0.08,
                max_iter=160,
                max_leaf_nodes=31,
                min_samples_leaf=20,
                l2_regularization=1.0,
                early_stopping=False,
                random_state=seed,
            ),
            {"sample_weight": sample_weights},
        ),
    ]

    results: list[CandidateResult] = []
    for name, estimator, fit_parameters in candidates:
        estimator.fit(train_features, train_labels, **fit_parameters)
        calibration_raw = _positive_probabilities(estimator, calibration_features)
        calibrator = SigmoidCalibrator().fit(calibration_raw, calibration_labels)
        validation_raw = _positive_probabilities(estimator, validation_features)
        validation_probabilities = calibrator.predict(validation_raw)
        threshold = select_threshold_at_fpr(
            validation_labels,
            validation_probabilities,
            maximum_false_positive_rate,
        )
        results.append(
            CandidateResult(
                name=name,
                estimator=estimator,
                calibrator=calibrator,
                threshold=threshold,
                validation_metrics=evaluate_probabilities(
                    validation_labels,
                    validation_probabilities,
                    threshold,
                ),
            )
        )
    return results


def select_candidate(candidates: list[CandidateResult]) -> CandidateResult:
    if not candidates:
        raise ValueError("At least one model candidate is required")
    return max(
        candidates,
        key=lambda candidate: (
            candidate.validation_metrics.average_precision,
            -candidate.validation_metrics.brier_score,
        ),
    )


def predict_candidate(
    candidate: CandidateResult,
    features: NDArray[np.float64],
) -> NDArray[np.float64]:
    return candidate.calibrator.predict(_positive_probabilities(candidate.estimator, features))


def explain_candidate(
    candidate: CandidateResult,
    features: NDArray[np.float64],
    labels: NDArray[np.int64],
    feature_names: tuple[str, ...],
    *,
    seed: int,
) -> list[dict[str, float | str]]:
    """Calculate validation-only global permutation importance by PR-AUC loss."""

    importance = permutation_importance(
        candidate.estimator,
        features,
        labels,
        scoring="average_precision",
        n_repeats=3,
        random_state=seed,
        n_jobs=1,
        max_samples=1.0,
    )
    rows: list[dict[str, float | str]] = [
        {
            "feature": feature_name,
            "mean_pr_auc_decrease": float(importance.importances_mean[index]),
            "standard_deviation": float(importance.importances_std[index]),
        }
        for index, feature_name in enumerate(feature_names)
    ]
    return sorted(
        rows,
        key=lambda row: float(row["mean_pr_auc_decrease"]),
        reverse=True,
    )


def _positive_probabilities(estimator: Any, features: NDArray[np.float64]) -> NDArray[np.float64]:
    probabilities = np.asarray(estimator.predict_proba(features), dtype=np.float64)
    if probabilities.ndim != 2 or probabilities.shape[1] != 2:
        raise ValueError("Research estimator did not return binary probabilities")
    return np.asarray(probabilities[:, 1], dtype=np.float64)


def _probability_logits(probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
    clipped = np.clip(probabilities, 1e-8, 1.0 - 1e-8)
    logits = np.log(clipped / (1.0 - clipped))
    return np.asarray(logits.reshape(-1, 1), dtype=np.float64)
