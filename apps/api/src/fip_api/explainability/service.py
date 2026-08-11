from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter_ns
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.explainability.prompt import (
    EVIDENCE_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_VERSION,
    build_provider_request,
)
from fip_api.explainability.provider import (
    CaseBriefProvider,
    CaseBriefProviderFailure,
    CaseBriefProviderUnavailable,
)
from fip_api.explainability.validation import (
    provider_failure_report,
    validate_case_brief_output,
)
from fip_api.hybrid_scoring import verify_hybrid_assessment_integrity
from fip_api.models import (
    AnalystCase,
    CaseBrief,
    HybridRiskAssessment,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
)
from fip_api.schemas.explanation import (
    CaseBriefClaim,
    CaseBriefOutput,
    CaseBriefResponse,
    CaseBriefValidationResponse,
)
from fip_api.scoring import verify_rule_assessment_integrity


class CaseBriefNotFound(LookupError):
    pass


class CaseBriefEvidenceViolation(ValueError):
    pass


def create_case_brief(
    db: Session,
    *,
    case: AnalystCase,
    hybrid_assessment_id: str | None,
    actor: User,
    provider: CaseBriefProvider,
) -> tuple[CaseBrief, bool]:
    evidence, sources = _build_input_evidence(
        db,
        case=case,
        hybrid_assessment_id=hybrid_assessment_id,
    )
    evidence_checksum = canonical_json_checksum(evidence)
    request_fingerprint = canonical_json_checksum(
        _request_facts(
            opening_checksum=case.opening_checksum,
            evidence_checksum=evidence_checksum,
            provider_name=provider.provider_name,
            provider_model=provider.model_name,
        )
    )
    existing = db.scalar(
        select(CaseBrief).where(CaseBrief.request_fingerprint == request_fingerprint)
    )
    if existing is not None:
        if not verify_case_brief_integrity(db, existing):
            raise CaseBriefEvidenceViolation("Stored case brief integrity verification failed.")
        return existing, False

    provider_output: dict[str, object] | None = None
    provider_raw_output: str | None = None
    fallback_reason: str | None = None
    generation_milliseconds = 0
    started_at = perf_counter_ns()
    try:
        result = provider.generate(build_provider_request(evidence))
        generation_milliseconds = result.generation_milliseconds
        provider_raw_output = result.raw_output[:100_000]
        candidate, provider_validation = validate_case_brief_output(
            result.output,
            _evidence_catalog(evidence),
        )
        if isinstance(result.output, dict):
            provider_output = cast(dict[str, object], result.output)
        if candidate is None or not provider_validation.grounding_passed:
            fallback_reason = "grounding_validation_failed"
    except CaseBriefProviderUnavailable as exc:
        generation_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
        provider_validation = provider_failure_report(
            code="provider_unavailable",
            detail=str(exc),
        )
        provider_raw_output = exc.raw_output[:100_000] if exc.raw_output is not None else None
        candidate = None
        fallback_reason = "provider_unavailable"
    except CaseBriefProviderFailure as exc:
        generation_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
        provider_validation = provider_failure_report(
            code="provider_failure",
            detail=str(exc),
        )
        provider_raw_output = exc.raw_output[:100_000] if exc.raw_output is not None else None
        candidate = None
        fallback_reason = "provider_failure"

    if fallback_reason is None and candidate is not None:
        generation_mode = "llm"
        display_output = candidate
        display_validation = provider_validation
    else:
        generation_mode = "deterministic_fallback"
        display_output = _deterministic_fallback(evidence)
        normalized_fallback, display_validation = validate_case_brief_output(
            display_output.model_dump(mode="json"),
            _evidence_catalog(evidence),
        )
        if normalized_fallback is None or not display_validation.grounding_passed:
            raise RuntimeError("Deterministic case brief failed its grounding contract.")
        display_output = normalized_fallback

    validation_report = CaseBriefValidationResponse(
        provider_candidate=provider_validation,
        display_output=display_validation,
        fallback_used=generation_mode == "deterministic_fallback",
        fallback_reason=fallback_reason,
    ).model_dump(mode="json")
    created_at = datetime.now(UTC)
    display_output_json = display_output.model_dump(mode="json")
    explanation_checksum = canonical_json_checksum(
        _explanation_facts(
            external_transaction_id=sources.transaction.external_transaction_id,
            opening_checksum=case.opening_checksum,
            rule_assessment_checksum=sources.rule_assessment.assessment_checksum,
            hybrid_assessment_checksum=(
                sources.hybrid_assessment.assessment_checksum
                if sources.hybrid_assessment is not None
                else None
            ),
            evidence_checksum=evidence_checksum,
            provider_name=provider.provider_name,
            provider_model=provider.model_name,
            generation_mode=generation_mode,
            provider_output=provider_output,
            provider_raw_output=provider_raw_output,
            display_output=display_output_json,
            validation_report=validation_report,
            generation_milliseconds=generation_milliseconds,
            requested_by=actor.username,
            created_at=created_at,
        )
    )
    brief = CaseBrief(
        case_id=case.id,
        transaction_id=sources.transaction.id,
        rule_assessment_id=sources.rule_assessment.id,
        hybrid_assessment_id=(
            sources.hybrid_assessment.id if sources.hybrid_assessment is not None else None
        ),
        prompt_version=PROMPT_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        provider_name=provider.provider_name,
        provider_model=provider.model_name,
        generation_mode=generation_mode,
        input_evidence=evidence,
        evidence_checksum=evidence_checksum,
        provider_output=provider_output,
        provider_raw_output=provider_raw_output,
        display_output=display_output_json,
        validation_report=validation_report,
        generation_milliseconds=generation_milliseconds,
        requested_by_id=actor.id,
        request_fingerprint=request_fingerprint,
        explanation_checksum=explanation_checksum,
        created_at=created_at,
    )
    db.add(brief)
    db.flush()
    return brief, True


