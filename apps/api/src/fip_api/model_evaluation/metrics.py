from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

METRIC_QUANTUM = Decimal("0.0000000001")
NUMERIC_FEATURES = (
    "amount",
    "occurred_hour_utc",
    "occurred_day_of_week_utc",
    "prior_transaction_count_1h",
    "prior_transaction_count_24h",
    "prior_transaction_count_30d",
    "prior_same_currency_count_30d",
    "prior_same_currency_median_amount_30d",
    "amount_to_median_ratio_30d",
)
CATEGORICAL_FEATURES = (
    "currency",
    "is_weekend_utc",
    "is_off_hours_utc",
    "is_cross_border",
    "channel",
    "merchant_category_code",
    "source_country",
    "destination_country",
    "merchant_seen_before_30d",
)


@dataclass(frozen=True)
class EvaluationObservation:
    score: Decimal
    threshold_exceeded: bool
    runtime_milliseconds: int
    rule_score: int
    rule_risk_level: str
    feature_values: dict[str, object]


def build_evaluation_metrics(
    baseline: list[EvaluationObservation],
    evaluation: list[EvaluationObservation],
    *,
    ruleset_version: str,
    risk_band_version: str,
) -> dict[str, object]:
    baseline_summary = _window_summary(
        baseline,
        ruleset_version=ruleset_version,
        risk_band_version=risk_band_version,
    )
    evaluation_summary = _window_summary(
        evaluation,
        ruleset_version=ruleset_version,
        risk_band_version=risk_band_version,
    )
    baseline_scores = [row.score for row in baseline]
    evaluation_scores = [row.score for row in evaluation]
    score_psi = _population_stability_index(
        _fixed_bin_counts(baseline_scores),
        _fixed_bin_counts(evaluation_scores),
    )
    baseline_mean = _mean(baseline_scores)
    evaluation_mean = _mean(evaluation_scores)
    baseline_threshold_rate = _rate(sum(row.threshold_exceeded for row in baseline), len(baseline))
    evaluation_threshold_rate = _rate(
        sum(row.threshold_exceeded for row in evaluation), len(evaluation)
    )

    return {
        "baseline": baseline_summary,
        "evaluation": evaluation_summary,
        "score_drift": {
            "population_stability_index": _decimal_text(score_psi),
            "mean_score_delta": _decimal_text(evaluation_mean - baseline_mean),
            "threshold_exceedance_rate_delta": _decimal_text(
                evaluation_threshold_rate - baseline_threshold_rate
            ),
            "status": _drift_status(score_psi, watch=Decimal("0.1"), material=Decimal("0.25")),
        },
        "feature_drift": _feature_drift(baseline, evaluation),
        "interpretation": {
            "comparison_only": True,
            "deterministic_rules_are_not_ground_truth_labels": True,
            "monitoring_result_changes_model_lifecycle": False,
            "monitoring_result_triggers_automatic_action": False,
        },
    }


def _window_summary(
    observations: list[EvaluationObservation],
    *,
    ruleset_version: str,
    risk_band_version: str,
) -> dict[str, object]:
    scores = [row.score for row in observations]
    runtimes = [Decimal(row.runtime_milliseconds) for row in observations]
    model_positive = [row.threshold_exceeded for row in observations]
    rule_high = [row.rule_risk_level == "high" for row in observations]
    both = sum(model and rule for model, rule in zip(model_positive, rule_high, strict=True))
    model_only = sum(
        model and not rule for model, rule in zip(model_positive, rule_high, strict=True)
    )
    rule_only = sum(
        not model and rule for model, rule in zip(model_positive, rule_high, strict=True)
    )
    neither = len(observations) - both - model_only - rule_only
    disagreements = model_only + rule_only

    return {
        "prediction_count": len(observations),
        "score_distribution": _distribution(scores),
        "model_threshold_exceedance_rate": _decimal_text(
            _rate(sum(model_positive), len(observations))
        ),
        "runtime_milliseconds": {
            "mean": _decimal_text(_mean(runtimes)),
            "p95": _decimal_text(_percentile(runtimes, Decimal("0.95"))),
            "maximum": _decimal_text(max(runtimes)),
        },
        "rules_comparison": {
            "ruleset_version": ruleset_version,
            "risk_band_version": risk_band_version,
            "rule_high_rate": _decimal_text(_rate(sum(rule_high), len(observations))),
            "agreement_rate": _decimal_text(
                _rate(len(observations) - disagreements, len(observations))
            ),
            "disagreement_rate": _decimal_text(_rate(disagreements, len(observations))),
            "both_model_and_rules_high": both,
            "model_only_high": model_only,
            "rules_only_high": rule_only,
            "neither_high": neither,
        },
    }


def _distribution(values: list[Decimal]) -> dict[str, str]:
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    return {
        "minimum": _decimal_text(min(values)),
        "p25": _decimal_text(_percentile(values, Decimal("0.25"))),
        "median": _decimal_text(_percentile(values, Decimal("0.5"))),
        "p75": _decimal_text(_percentile(values, Decimal("0.75"))),
        "p95": _decimal_text(_percentile(values, Decimal("0.95"))),
        "maximum": _decimal_text(max(values)),
        "mean": _decimal_text(mean),
        "population_standard_deviation": _decimal_text(variance.sqrt()),
    }


