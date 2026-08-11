from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from fip_api.cases import build_case_summary_response, list_cases
from fip_api.core.checksums import canonical_json_checksum
from fip_api.db.base import Base
from fip_api.explainability import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_VERSION,
    verify_case_brief_integrity,
)
from fip_api.features import FEATURE_SET_VERSION
from fip_api.hybrid_scoring import HYBRID_POLICY_VERSION, verify_hybrid_assessment_integrity
from fip_api.model_evaluation import (
    SHADOW_EVALUATION_SCHEMA_VERSION,
    build_evaluation_response,
    list_all_shadow_evaluations,
    verify_evaluation_report_integrity,
)
from fip_api.model_registry import SHADOW_OUTPUT_SCHEMA_VERSION, verify_model_lineage
from fip_api.models import (
    CaseBrief,
    CaseEvent,
    CaseOutcome,
    HybridRiskAssessment,
    ModelLifecycleEvent,
    OperationalDatasetSnapshot,
    RegisteredModel,
    ScoringRuntimeObservation,
    ShadowModelEvaluationReport,
    ShadowModelPrediction,
    Transaction,
    TransactionRuleAssessment,
)
from fip_api.rules import RISK_BAND_VERSION, RULESET_VERSION
from fip_api.schemas.explanation import CaseBriefValidationResponse
from fip_api.schemas.system_evaluation import (
    EvaluationGateResponse,
    EvaluationVolumeResponse,
    ExplanationEvaluationResponse,
    IntegritySummaryResponse,
    LatencySummaryResponse,
    ModelEvidenceResponse,
    SystemEvaluationRecordResponse,
    VersionLineageResponse,
)
from fip_api.scoring import (
    SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION,
    verify_scoring_runtime_observation,
)
from fip_api.training_datasets import verify_dataset_integrity
from fip_api.training_datasets.service import (
    LABEL_CONTRACT_VERSION,
    SPLIT_CONTRACT_VERSION,
)

SYSTEM_EVALUATION_SCHEMA_VERSION = "system-evaluation-record-v1.0.0"
SCORING_LATENCY_TARGET_MILLISECONDS = 2_000
LLM_LATENCY_TARGET_MILLISECONDS = 10_000
BENCHMARK_VOLUME_TARGET = 10_000