def list_case_briefs(db: Session, case_id: str) -> list[CaseBrief]:
    return list(
        db.scalars(
            select(CaseBrief)
            .where(CaseBrief.case_id == case_id)
            .order_by(CaseBrief.created_at, CaseBrief.id)
        ).all()
    )


def build_case_brief_response(db: Session, brief: CaseBrief) -> CaseBriefResponse:
    requested_by = db.get(User, brief.requested_by_id)
    if requested_by is None:
        raise CaseBriefEvidenceViolation("Case brief references a missing requester.")
    try:
        output = CaseBriefOutput.model_validate(brief.display_output)
    except ValueError:
        output = None
    try:
        validation = CaseBriefValidationResponse.model_validate(brief.validation_report)
    except ValueError:
        validation = None
    return CaseBriefResponse(
        id=brief.id,
        case_id=brief.case_id,
        transaction_id=brief.transaction_id,
        rule_assessment_id=brief.rule_assessment_id,
        hybrid_assessment_id=brief.hybrid_assessment_id,
        prompt_version=brief.prompt_version,
        output_schema_version=brief.output_schema_version,
        provider_name=brief.provider_name,
        provider_model=brief.provider_model,
        generation_mode=cast(Literal["llm", "deterministic_fallback"], brief.generation_mode),
        output=output,
        validation=validation,
        evidence_checksum=brief.evidence_checksum,
        explanation_checksum=brief.explanation_checksum,
        integrity_verified=verify_case_brief_integrity(db, brief),
        generation_milliseconds=brief.generation_milliseconds,
        requested_by=requested_by.username,
        created_at=brief.created_at,
    )


