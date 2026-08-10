from __future__ import annotations

import json
import os
import platform
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from fip_api.research_ml import PIPELINE_VERSION
from fip_api.research_ml.artifact import sha256_file, write_model_artifact
from fip_api.research_ml.dataset import ResearchDataset, load_ulb_credit_card
from fip_api.research_ml.evaluation import evaluate_probabilities
from fip_api.research_ml.splitting import (
    SplitFractions,
    TemporalPartitions,
    build_temporal_partitions,
)
from fip_api.research_ml.training import (
    CandidateResult,
    explain_candidate,
    predict_candidate,
    select_candidate,
    train_candidates,
)

ULB_SOURCE_PAGE = "https://www.openml.org/d/1597"
ULB_DOWNLOAD_URL = "https://openml.org/data/v1/download/1673544/creditcard.arff"
CANDIDATE_DISPLAY_ORDER = ("logistic-regression", "hist-gradient-boosting")


@dataclass(frozen=True)
class ExperimentConfig:
    input_path: Path
    output_directory: Path
    seed: int = 42
    maximum_false_positive_rate: float = 0.01
    split_fractions: SplitFractions = SplitFractions()

    def validate(self) -> None:
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if not 0 < self.maximum_false_positive_rate < 1:
            raise ValueError("maximum_false_positive_rate must be between 0 and 1")
        self.split_fractions.validate()


def run_experiment(config: ExperimentConfig) -> dict[str, Any]:
    """Train and evaluate research models without touching operational scoring."""

    config.validate()
    if config.output_directory.exists():
        raise FileExistsError(config.output_directory)

    dataset = load_ulb_credit_card(config.input_path)
    source_checksum = sha256_file(config.input_path)
    partitions = build_temporal_partitions(dataset, config.split_fractions)

    candidates = train_candidates(
        dataset.features[partitions.train],
        dataset.labels[partitions.train],
        dataset.features[partitions.calibration],
        dataset.labels[partitions.calibration],
        dataset.features[partitions.validation],
        dataset.labels[partitions.validation],
        seed=config.seed,
        maximum_false_positive_rate=config.maximum_false_positive_rate,
    )
    selected = select_candidate(candidates)
    test_probabilities = predict_candidate(selected, dataset.features[partitions.test])
    test_metrics = evaluate_probabilities(
        dataset.labels[partitions.test],
        test_probabilities,
        selected.threshold,
    )
    feature_importance = explain_candidate(
        selected,
        dataset.features[partitions.validation],
        dataset.labels[partitions.validation],
        dataset.feature_names,
        seed=config.seed,
    )

    created_at = datetime.now(UTC).isoformat()
    result: dict[str, Any] = {
        "pipeline_version": PIPELINE_VERSION,
        "created_at": created_at,
        "research_only": True,
        "dataset": {
            "dataset_id": dataset.dataset_id,
            "source_page": ULB_SOURCE_PAGE,
            "source_file_sha256": source_checksum,
            "row_count": dataset.row_count,
            "positive_count": dataset.positive_count,
            "feature_names": list(dataset.feature_names),
            "operational_feature_compatible": False,
        },
        "configuration": {
            "seed": config.seed,
            "maximum_false_positive_rate": config.maximum_false_positive_rate,
            "split_fractions": asdict(config.split_fractions),
        },
        "partitions": partition_summary(dataset, partitions),
        "candidates": {
            candidate.name: {"validation": candidate.validation_metrics.to_dict()}
            for candidate in candidates
        },
        "selected_model": selected.name,
        "explainability": {
            "method": "validation permutation importance by average-precision decrease",
            "repeats": 3,
            "validation_sample_fraction": 1.0,
            "features": feature_importance,
            "semantic_limit": "V1 through V28 are undisclosed PCA components",
        },
        "test": test_metrics.to_dict(),
        "runtime": {
            "python": platform.python_version(),
            "numpy": version("numpy"),
            "scikit_learn": version("scikit-learn"),
        },
    }
    _write_run(config.output_directory, result, selected)
    return result