def _feature_drift(
    baseline: list[EvaluationObservation],
    evaluation: list[EvaluationObservation],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for feature in NUMERIC_FEATURES:
        baseline_values, baseline_missing = _numeric_feature_values(baseline, feature)
        evaluation_values, evaluation_missing = _numeric_feature_values(evaluation, feature)
        if baseline_values and evaluation_values:
            edges = sorted(
                {
                    _percentile(baseline_values, percentile)
                    for percentile in (
                        Decimal("0.2"),
                        Decimal("0.4"),
                        Decimal("0.6"),
                        Decimal("0.8"),
                    )
                }
            )
            value = _population_stability_index(
                _variable_bin_counts(baseline_values, edges),
                _variable_bin_counts(evaluation_values, edges),
            )
            status = _drift_status(value, watch=Decimal("0.1"), material=Decimal("0.25"))
            value_text: str | None = _decimal_text(value)
        else:
            value_text = None
            status = "insufficient_data"
        rows.append(
            _feature_row(
                feature=feature,
                kind="numeric",
                metric="population_stability_index",
                value=value_text,
                status=status,
                baseline_missing=baseline_missing,
                evaluation_missing=evaluation_missing,
                baseline_count=len(baseline),
                evaluation_count=len(evaluation),
            )
        )

    for feature in CATEGORICAL_FEATURES:
        baseline_categories, baseline_missing = _categorical_feature_values(baseline, feature)
        evaluation_categories, evaluation_missing = _categorical_feature_values(evaluation, feature)
        if baseline_categories and evaluation_categories:
            value = _total_variation_distance(baseline_categories, evaluation_categories)
            status = _drift_status(value, watch=Decimal("0.1"), material=Decimal("0.2"))
            value_text = _decimal_text(value)
        else:
            value_text = None
            status = "insufficient_data"
        rows.append(
            _feature_row(
                feature=feature,
                kind="categorical",
                metric="total_variation_distance",
                value=value_text,
                status=status,
                baseline_missing=baseline_missing,
                evaluation_missing=evaluation_missing,
                baseline_count=len(baseline),
                evaluation_count=len(evaluation),
            )
        )
    return rows


def _feature_row(
    *,
    feature: str,
    kind: str,
    metric: str,
    value: str | None,
    status: str,
    baseline_missing: int,
    evaluation_missing: int,
    baseline_count: int,
    evaluation_count: int,
) -> dict[str, object]:
    baseline_missing_rate = _rate(baseline_missing, baseline_count)
    evaluation_missing_rate = _rate(evaluation_missing, evaluation_count)
    return {
        "feature": feature,
        "kind": kind,
        "metric": metric,
        "value": value,
        "status": status,
        "baseline_missing_rate": _decimal_text(baseline_missing_rate),
        "evaluation_missing_rate": _decimal_text(evaluation_missing_rate),
        "missing_rate_delta": _decimal_text(evaluation_missing_rate - baseline_missing_rate),
    }


def _numeric_feature_values(
    observations: list[EvaluationObservation],
    feature: str,
) -> tuple[list[Decimal], int]:
    values: list[Decimal] = []
    missing = 0
    for observation in observations:
        raw = observation.feature_values.get(feature)
        numeric = _optional_decimal(raw)
        if numeric is None:
            missing += 1
        else:
            values.append(numeric)
    return values, missing


def _categorical_feature_values(
    observations: list[EvaluationObservation],
    feature: str,
) -> tuple[list[str], int]:
    values: list[str] = []
    missing = 0
    for observation in observations:
        raw = observation.feature_values.get(feature)
        if raw is None:
            missing += 1
        elif isinstance(raw, bool):
            values.append("true" if raw else "false")
        else:
            values.append(str(raw))
    return values, missing


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return numeric if numeric.is_finite() else None


def _fixed_bin_counts(values: list[Decimal]) -> list[int]:
    edges = [Decimal(index) / Decimal(10) for index in range(1, 10)]
    return _variable_bin_counts(values, edges)


def _variable_bin_counts(values: list[Decimal], edges: list[Decimal]) -> list[int]:
    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    return counts


def _population_stability_index(baseline: list[int], evaluation: list[int]) -> Decimal:
    epsilon = 1e-6
    baseline_total = float(sum(baseline)) + epsilon * len(baseline)
    evaluation_total = float(sum(evaluation)) + epsilon * len(evaluation)
    value = 0.0
    for baseline_count, evaluation_count in zip(baseline, evaluation, strict=True):
        baseline_rate = (baseline_count + epsilon) / baseline_total
        evaluation_rate = (evaluation_count + epsilon) / evaluation_total
        value += (evaluation_rate - baseline_rate) * math.log(evaluation_rate / baseline_rate)
    return Decimal(str(value)).quantize(METRIC_QUANTUM)


def _total_variation_distance(baseline: list[str], evaluation: list[str]) -> Decimal:
    categories = sorted(set(baseline) | set(evaluation))
    baseline_total = Decimal(len(baseline))
    evaluation_total = Decimal(len(evaluation))
    difference = sum(
        abs(
            Decimal(baseline.count(category)) / baseline_total
            - Decimal(evaluation.count(category)) / evaluation_total
        )
        for category in categories
    )
    return (difference / Decimal(2)).quantize(METRIC_QUANTUM)


def _percentile(values: list[Decimal], percentile: Decimal) -> Decimal:
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _rate(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator)


def _drift_status(value: Decimal, *, watch: Decimal, material: Decimal) -> str:
    if value >= material:
        return "material"
    if value >= watch:
        return "watch"
    return "stable"


def _decimal_text(value: Decimal) -> str:
    quantized = value.quantize(METRIC_QUANTUM)
    return format(quantized.normalize(), "f")