def verify_case_brief_integrity(db: Session, brief: CaseBrief) -> bool:
    case = db.get(AnalystCase, brief.case_id)
    requested_by = db.get(User, brief.requested_by_id)
    if case is None or requested_by is None:
        return False
    try:
        evidence, sources = _build_input_evidence(
            db,
            case=case,
            hybrid_assessment_id=brief.hybrid_assessment_id,
        )
    except (CaseBriefNotFound, CaseBriefEvidenceViolation):
        return False
    evidence_checksum = canonical_json_checksum(evidence)
    try:
        display_output, display_validation = validate_case_brief_output(
            brief.display_output,
            _evidence_catalog(evidence),
        )
        stored_validation = CaseBriefValidationResponse.model_validate(brief.validation_report)
    except (TypeError, ValueError):
        return False
    if display_output is None:
        return False
    if brief.provider_output is not None:
        _, provider_validation = validate_case_brief_output(
            brief.provider_output,
            _evidence_catalog(evidence),
        )
        if provider_validation != stored_validation.provider_candidate:
            return False
    if (
        brief.generation_mode == "deterministic_fallback"
        and display_output != _deterministic_fallback(evidence)
    ):
        return False
    request_fingerprint = canonical_json_checksum(
        _request_facts(
            opening_checksum=case.opening_checksum,
            evidence_checksum=evidence_checksum,
            provider_name=brief.provider_name,
            provider_model=brief.provider_model,
        )
    )
    expected_checksum = canonical_json_checksum(
        _explanation_facts(
            external_transaction_id=sources.transaction.external_transaction_id,
            opening_checksum=case.opening_checksum,
            rule_assessment_checksum=sources.rule_assessment.assessment_checksum,
            hybrid_assessment_checksum=(
                sources.hybrid_assessment.assessment_checksum
                if sources.hybrid_assessment is not None
                else None
            ),
            evidence_checksum=brief.evidence_checksum,
            provider_name=brief.provider_name,
            provider_model=brief.provider_model,
            generation_mode=brief.generation_mode,
            provider_output=brief.provider_output,
            provider_raw_output=brief.provider_raw_output,
            display_output=brief.display_output,
            validation_report=brief.validation_report,
            generation_milliseconds=brief.generation_milliseconds,
            requested_by=requested_by.username,
            created_at=brief.created_at,
        )
    )
    return (
        brief.prompt_version == PROMPT_VERSION
        and brief.output_schema_version == OUTPUT_SCHEMA_VERSION
        and brief.transaction_id == sources.transaction.id
        and brief.rule_assessment_id == sources.rule_assessment.id
        and brief.hybrid_assessment_id
        == (sources.hybrid_assessment.id if sources.hybrid_assessment is not None else None)
        and brief.input_evidence == evidence
        and brief.evidence_checksum == evidence_checksum
        and brief.request_fingerprint == request_fingerprint
        and brief.explanation_checksum == expected_checksum
        and display_validation == stored_validation.display_output
        and display_validation.grounding_passed
        and stored_validation.fallback_used == (brief.generation_mode == "deterministic_fallback")
        and (
            brief.generation_mode == "deterministic_fallback"
            or stored_validation.provider_candidate.grounding_passed
        )
    )


class _EvidenceSources:
    def __init__(
        self,
        *,
        transaction: Transaction,
        snapshot: TransactionFeatureSnapshot,
        rule_assessment: TransactionRuleAssessment,
        hybrid_assessment: HybridRiskAssessment | None,
    ) -> None:
        self.transaction = transaction
        self.snapshot = snapshot
        self.rule_assessment = rule_assessment
        self.hybrid_assessment = hybrid_assessment