def build_system_evaluation_record(db: Session) -> SystemEvaluationRecordResponse:
    cases = list_cases(db)
    case_summaries = [build_case_summary_response(db, case) for case in cases]
    briefs = list(db.scalars(select(CaseBrief).order_by(CaseBrief.created_at, CaseBrief.id)).all())
    models = list(
        db.scalars(
            select(RegisteredModel).order_by(
                RegisteredModel.created_at,
                RegisteredModel.id,
            )
        ).all()
    )
    hybrids = list(
        db.scalars(
            select(HybridRiskAssessment).order_by(
                HybridRiskAssessment.created_at,
                HybridRiskAssessment.id,
            )
        ).all()
    )
    datasets = list(
        db.scalars(
            select(OperationalDatasetSnapshot).order_by(
                OperationalDatasetSnapshot.created_at,
                OperationalDatasetSnapshot.id,
            )
        ).all()
    )
    reports = list_all_shadow_evaluations(db)
    scoring_observations = list(
        db.scalars(
            select(ScoringRuntimeObservation).order_by(
                ScoringRuntimeObservation.created_at,
                ScoringRuntimeObservation.id,
            )
        ).all()
    )

    case_integrity = [summary.integrity_verified for summary in case_summaries]
    model_integrity = [verify_model_lineage(db, model) for model in models]
    brief_integrity = [verify_case_brief_integrity(db, brief) for brief in briefs]
    hybrid_integrity = [verify_hybrid_assessment_integrity(db, hybrid) for hybrid in hybrids]
    dataset_integrity = [verify_dataset_integrity(db, dataset) for dataset in datasets]
    report_integrity = [verify_evaluation_report_integrity(db, report) for report in reports]
    scoring_integrity = [
        verify_scoring_runtime_observation(db, observation) for observation in scoring_observations
    ]

    risk_counts = _group_counts(db, TransactionRuleAssessment.risk_level)
    outcome_counts = _group_counts(db, CaseOutcome.classification)
    case_status_counts = Counter(summary.status.value for summary in case_summaries)
    volume = EvaluationVolumeResponse(
        transactions=_count(db, Transaction),
        rule_assessments=_count(db, TransactionRuleAssessment),
        low_risk=risk_counts.get("low", 0),
        medium_risk=risk_counts.get("medium", 0),
        high_risk=risk_counts.get("high", 0),
        cases=len(cases),
        open_cases=case_status_counts.get("open", 0),
        in_review_cases=case_status_counts.get("in_review", 0),
        classified_cases=case_status_counts.get("classified", 0),
        confirmed_fraud=outcome_counts.get("confirmed_fraud", 0),
        legitimate=outcome_counts.get("legitimate", 0),
        inconclusive=outcome_counts.get("inconclusive", 0),
    )

    verified_scoring_latencies = [
        observation.runtime_milliseconds
        for observation, verified in zip(scoring_observations, scoring_integrity, strict=True)
        if verified
    ]
    scoring_latency = _latency_summary(
        verified_scoring_latencies,
        target_milliseconds=SCORING_LATENCY_TARGET_MILLISECONDS,
    )
    explanations = _explanation_evaluation(briefs, brief_integrity)
    integrity = IntegritySummaryResponse(
        case_events=_count(db, CaseEvent),
        case_records=len(cases),
        case_integrity_failures=case_integrity.count(False),
        model_records=len(models),
        model_integrity_failures=model_integrity.count(False),
        case_brief_records=len(briefs),
        case_brief_integrity_failures=brief_integrity.count(False),
        hybrid_records=len(hybrids),
        hybrid_integrity_failures=hybrid_integrity.count(False),
        dataset_records=len(datasets),
        dataset_integrity_failures=dataset_integrity.count(False),
        evaluation_report_records=len(reports),
        evaluation_report_integrity_failures=report_integrity.count(False),
        scoring_observation_records=len(scoring_observations),
        scoring_observation_integrity_failures=scoring_integrity.count(False),
    )
    model_evidence = ModelEvidenceResponse(
        registered_models=len(models),
        verified_model_lineages=model_integrity.count(True),
        shadow_predictions=_count(db, ShadowModelPrediction),
        hybrid_assessments=len(hybrids),
        shadow_evaluation_reports=len(reports),
        verified_shadow_evaluation_reports=report_integrity.count(True),
    )
    versions = VersionLineageResponse(
        feature_set=FEATURE_SET_VERSION,
        ruleset=RULESET_VERSION,
        risk_bands=RISK_BAND_VERSION,
        scoring_runtime_observation=SCORING_RUNTIME_OBSERVATION_SCHEMA_VERSION,
        shadow_output=SHADOW_OUTPUT_SCHEMA_VERSION,
        hybrid_policy=HYBRID_POLICY_VERSION,
        case_brief_prompt=PROMPT_VERSION,
        case_brief_output=OUTPUT_SCHEMA_VERSION,
        model_evaluation_report=SHADOW_EVALUATION_SCHEMA_VERSION,
        label_contract=LABEL_CONTRACT_VERSION,
        split_contract=SPLIT_CONTRACT_VERSION,
    )
    gates = _evaluation_gates(
        volume=volume,
        scoring_latency=scoring_latency,
        explanations=explanations,
        integrity=integrity,
        model_evidence=model_evidence,
    )
    gate_statuses = {gate.status for gate in gates}
    overall_status = (
        "attention"
        if "failed" in gate_statuses
        else "passed"
        if gate_statuses == {"passed"}
        else "evidence_pending"
    )
    latest_reports = [build_evaluation_response(db, report) for report in reports[:20]]
    evidence_as_of = _evidence_as_of(db)
    facts: dict[str, object] = {
        "schema_version": SYSTEM_EVALUATION_SCHEMA_VERSION,
        "evidence_as_of": _timestamp_text(evidence_as_of) if evidence_as_of is not None else None,
        "overall_status": overall_status,
        "volume": volume.model_dump(mode="json"),
        "scoring_latency": scoring_latency.model_dump(mode="json"),
        "explanations": explanations.model_dump(mode="json"),
        "model_evidence": model_evidence.model_dump(mode="json"),
        "integrity": integrity.model_dump(mode="json"),
        "versions": versions.model_dump(mode="json"),
        "gates": [gate.model_dump(mode="json") for gate in gates],
        "latest_model_evaluations": [report.model_dump(mode="json") for report in latest_reports],
        "read_only": True,
        "changes_operational_state": False,
    }
    return SystemEvaluationRecordResponse.model_validate(
        {**facts, "snapshot_checksum": canonical_json_checksum(facts)}
    )