def _write_run(
    output_directory: Path,
    result: dict[str, Any],
    selected: CandidateResult,
) -> None:
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory = Path(
        tempfile.mkdtemp(prefix=f".{output_directory.name}-", dir=output_directory.parent)
    )
    try:
        metrics_path = temporary_directory / "metrics.json"
        metrics_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_path = temporary_directory / "model.joblib"
        write_model_artifact(artifact_path, selected)
        model_checksum = sha256_file(artifact_path)
        model_card = build_model_card(result, model_checksum)
        (temporary_directory / "model-card.md").write_text(model_card, encoding="utf-8")
        run_manifest = {
            "pipeline_version": PIPELINE_VERSION,
            "research_only": True,
            "files": {
                "metrics.json": sha256_file(metrics_path),
                "model.joblib": model_checksum,
                "model-card.md": sha256_file(temporary_directory / "model-card.md"),
            },
        }
        (temporary_directory / "run-manifest.json").write_text(
            json.dumps(run_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_directory, output_directory)
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise


def partition_summary(
    dataset: ResearchDataset,
    partitions: TemporalPartitions,
) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for name, indices in partitions.named():
        summary[name] = {
            "row_count": int(indices.size),
            "positive_count": int(np.sum(dataset.labels[indices])),
            "minimum_event_time": float(np.min(dataset.event_time[indices])),
            "maximum_event_time": float(np.max(dataset.event_time[indices])),
        }
    return summary


def build_model_card(result: dict[str, Any], model_checksum: str) -> str:
    dataset = result["dataset"]
    configuration = result["configuration"]
    test = result["test"]
    candidates = result["candidates"]
    candidate_names = [name for name in CANDIDATE_DISPLAY_ORDER if name in candidates]
    candidate_names.extend(sorted(set(candidates).difference(candidate_names)))
    candidate_entries = [(name, candidates[name]) for name in candidate_names]
    candidate_rows = "\n".join(
        (
            f"| {name} | {values['validation']['average_precision']:.6f} | "
            f"{values['validation']['roc_auc']:.6f} | "
            f"{values['validation']['brier_score']:.6f} |"
        )
        for name, values in candidate_entries
    )
    importance_rows = "\n".join(
        (
            f"| {row['feature']} | {row['mean_pr_auc_decrease']:.6f} | "
            f"{row['standard_deviation']:.6f} |"
        )
        for row in result["explainability"]["features"][:10]
    )

    return f"""# FIP research model card

## Status and intended use

This artifact is a **research-only methodology benchmark**. It must not participate in FIP's
operational scoring, transaction decisions, case prioritization, or claims of production efficacy.
It compares reproducible fraud-classification methods on a public real-transaction dataset.

## Dataset

- Dataset: OpenML 1597 / ULB credit-card fraud, version 1
- Source: {dataset["source_page"]}
- Rows: {dataset["row_count"]:,}
- Fraud labels: {dataset["positive_count"]:,}
- Source SHA-256: `{dataset["source_file_sha256"]}`
- Operational feature compatibility: **No**. `V1` through `V28` are undisclosed PCA features and
  cannot be recreated from FIP's canonical transaction contract.

## Evaluation design

Rows are ordered by event time and divided into separate train, calibration, validation, and test
partitions. Equal timestamps never cross partition boundaries. Models learn only from the training
partition, probability calibration uses only the calibration partition, selection and thresholding
use only validation, and the test partition is evaluated once after selection.

- Random seed: {configuration["seed"]}
- Maximum validation false-positive rate: {configuration["maximum_false_positive_rate"]:.4f}
- Split fractions: {json.dumps(configuration["split_fractions"], sort_keys=True)}

| Candidate | Validation PR-AUC | Validation ROC-AUC | Validation Brier |
| --- | ---: | ---: | ---: |
{candidate_rows}

## Selected model and held-out result

- Selected candidate: **{result["selected_model"]}**
- Test PR-AUC: {test["average_precision"]:.6f}
- Test ROC-AUC: {test["roc_auc"]:.6f}
- Test Brier score: {test["brier_score"]:.6f}
- Test precision at selected threshold: {test["precision"]:.6f}
- Test recall at selected threshold: {test["recall"]:.6f}
- Test false-positive rate: {test["false_positive_rate"]:.6f}
- Test alert rate: {test["alert_rate"]:.6f}
- Model artifact SHA-256: `{model_checksum}`

## Global research explanation

Permutation importance was calculated on the full validation partition with three repeats, using
PR-AUC decrease. These names are useful for model diagnostics only; PCA features do not provide
human-readable operational reasons.

| Feature | Mean PR-AUC decrease | Standard deviation |
| --- | ---: | ---: |
{importance_rows}

## Limitations

- The data cover two days of European card transactions from 2013 and do not establish current
  U.S. institutional performance.
- The anonymized PCA features prevent operational feature parity and human-readable factor labels.
- Severe class imbalance makes accuracy an inappropriate headline metric; PR-AUC, recall, precision,
  calibration, and false-positive rate are reported instead.
- This run does not demonstrate loss reduction, cross-institution generalization, fairness, drift
  resilience, or production latency.
- Generated test fixtures validate software only and are never reported as model evidence.

## Promotion decision

**Not eligible for operational promotion.** Production scoring remains disabled until FIP has a
reviewed institution-owned label set or a compatible licensed partner dataset, validated canonical
features, governance approval, and shadow-mode evidence.
"""