def _build_input_evidence(
    db: Session,
    *,
    case: AnalystCase,
    hybrid_assessment_id: str | None,
) -> tuple[dict[str, object], _EvidenceSources]:
    transaction = db.get(Transaction, case.transaction_id)
    snapshot = db.get(TransactionFeatureSnapshot, case.feature_snapshot_id)
    rule_assessment = db.get(TransactionRuleAssessment, case.rule_assessment_id)
    if transaction is None or snapshot is None or rule_assessment is None:
        raise CaseBriefEvidenceViolation("Case references missing deterministic evidence.")
    if not verify_rule_assessment_integrity(snapshot, rule_assessment, transaction):
        raise CaseBriefEvidenceViolation("Rule assessment integrity verification failed.")
    hybrid_assessment: HybridRiskAssessment | None = None
    if hybrid_assessment_id is not None:
        hybrid_assessment = db.get(HybridRiskAssessment, hybrid_assessment_id)
        if hybrid_assessment is None:
            raise CaseBriefNotFound("Hybrid assessment not found.")
        if (
            hybrid_assessment.transaction_id != transaction.id
            or hybrid_assessment.feature_snapshot_id != snapshot.id
            or hybrid_assessment.rule_assessment_id != rule_assessment.id
        ):
            raise CaseBriefEvidenceViolation(
                "Hybrid assessment does not belong to the case evidence set."
            )
        if not verify_hybrid_assessment_integrity(db, hybrid_assessment):
            raise CaseBriefEvidenceViolation("Hybrid assessment integrity verification failed.")

    catalog: dict[str, object] = {
        "transaction.amount": {
            "amount": _decimal_text(transaction.amount),
            "currency": transaction.currency,
        },
        "transaction.occurred_at": _timestamp_text(transaction.occurred_at),
        "transaction.channel": transaction.channel,
        "transaction.merchant_category_code": transaction.merchant_category_code,
        "transaction.countries": {
            "source_country": transaction.source_country,
            "destination_country": transaction.destination_country,
        },
        "rule_assessment.score": {
            "score": rule_assessment.rule_score,
            "maximum": 100,
            "risk_level": rule_assessment.risk_level,
        },
        "limitations.human_authority": {
            "human_review_required": True,
            "llm_may_classify_case": False,
        },
        "limitations.no_financial_action": {
            "financial_action_allowed": False,
            "decision_support_only": True,
        },
    }
    triggered_rule_refs: list[str] = []
    for index, trigger in enumerate(rule_assessment.triggered_rules):
        rule_id = str(trigger.get("rule_id") or f"index-{index + 1}")
        reference = f"rules.{rule_id}"
        catalog[reference] = trigger
        triggered_rule_refs.append(reference)
    for feature_name, value in snapshot.feature_values.items():
        catalog[f"features.{feature_name}"] = value

    if hybrid_assessment is None:
        catalog["limitations.no_hybrid"] = {
            "verified_hybrid_assessment_supplied": False,
            "model_factor_evidence_available": False,
        }
    else:
        catalog["hybrid.score"] = {
            "combined_score": _decimal_text(hybrid_assessment.combined_score),
            "maximum": 100,
            "risk_level": hybrid_assessment.risk_level,
            "policy_version": hybrid_assessment.policy_version,
        }
        components = hybrid_assessment.evidence_package.get("components")
        if isinstance(components, dict):
            for component_name in ("rules", "supervised", "anomaly"):
                if component_name in components:
                    catalog[f"hybrid.components.{component_name}"] = components[component_name]
        lineage = hybrid_assessment.evidence_package.get("lineage")
        if isinstance(lineage, dict):
            for model_kind in ("supervised", "anomaly"):
                model_lineage = lineage.get(model_kind)
                if not isinstance(model_lineage, dict):
                    continue
                factors = model_lineage.get("factor_contributions")
                if isinstance(factors, list):
                    for factor in factors:
                        if isinstance(factor, dict) and "feature" in factor:
                            catalog[f"hybrid.{model_kind}.factor.{factor['feature']}"] = factor
        catalog["hybrid.limitations"] = hybrid_assessment.evidence_package.get("limitations", {})

    evidence: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "case": {
            "display_id": case.display_id,
            "priority": case.priority,
            "opening_reason": case.opening_reason,
        },
        "evidence_catalog": dict(sorted(catalog.items())),
        "triggered_rule_refs": triggered_rule_refs,
        "lineage": {
            "feature_set_version": snapshot.feature_set_version,
            "feature_snapshot_checksum": snapshot.snapshot_checksum,
            "ruleset_version": rule_assessment.ruleset_version,
            "rule_assessment_checksum": rule_assessment.assessment_checksum,
            "hybrid_assessment_checksum": (
                hybrid_assessment.assessment_checksum if hybrid_assessment is not None else None
            ),
        },
    }
    return evidence, _EvidenceSources(
        transaction=transaction,
        snapshot=snapshot,
        rule_assessment=rule_assessment,
        hybrid_assessment=hybrid_assessment,
    )