def _explanation_evaluation(
    briefs: list[CaseBrief],
    brief_integrity: list[bool],
) -> ExplanationEvaluationResponse:
    validated_llm = 0
    fallbacks = 0
    candidate_failures = 0
    display_failures = 0
    fallback_reasons: Counter[str] = Counter()
    llm_latencies: list[int] = []
    for brief, verified in zip(briefs, brief_integrity, strict=True):
        try:
            validation = CaseBriefValidationResponse.model_validate(brief.validation_report)
        except ValueError:
            display_failures += 1
            continue
        if not validation.provider_candidate.grounding_passed:
            candidate_failures += 1
        if not validation.display_output.grounding_passed or not verified:
            display_failures += 1
        if (
            brief.generation_mode == "llm"
            and verified
            and validation.display_output.grounding_passed
        ):
            validated_llm += 1
            llm_latencies.append(brief.generation_milliseconds)
        elif (
            brief.generation_mode == "deterministic_fallback"
            and verified
            and validation.display_output.grounding_passed
        ):
            fallbacks += 1
            fallback_reasons[validation.fallback_reason or "unspecified"] += 1
    total = len(briefs)
    return ExplanationEvaluationResponse(
        total_briefs=total,
        validated_llm_briefs=validated_llm,
        deterministic_fallbacks=fallbacks,
        fallback_rate=_rate_text(fallbacks, total),
        provider_candidate_grounding_failures=candidate_failures,
        displayed_grounding_failures=display_failures,
        fallback_reasons=dict(sorted(fallback_reasons.items())),
        llm_latency=_latency_summary(
            llm_latencies,
            target_milliseconds=LLM_LATENCY_TARGET_MILLISECONDS,
        ),
    )


def _evaluation_gates(
    *,
    volume: EvaluationVolumeResponse,
    scoring_latency: LatencySummaryResponse,
    explanations: ExplanationEvaluationResponse,
    integrity: IntegritySummaryResponse,
    model_evidence: ModelEvidenceResponse,
) -> list[EvaluationGateResponse]:
    integrity_failures = sum(
        (
            integrity.case_integrity_failures,
            integrity.model_integrity_failures,
            integrity.case_brief_integrity_failures,
            integrity.hybrid_integrity_failures,
            integrity.dataset_integrity_failures,
            integrity.evaluation_report_integrity_failures,
            integrity.scoring_observation_integrity_failures,
        )
    )
    integrity_records = sum(
        (
            integrity.case_records,
            integrity.model_records,
            integrity.case_brief_records,
            integrity.hybrid_records,
            integrity.dataset_records,
            integrity.evaluation_report_records,
            integrity.scoring_observation_records,
        )
    )
    return [
        EvaluationGateResponse(
            gate="transaction_benchmark_volume",
            status=(
                "passed" if volume.transactions >= BENCHMARK_VOLUME_TARGET else "not_demonstrated"
            ),
            observed=volume.transactions,
            target=f">= {BENCHMARK_VOLUME_TARGET} scored transactions in one environment",
            detail="Current volume is evidence, not a synthetic capability claim.",
        ),
        EvaluationGateResponse(
            gate="deterministic_scoring_latency",
            status=scoring_latency.status,
            observed=scoring_latency.maximum_milliseconds,
            target=f"< {SCORING_LATENCY_TARGET_MILLISECONDS} ms maximum observed runtime",
            detail="Only checksum-verified runtime observations are included.",
        ),
        EvaluationGateResponse(
            gate="llm_explanation_latency",
            status=explanations.llm_latency.status,
            observed=explanations.llm_latency.maximum_milliseconds,
            target=f"< {LLM_LATENCY_TARGET_MILLISECONDS} ms maximum validated LLM runtime",
            detail="Deterministic fallbacks are excluded from the LLM latency gate.",
        ),
        EvaluationGateResponse(
            gate="displayed_explanation_grounding",
            status=(
                "not_observed"
                if explanations.total_briefs == 0
                else "passed"
                if explanations.displayed_grounding_failures == 0
                else "failed"
            ),
            observed=explanations.displayed_grounding_failures,
            target="0 displayed grounding or integrity failures",
            detail="Rejected provider candidates may fall back safely and remain audit evidence.",
        ),
        EvaluationGateResponse(
            gate="append_only_integrity",
            status=(
                "not_observed"
                if integrity_records == 0
                else "passed"
                if integrity_failures == 0
                else "failed"
            ),
            observed=integrity_failures,
            target="0 integrity failures across material record types",
            detail="Every supported record type is independently re-verified on this read.",
        ),
        EvaluationGateResponse(
            gate="reproducible_model_evaluation",
            status=(
                "not_demonstrated"
                if model_evidence.shadow_evaluation_reports == 0
                else "passed"
                if model_evidence.shadow_evaluation_reports
                == model_evidence.verified_shadow_evaluation_reports
                else "failed"
            ),
            observed=model_evidence.verified_shadow_evaluation_reports,
            target=">= 1 verified immutable shadow evaluation report",
            detail="Reports pin model, prediction, feature, rules, and authorization lineage.",
        ),
    ]


