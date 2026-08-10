from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import (  # type: ignore[import-untyped]
    HistGradientBoostingClassifier,
    IsolationForest,
)
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.metrics import average_precision_score  # type: ignore[import-untyped]
from sklearn.utils.class_weight import compute_sample_weight  # type: ignore[import-untyped]

from fip_api.models import DatasetSplit
from fip_api.operational_ml.dataset import (
    OperationalTrainingBlocked,
    OperationalTrainingDataset,
    OperationalTrainingRow,
)
from fip_api.operational_ml.evaluation import (
    EvaluationMetrics,
    evaluate_scores,
    select_threshold_at_fpr,
)
from fip_api.operational_ml.preprocessing import OperationalPreprocessor


class SigmoidCalibrator:
    """Platt-style calibration fitted only on the chronological training tail."""

    def __init__(self) -> None:
        self.model: LogisticRegression | None = None

    def fit(
        self,
        probabilities: NDArray[np.float64],
        labels: NDArray[np.int64],
    ) -> SigmoidCalibrator:
        model = LogisticRegression(C=1_000_000.0, max_iter=1_000, random_state=0)
        model.fit(_probability_logits(probabilities), labels)
        self.model = model
        return self

    def predict(self, probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
        if self.model is None:
            raise RuntimeError("Calibrator has not been fitted.")
        calibrated = self.model.predict_proba(_probability_logits(probabilities))[:, 1]
        return np.asarray(calibrated, dtype=np.float64)


@dataclass(frozen=True)
class SupervisedModelArtifact:
    model_name: str
    feature_set_version: str
    training_dataset_checksum: str
    preprocessor: OperationalPreprocessor
    estimator: Any
    calibrator: SigmoidCalibrator
    threshold: float

    def predict_scores(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> NDArray[np.float64]:
        encoded = self.preprocessor.transform(rows)
        raw = _positive_probabilities(self.estimator, encoded)
        return self.calibrator.predict(raw)


@dataclass(frozen=True)
class AnomalyModelArtifact:
    feature_set_version: str
    training_dataset_checksum: str
    preprocessor: OperationalPreprocessor
    estimator: IsolationForest
    reference_scores: NDArray[np.float64]
    contamination: float
    threshold: float

    def predict_scores(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> NDArray[np.float64]:
        encoded = self.preprocessor.transform(rows)
        raw = np.asarray(-self.estimator.score_samples(encoded), dtype=np.float64)
        ranks = np.searchsorted(self.reference_scores, raw, side="right")
        return np.asarray(ranks / self.reference_scores.size, dtype=np.float64)


@dataclass(frozen=True)
class CandidateSummary:
    name: str
    validation_metrics: EvaluationMetrics


@dataclass(frozen=True)
class SupervisedTrainingResult:
    artifact: SupervisedModelArtifact
    candidates: tuple[CandidateSummary, ...]
    test_metrics: EvaluationMetrics
    feature_importance: tuple[dict[str, float | str], ...]
    preprocessing_evidence: dict[str, object]


@dataclass(frozen=True)
class AnomalyTrainingResult:
    artifact: AnomalyModelArtifact
    validation_metrics: EvaluationMetrics
    test_metrics: EvaluationMetrics
    feature_importance: tuple[dict[str, float | str], ...]
    preprocessing_evidence: dict[str, object]


@dataclass(frozen=True)
class TrainingPartitions:
    estimator_train: tuple[OperationalTrainingRow, ...]
    calibration: tuple[OperationalTrainingRow, ...]
    validation: tuple[OperationalTrainingRow, ...]
    test: tuple[OperationalTrainingRow, ...]

    def evidence(self) -> dict[str, dict[str, int | str]]:
        return {
            name: _partition_evidence(rows)
            for name, rows in (
                ("estimator_train", self.estimator_train),
                ("calibration", self.calibration),
                ("validation", self.validation),
                ("test", self.test),
            )
        }


def build_training_partitions(dataset: OperationalTrainingDataset) -> TrainingPartitions:
    train = dataset.rows_for(DatasetSplit.TRAIN)
    calibration_count = max(20, int(np.ceil(len(train) * 0.2)))
    if calibration_count >= len(train):
        raise OperationalTrainingBlocked(
            "The training partition is too small for a separate calibration tail."
        )
    partitions = TrainingPartitions(
        estimator_train=train[:-calibration_count],
        calibration=train[-calibration_count:],
        validation=dataset.rows_for(DatasetSplit.VALIDATION),
        test=dataset.rows_for(DatasetSplit.TEST),
    )
    for name, rows in (
        ("estimator training", partitions.estimator_train),
        ("calibration", partitions.calibration),
        ("validation", partitions.validation),
        ("test", partitions.test),
    ):
        if {row.label for row in rows} != {0, 1}:
            raise OperationalTrainingBlocked(
                f"The chronological {name} partition must contain both binary classes."
            )
    return partitions


def train_supervised_model(
    dataset: OperationalTrainingDataset,
    partitions: TrainingPartitions,
    *,
    seed: int,
    maximum_false_positive_rate: float,
) -> SupervisedTrainingResult:
    train_rows = _features(partitions.estimator_train)
    calibration_rows = _features(partitions.calibration)
    validation_rows = _features(partitions.validation)
    test_rows = _features(partitions.test)
    preprocessor = OperationalPreprocessor().fit(train_rows)
    train_features = preprocessor.transform(train_rows)
    calibration_features = preprocessor.transform(calibration_rows)
    validation_features = preprocessor.transform(validation_rows)
    train_labels = _labels(partitions.estimator_train)
    calibration_labels = _labels(partitions.calibration)
    validation_labels = _labels(partitions.validation)
    sample_weights = np.asarray(
        compute_sample_weight(class_weight="balanced", y=train_labels),
        dtype=np.float64,
    )

    candidates: list[tuple[str, Any, SigmoidCalibrator, float, EvaluationMetrics]] = []
    estimator_specs: tuple[tuple[str, Any, dict[str, object]], ...] = (
        (
            "logistic-regression",
            LogisticRegression(max_iter=1_000, random_state=seed),
            {"sample_weight": sample_weights},
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
    )
    for name, estimator, fit_parameters in estimator_specs:
        estimator.fit(train_features, train_labels, **fit_parameters)
        calibrator = SigmoidCalibrator().fit(
            _positive_probabilities(estimator, calibration_features),
            calibration_labels,
        )
        validation_scores = calibrator.predict(
            _positive_probabilities(estimator, validation_features)
        )
        threshold = select_threshold_at_fpr(
            validation_labels,
            validation_scores,
            maximum_false_positive_rate,
        )
        candidates.append(
            (
                name,
                estimator,
                calibrator,
                threshold,
                evaluate_scores(validation_labels, validation_scores, threshold),
            )
        )

    selected = max(
        candidates,
        key=lambda item: (item[4].average_precision, -item[4].brier_score),
    )
    artifact = SupervisedModelArtifact(
        model_name=selected[0],
        feature_set_version=dataset.feature_set_version,
        training_dataset_checksum=dataset.dataset_checksum,
        preprocessor=preprocessor,
        estimator=selected[1],
        calibrator=selected[2],
        threshold=selected[3],
    )
    test_labels = _labels(partitions.test)
    test_metrics = evaluate_scores(
        test_labels,
        artifact.predict_scores(test_rows),
        artifact.threshold,
    )
    importance = semantic_permutation_importance(
        artifact.predict_scores,
        validation_rows,
        validation_labels,
        dataset.feature_names,
        seed=seed,
    )
    return SupervisedTrainingResult(
        artifact=artifact,
        candidates=tuple(
            CandidateSummary(name=name, validation_metrics=metrics)
            for name, _, _, _, metrics in candidates
        ),
        test_metrics=test_metrics,
        feature_importance=importance,
        preprocessing_evidence=preprocessor.evidence(),
    )


def train_anomaly_model(
    dataset: OperationalTrainingDataset,
    partitions: TrainingPartitions,
    *,
    seed: int,
    maximum_false_positive_rate: float,
) -> AnomalyTrainingResult:
    training_partition = dataset.rows_for(DatasetSplit.TRAIN)
    train_rows = _features(training_partition)
    validation_rows = _features(partitions.validation)
    test_rows = _features(partitions.test)
    preprocessor = OperationalPreprocessor().fit(train_rows)
    train_features = preprocessor.transform(train_rows)
    contamination = float(np.clip(np.mean(_labels(training_partition)), 0.01, 0.2))
    estimator = IsolationForest(
        n_estimators=160,
        contamination=contamination,
        random_state=seed,
        n_jobs=1,
    )
    estimator.fit(train_features)
    reference_scores = np.sort(
        np.asarray(-estimator.score_samples(train_features), dtype=np.float64)
    )
    artifact = AnomalyModelArtifact(
        feature_set_version=dataset.feature_set_version,
        training_dataset_checksum=dataset.dataset_checksum,
        preprocessor=preprocessor,
        estimator=estimator,
        reference_scores=reference_scores,
        contamination=contamination,
        threshold=0.5,
    )
    validation_labels = _labels(partitions.validation)
    validation_scores = artifact.predict_scores(validation_rows)
    threshold = select_threshold_at_fpr(
        validation_labels,
        validation_scores,
        maximum_false_positive_rate,
    )
    artifact = AnomalyModelArtifact(
        feature_set_version=artifact.feature_set_version,
        training_dataset_checksum=artifact.training_dataset_checksum,
        preprocessor=artifact.preprocessor,
        estimator=artifact.estimator,
        reference_scores=artifact.reference_scores,
        contamination=artifact.contamination,
        threshold=threshold,
    )
    validation_metrics = evaluate_scores(validation_labels, validation_scores, threshold)
    test_labels = _labels(partitions.test)
    test_metrics = evaluate_scores(test_labels, artifact.predict_scores(test_rows), threshold)
    importance = semantic_permutation_importance(
        artifact.predict_scores,
        validation_rows,
        validation_labels,
        dataset.feature_names,
        seed=seed,
    )
    return AnomalyTrainingResult(
        artifact=artifact,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        feature_importance=importance,
        preprocessing_evidence=preprocessor.evidence(),
    )


def semantic_permutation_importance(
    score_function: Callable[[Sequence[Mapping[str, object]]], NDArray[np.float64]],
    rows: Sequence[Mapping[str, object]],
    labels: NDArray[np.int64],
    feature_names: Sequence[str],
    *,
    seed: int,
    repeats: int = 3,
) -> tuple[dict[str, float | str], ...]:
    baseline = float(average_precision_score(labels, score_function(rows)))
    random = np.random.default_rng(seed)
    results: list[dict[str, float | str]] = []
    for feature_name in feature_names:
        decreases: list[float] = []
        values = [row[feature_name] for row in rows]
        for _ in range(repeats):
            shuffled = random.permutation(len(rows))
            permuted = [dict(row) for row in rows]
            for index, source_index in enumerate(shuffled):
                permuted[index][feature_name] = values[int(source_index)]
            score = float(average_precision_score(labels, score_function(permuted)))
            decreases.append(baseline - score)
        results.append(
            {
                "feature": feature_name,
                "mean_pr_auc_decrease": float(np.mean(decreases)),
                "standard_deviation": float(np.std(decreases)),
            }
        )
    return tuple(
        sorted(
            results,
            key=lambda row: float(row["mean_pr_auc_decrease"]),
            reverse=True,
        )
    )


def _features(rows: Sequence[OperationalTrainingRow]) -> tuple[dict[str, object], ...]:
    return tuple(row.feature_values for row in rows)


def _labels(rows: Sequence[OperationalTrainingRow]) -> NDArray[np.int64]:
    return np.asarray([row.label for row in rows], dtype=np.int64)


def _partition_evidence(rows: Sequence[OperationalTrainingRow]) -> dict[str, int | str]:
    return {
        "row_count": len(rows),
        "positive_count": sum(row.label for row in rows),
        "first_occurred_at": rows[0].occurred_at.isoformat(),
        "last_occurred_at": rows[-1].occurred_at.isoformat(),
    }


def _positive_probabilities(estimator: Any, features: NDArray[np.float64]) -> NDArray[np.float64]:
    probabilities = np.asarray(estimator.predict_proba(features), dtype=np.float64)
    if probabilities.ndim != 2 or probabilities.shape[1] != 2:
        raise ValueError("The supervised estimator did not return binary probabilities.")
    return np.asarray(probabilities[:, 1], dtype=np.float64)


def _probability_logits(probabilities: NDArray[np.float64]) -> NDArray[np.float64]:
    clipped = np.clip(probabilities, 1e-8, 1.0 - 1e-8)
    logits = np.log(clipped / (1.0 - clipped))
    return np.asarray(logits.reshape(-1, 1), dtype=np.float64)