def _deterministic_fallback(evidence: dict[str, object]) -> CaseBriefOutput:
    catalog = _evidence_catalog(evidence)
    rule_score = _mapping(catalog["rule_assessment.score"])
    score = str(rule_score["score"])
    risk_level = str(rule_score["risk_level"])
    summary = (
        f"The deterministic rules assessment recorded {score} out of 100 and a "
        f"{risk_level} risk level. Human review remains required."
    )
    summary_refs = ["rule_assessment.score", "limitations.human_authority"]
    if "hybrid.score" in catalog:
        hybrid_score = _mapping(catalog["hybrid.score"])
        summary += (
            " Separate hybrid decision-support evidence recorded "
            f"{hybrid_score['combined_score']} out of 100 and a "
            f"{hybrid_score['risk_level']} risk level."
        )
        summary_refs.extend(["hybrid.score", "hybrid.limitations"])

    triggered_refs = evidence.get("triggered_rule_refs")
    primary_factors: list[CaseBriefClaim] = []
    if isinstance(triggered_refs, list):
        for reference in triggered_refs[:5]:
            if not isinstance(reference, str) or reference not in catalog:
                continue
            trigger = _mapping(catalog[reference])
            primary_factors.append(
                CaseBriefClaim(
                    text=(
                        f"{trigger.get('title', 'Triggered rule')} contributed "
                        f"{trigger.get('contribution_points', 0)} rule points."
                    ),
                    evidence_refs=[reference],
                )
            )
    if not primary_factors:
        primary_factors.append(
            CaseBriefClaim(
                text=f"The rules assessment recorded a {risk_level} risk level.",
                evidence_refs=["rule_assessment.score"],
            )
        )

    amount = _mapping(catalog["transaction.amount"])
    supporting_evidence = [
        CaseBriefClaim(
            text=f"The transaction amount was {amount['currency']} {amount['amount']}.",
            evidence_refs=["transaction.amount"],
        ),
        CaseBriefClaim(
            text=f"The transaction occurred at {catalog['transaction.occurred_at']}.",
            evidence_refs=["transaction.occurred_at"],
        ),
    ]
    uncertainty = (
        CaseBriefClaim(
            text=(
                "The model inputs are shadow-only and do not change the rules score "
                "or case priority."
            ),
            evidence_refs=["hybrid.limitations"],
        )
        if "hybrid.score" in catalog
        else CaseBriefClaim(
            text="No verified hybrid model assessment was supplied for this case brief.",
            evidence_refs=["limitations.no_hybrid"],
        )
    )
    review_steps = [
        CaseBriefClaim(
            text="Review the cited transaction amount and timing against the rule evidence.",
            evidence_refs=[
                "transaction.amount",
                "transaction.occurred_at",
                "rule_assessment.score",
            ],
        ),
        CaseBriefClaim(
            text="Compare the available behavioral history with the transaction context.",
            evidence_refs=["features.prior_transaction_count_30d"],
        ),
        CaseBriefClaim(
            text=(
                "Keep the final case classification under human review; this brief is "
                "decision support only."
            ),
            evidence_refs=[
                "limitations.human_authority",
                "limitations.no_financial_action",
            ],
        ),
    ]
    return CaseBriefOutput(
        summary=summary,
        summary_evidence_refs=summary_refs,
        primary_risk_factors=primary_factors,
        supporting_evidence=supporting_evidence,
        uncertainties=[uncertainty],
        recommended_review_steps=review_steps,
    )


def _request_facts(
    *,
    opening_checksum: str,
    evidence_checksum: str,
    provider_name: str,
    provider_model: str,
) -> dict[str, object]:
    return {
        "opening_checksum": opening_checksum,
        "evidence_checksum": evidence_checksum,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "provider_name": provider_name,
        "provider_model": provider_model,
    }


def _explanation_facts(
    *,
    external_transaction_id: str,
    opening_checksum: str,
    rule_assessment_checksum: str,
    hybrid_assessment_checksum: str | None,
    evidence_checksum: str,
    provider_name: str,
    provider_model: str,
    generation_mode: str,
    provider_output: dict[str, object] | None,
    provider_raw_output: str | None,
    display_output: dict[str, object],
    validation_report: dict[str, object],
    generation_milliseconds: int,
    requested_by: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "external_transaction_id": external_transaction_id,
        "opening_checksum": opening_checksum,
        "rule_assessment_checksum": rule_assessment_checksum,
        "hybrid_assessment_checksum": hybrid_assessment_checksum,
        "evidence_checksum": evidence_checksum,
        "prompt_version": PROMPT_VERSION,
        "output_schema_version": OUTPUT_SCHEMA_VERSION,
        "provider_name": provider_name,
        "provider_model": provider_model,
        "generation_mode": generation_mode,
        "provider_output": provider_output,
        "provider_raw_output": provider_raw_output,
        "display_output": display_output,
        "validation_report": validation_report,
        "generation_milliseconds": generation_milliseconds,
        "requested_by": requested_by,
        "created_at": _timestamp_text(created_at),
        "llm_changed_score": False,
        "llm_classified_case": False,
        "financial_action_taken": False,
    }


def _evidence_catalog(evidence: dict[str, object]) -> dict[str, object]:
    catalog = evidence.get("evidence_catalog")
    if not isinstance(catalog, dict):
        raise CaseBriefEvidenceViolation("Case brief evidence catalog is malformed.")
    return catalog


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CaseBriefEvidenceViolation("Case brief evidence entry is malformed.")
    return value


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()