def _latency_summary(
    values: list[int],
    *,
    target_milliseconds: int,
) -> LatencySummaryResponse:
    if not values:
        return LatencySummaryResponse(
            observation_count=0,
            mean_milliseconds=None,
            p95_milliseconds=None,
            maximum_milliseconds=None,
            target_milliseconds=target_milliseconds,
            status="not_observed",
        )
    ordered = sorted(values)
    mean = Decimal(sum(ordered)) / Decimal(len(ordered))
    position = Decimal(len(ordered) - 1) * Decimal("0.95")
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    p95 = Decimal(ordered[lower_index]) + (
        Decimal(ordered[upper_index] - ordered[lower_index]) * fraction
    )
    maximum = ordered[-1]
    return LatencySummaryResponse(
        observation_count=len(ordered),
        mean_milliseconds=_decimal_text(mean),
        p95_milliseconds=_decimal_text(p95),
        maximum_milliseconds=maximum,
        target_milliseconds=target_milliseconds,
        status="passed" if maximum < target_milliseconds else "failed",
    )


def _evidence_as_of(
    db: Session,
) -> datetime | None:
    values = [
        value
        for value in (
            db.scalar(select(func.max(Transaction.created_at))),
            db.scalar(select(func.max(CaseEvent.created_at))),
            db.scalar(select(func.max(CaseOutcome.created_at))),
            db.scalar(select(func.max(CaseBrief.created_at))),
            db.scalar(select(func.max(RegisteredModel.created_at))),
            db.scalar(select(func.max(ModelLifecycleEvent.created_at))),
            db.scalar(select(func.max(ShadowModelPrediction.created_at))),
            db.scalar(select(func.max(HybridRiskAssessment.created_at))),
            db.scalar(select(func.max(OperationalDatasetSnapshot.created_at))),
            db.scalar(select(func.max(ShadowModelEvaluationReport.created_at))),
            db.scalar(select(func.max(ScoringRuntimeObservation.created_at))),
        )
        if value is not None
    ]
    return max((_utc_datetime(value) for value in values), default=None)


def _count(db: Session, model: type[Base]) -> int:
    value = db.scalar(select(func.count()).select_from(model))
    return int(value or 0)


def _group_counts(
    db: Session,
    column: InstrumentedAttribute[str],
) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {str(value): int(count) for value, count in rows}


def _rate_text(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return _decimal_text(Decimal(numerator) / Decimal(denominator))


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")).normalize(), "f")


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _timestamp_text(value: datetime) -> str:
    return _utc_datetime(value).isoformat()
