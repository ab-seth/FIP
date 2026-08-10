from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.core.checksums import canonical_json_checksum
from fip_api.models import (
    AnalystCase,
    CaseClassification,
    CaseEvent,
    CaseEventType,
    CaseOutcome,
    CaseOutcomeReview,
    CasePriority,
    CaseStatus,
    OutcomeReviewStatus,
    RuleRiskLevel,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
    UserRole,
)
from fip_api.schemas.case import (
    CaseDetailResponse,
    CaseEventResponse,
    CaseOutcomeResponse,
    CaseOutcomeReviewResponse,
    CaseRuleEvidenceResponse,
    CaseSummaryResponse,
    CaseTransactionResponse,
)
from fip_api.scoring import verify_rule_assessment_integrity

SYSTEM_ACTOR = "fip-scoring"


class CaseNotFound(LookupError):
    pass


class CaseConflict(ValueError):
    pass


class CaseGovernanceViolation(ValueError):
    pass


def open_case_for_assessment(
    db: Session,
    transaction: Transaction,
    snapshot: TransactionFeatureSnapshot,
    assessment: TransactionRuleAssessment,
) -> AnalystCase | None:
    if assessment.risk_level == RuleRiskLevel.LOW.value:
        return None
    existing = db.scalar(select(AnalystCase).where(AnalystCase.transaction_id == transaction.id))
    if existing is not None:
        return existing

    case_id = uuid4()
    created_at = datetime.now(UTC)
    display_id = _display_id(case_id)
    priority = (
        CasePriority.URGENT
        if assessment.risk_level == RuleRiskLevel.HIGH.value
        else CasePriority.STANDARD
    )
    opening_reason = (
        f"Rules-only assessment marked the transaction {assessment.risk_level} risk; "
        "human classification is required."
    )
    opening_checksum = canonical_json_checksum(
        _opening_facts(
            display_id=display_id,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            assessment_checksum=assessment.assessment_checksum,
            priority=priority.value,
            opening_reason=opening_reason,
            created_at=created_at,
        )
    )
    case = AnalystCase(
        id=str(case_id),
        display_id=display_id,
        transaction_id=transaction.id,
        feature_snapshot_id=snapshot.id,
        rule_assessment_id=assessment.id,
        priority=priority.value,
        opening_reason=opening_reason,
        opening_checksum=opening_checksum,
        created_at=created_at,
    )
    db.add(case)
    db.flush()
    event = _new_event(
        case=case,
        sequence_number=1,
        event_type=CaseEventType.OPENED,
        payload={
            "assessment_checksum": assessment.assessment_checksum,
            "feature_snapshot_checksum": snapshot.snapshot_checksum,
            "opening_reason": opening_reason,
            "priority": priority.value,
            "risk_level": assessment.risk_level,
            "rule_score": assessment.rule_score,
        },
        actor=None,
        actor_username=SYSTEM_ACTOR,
        previous_event_checksum=None,
    )
    db.add(event)
    db.flush()
    return case


def list_cases(db: Session, status: CaseStatus | None = None) -> list[AnalystCase]:
    cases = list(db.scalars(select(AnalystCase).order_by(AnalystCase.created_at.desc())).all())
    if status is None:
        return cases
    return [case for case in cases if current_case_status(db, case.id) is status]


def start_case_review(db: Session, case_id: str, reason: str, actor: User) -> AnalystCase:
    _assert_investigator(actor)
    case = _locked_case(db, case_id)
    _assert_integrity(db, case)
    status = current_case_status(db, case.id)
    if status is CaseStatus.CLASSIFIED:
        raise CaseConflict("A classified case cannot re-enter review.")
    if status is CaseStatus.IN_REVIEW:
        return case
    _append_event(
        db,
        case,
        CaseEventType.REVIEW_STARTED,
        {"reason": reason.strip()},
        actor,
    )
    return case


def add_case_note(db: Session, case_id: str, note: str, actor: User) -> AnalystCase:
    _assert_investigator(actor)
    case = _locked_case(db, case_id)
    _assert_integrity(db, case)
    status = current_case_status(db, case.id)
    if status is CaseStatus.CLASSIFIED:
        raise CaseConflict("Notes cannot be added after final classification.")
    if status is CaseStatus.OPEN:
        raise CaseConflict("Begin case review before adding analyst notes.")
    _append_event(db, case, CaseEventType.NOTE_ADDED, {"note": note.strip()}, actor)
    return case


def classify_case(
    db: Session,
    case_id: str,
    classification: CaseClassification,
    rationale: str,
    actor: User,
) -> AnalystCase:
    _assert_investigator(actor)
    case = _locked_case(db, case_id)
    _assert_integrity(db, case)
    if current_case_status(db, case.id) is not CaseStatus.IN_REVIEW:
        raise CaseConflict("Case review must begin before final classification.")
    if _outcome(db, case.id) is not None:
        raise CaseConflict("The case already has a final classification.")

    transaction, snapshot, assessment = _evidence(db, case)
    created_at = datetime.now(UTC)
    outcome_checksum = canonical_json_checksum(
        _outcome_facts(
            opening_checksum=case.opening_checksum,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            assessment_checksum=assessment.assessment_checksum,
            classification=classification.value,
            rationale=rationale.strip(),
            determined_by=actor.username,
            created_at=created_at,
        )
    )
    outcome = CaseOutcome(
        case_id=case.id,
        classification=classification.value,
        rationale=rationale.strip(),
        determined_by_id=actor.id,
        outcome_checksum=outcome_checksum,
        created_at=created_at,
    )
    db.add(outcome)
    db.flush()
    _append_event(
        db,
        case,
        CaseEventType.CLASSIFIED,
        {
            "classification": classification.value,
            "outcome_checksum": outcome.outcome_checksum,
            "outcome_id": outcome.id,
            "rationale": outcome.rationale,
        },
        actor,
    )
    return case


def review_case_outcome(
    db: Session,
    case_id: str,
    outcome_id: str,
    review_status: OutcomeReviewStatus,
    reason: str,
    actor: User,
) -> AnalystCase:
    if actor.role != UserRole.EVALUATOR.value:
        raise CaseGovernanceViolation("Only an evaluator may review a future-ML label.")
    case = _locked_case(db, case_id)
    _assert_integrity(db, case)
    outcome = _outcome(db, case.id)
    if outcome is None or outcome.id != outcome_id:
        raise CaseNotFound("Case outcome not found.")
    if outcome.classification == CaseClassification.INCONCLUSIVE.value:
        raise CaseGovernanceViolation(
            "Inconclusive outcomes cannot become supervised-learning labels."
        )
    if actor.id == outcome.determined_by_id:
        raise CaseGovernanceViolation(
            "The label reviewer must be independent from the analyst who classified the case."
        )
    existing = _review(db, outcome.id)
    if existing is not None:
        raise CaseConflict("The outcome already has an immutable label review.")

    created_at = datetime.now(UTC)
    review_checksum = canonical_json_checksum(
        _review_facts(
            outcome_checksum=outcome.outcome_checksum,
            status=review_status.value,
            reason=reason.strip(),
            reviewed_by=actor.username,
            created_at=created_at,
        )
    )
    review = CaseOutcomeReview(
        outcome_id=outcome.id,
        status=review_status.value,
        reason=reason.strip(),
        reviewed_by_id=actor.id,
        review_checksum=review_checksum,
        created_at=created_at,
    )
    db.add(review)
    db.flush()
    _append_event(
        db,
        case,
        CaseEventType.OUTCOME_REVIEWED,
        {
            "outcome_id": outcome.id,
            "reason": review.reason,
            "review_checksum": review.review_checksum,
            "status": review.status,
        },
        actor,
    )
    return case


def build_case_summary_response(db: Session, case: AnalystCase) -> CaseSummaryResponse:
    transaction, _, assessment = _evidence(db, case)
    events = _events(db, case.id)
    return CaseSummaryResponse(
        id=case.id,
        display_id=case.display_id,
        status=_status_from_events(events),
        priority=CasePriority(case.priority),
        transaction=_transaction_response(transaction),
        risk_score=assessment.rule_score,
        risk_level=RuleRiskLevel(assessment.risk_level),
        triggered_rule_count=len(assessment.triggered_rules),
        outcome=_outcome_response(db, case),
        opening_checksum=case.opening_checksum,
        integrity_verified=_verify_case_integrity(db, case, events),
        created_at=_utc_datetime(case.created_at),
        last_activity_at=_utc_datetime(events[-1].created_at if events else case.created_at),
    )


def build_case_detail_response(db: Session, case: AnalystCase) -> CaseDetailResponse:
    transaction, snapshot, assessment = _evidence(db, case)
    events = _events(db, case.id)
    summary = build_case_summary_response(db, case)
    return CaseDetailResponse(
        **summary.model_dump(),
        opening_reason=case.opening_reason,
        evidence=CaseRuleEvidenceResponse(
            rule_score=assessment.rule_score,
            risk_level=RuleRiskLevel(assessment.risk_level),
            ruleset_version=assessment.ruleset_version,
            assessment_checksum=assessment.assessment_checksum,
            feature_set_version=snapshot.feature_set_version,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            triggered_rules=assessment.triggered_rules,
            feature_values=snapshot.feature_values,
        ),
        events=[
            CaseEventResponse(
                sequence_number=event.sequence_number,
                event_type=CaseEventType(event.event_type),
                payload=event.payload,
                actor_username=event.actor_username,
                previous_event_checksum=event.previous_event_checksum,
                event_checksum=event.event_checksum,
                created_at=_utc_datetime(event.created_at),
            )
            for event in events
        ],
    )


def verify_case_integrity(db: Session, case: AnalystCase) -> bool:
    return _verify_case_integrity(db, case, _events(db, case.id))


def current_case_status(db: Session, case_id: str) -> CaseStatus:
    return _status_from_events(_events(db, case_id))


def _locked_case(db: Session, case_id: str) -> AnalystCase:
    case = db.scalar(select(AnalystCase).where(AnalystCase.id == case_id).with_for_update())
    if case is None:
        raise CaseNotFound("Investigation case not found.")
    return case


def _append_event(
    db: Session,
    case: AnalystCase,
    event_type: CaseEventType,
    payload: dict[str, object],
    actor: User,
) -> CaseEvent:
    current = _events(db, case.id)[-1]
    event = _new_event(
        case=case,
        sequence_number=current.sequence_number + 1,
        event_type=event_type,
        payload=payload,
        actor=actor,
        actor_username=actor.username,
        previous_event_checksum=current.event_checksum,
    )
    db.add(event)
    db.flush()
    return event


def _new_event(
    *,
    case: AnalystCase,
    sequence_number: int,
    event_type: CaseEventType,
    payload: dict[str, object],
    actor: User | None,
    actor_username: str,
    previous_event_checksum: str | None,
) -> CaseEvent:
    created_at = datetime.now(UTC)
    event_checksum = canonical_json_checksum(
        _event_facts(
            opening_checksum=case.opening_checksum,
            sequence_number=sequence_number,
            event_type=event_type.value,
            payload=payload,
            actor_username=actor_username,
            previous_event_checksum=previous_event_checksum,
            created_at=created_at,
        )
    )
    return CaseEvent(
        case_id=case.id,
        sequence_number=sequence_number,
        event_type=event_type.value,
        payload=payload,
        actor_user_id=actor.id if actor is not None else None,
        actor_username=actor_username,
        previous_event_checksum=previous_event_checksum,
        event_checksum=event_checksum,
        created_at=created_at,
    )


def _verify_case_integrity(
    db: Session,
    case: AnalystCase,
    events: list[CaseEvent],
) -> bool:
    try:
        transaction, snapshot, assessment = _evidence(db, case)
    except CaseGovernanceViolation:
        return False
    expected_opening_checksum = canonical_json_checksum(
        _opening_facts(
            display_id=case.display_id,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            assessment_checksum=assessment.assessment_checksum,
            priority=case.priority,
            opening_reason=case.opening_reason,
            created_at=case.created_at,
        )
    )
    if expected_opening_checksum != case.opening_checksum or not events:
        return False
    expected_snapshot_checksum = canonical_json_checksum(
        {
            "feature_set_version": snapshot.feature_set_version,
            "feature_values": snapshot.feature_values,
            "history_checksum": snapshot.history_checksum,
            "external_transaction_id": transaction.external_transaction_id,
        }
    )
    if (
        expected_snapshot_checksum != snapshot.snapshot_checksum
        or not verify_rule_assessment_integrity(snapshot, assessment, transaction)
    ):
        return False

    previous_checksum: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if (
            event.sequence_number != expected_sequence
            or event.previous_event_checksum != previous_checksum
        ):
            return False
        expected_event_checksum = canonical_json_checksum(
            _event_facts(
                opening_checksum=case.opening_checksum,
                sequence_number=event.sequence_number,
                event_type=event.event_type,
                payload=event.payload,
                actor_username=event.actor_username,
                previous_event_checksum=event.previous_event_checksum,
                created_at=event.created_at,
            )
        )
        if expected_event_checksum != event.event_checksum:
            return False
        previous_checksum = event.event_checksum

    outcome = _outcome(db, case.id)
    if outcome is None:
        return all(event.event_type != CaseEventType.CLASSIFIED.value for event in events)
    determiner = db.get(User, outcome.determined_by_id)
    if determiner is None:
        return False
    expected_outcome_checksum = canonical_json_checksum(
        _outcome_facts(
            opening_checksum=case.opening_checksum,
            external_transaction_id=transaction.external_transaction_id,
            feature_snapshot_checksum=snapshot.snapshot_checksum,
            assessment_checksum=assessment.assessment_checksum,
            classification=outcome.classification,
            rationale=outcome.rationale,
            determined_by=determiner.username,
            created_at=outcome.created_at,
        )
    )
    if expected_outcome_checksum != outcome.outcome_checksum:
        return False
    review = _review(db, outcome.id)
    if review is None:
        return True
    reviewer = db.get(User, review.reviewed_by_id)
    if reviewer is None or reviewer.id == determiner.id:
        return False
    return review.review_checksum == canonical_json_checksum(
        _review_facts(
            outcome_checksum=outcome.outcome_checksum,
            status=review.status,
            reason=review.reason,
            reviewed_by=reviewer.username,
            created_at=_utc_datetime(review.created_at),
        )
    )


def _assert_integrity(db: Session, case: AnalystCase) -> None:
    if not verify_case_integrity(db, case):
        raise CaseGovernanceViolation("Case audit integrity verification failed.")


def _assert_investigator(actor: User) -> None:
    if actor.role not in {UserRole.ADMINISTRATOR.value, UserRole.ANALYST.value}:
        raise CaseGovernanceViolation(
            "Only an administrator or analyst may change the investigation record."
        )


def _evidence(
    db: Session, case: AnalystCase
) -> tuple[Transaction, TransactionFeatureSnapshot, TransactionRuleAssessment]:
    transaction = db.get(Transaction, case.transaction_id)
    snapshot = db.get(TransactionFeatureSnapshot, case.feature_snapshot_id)
    assessment = db.get(TransactionRuleAssessment, case.rule_assessment_id)
    if (
        transaction is None
        or snapshot is None
        or assessment is None
        or snapshot.transaction_id != transaction.id
        or assessment.transaction_id != transaction.id
        or assessment.feature_snapshot_id != snapshot.id
    ):
        raise CaseGovernanceViolation("Case evidence references are inconsistent.")
    return transaction, snapshot, assessment


def _events(db: Session, case_id: str) -> list[CaseEvent]:
    return list(
        db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case_id)
            .order_by(CaseEvent.sequence_number)
        ).all()
    )


def _outcome(db: Session, case_id: str) -> CaseOutcome | None:
    return db.scalar(select(CaseOutcome).where(CaseOutcome.case_id == case_id))


def _review(db: Session, outcome_id: str) -> CaseOutcomeReview | None:
    return db.scalar(select(CaseOutcomeReview).where(CaseOutcomeReview.outcome_id == outcome_id))


def _outcome_response(db: Session, case: AnalystCase) -> CaseOutcomeResponse | None:
    outcome = _outcome(db, case.id)
    if outcome is None:
        return None
    determiner = db.get(User, outcome.determined_by_id)
    review = _review(db, outcome.id)
    review_response: CaseOutcomeReviewResponse | None = None
    if review is not None:
        reviewer = db.get(User, review.reviewed_by_id)
        review_response = CaseOutcomeReviewResponse(
            status=OutcomeReviewStatus(review.status),
            reason=review.reason,
            reviewed_by=reviewer.username if reviewer is not None else "unknown",
            review_checksum=review.review_checksum,
            created_at=review.created_at,
        )
    training_eligible = (
        outcome.classification != CaseClassification.INCONCLUSIVE.value
        and review is not None
        and review.status == OutcomeReviewStatus.APPROVED.value
        and verify_case_integrity(db, case)
    )
    return CaseOutcomeResponse(
        id=outcome.id,
        classification=CaseClassification(outcome.classification),
        rationale=outcome.rationale,
        determined_by=determiner.username if determiner is not None else "unknown",
        outcome_checksum=outcome.outcome_checksum,
        review=review_response,
        training_eligible=training_eligible,
        created_at=_utc_datetime(outcome.created_at),
    )


def _transaction_response(transaction: Transaction) -> CaseTransactionResponse:
    return CaseTransactionResponse(
        id=transaction.id,
        external_transaction_id=transaction.external_transaction_id,
        occurred_at=_utc_datetime(transaction.occurred_at),
        amount=transaction.amount,
        currency=transaction.currency,
        account_reference=transaction.account_reference,
        merchant_reference=transaction.merchant_reference,
        channel=transaction.channel,
    )


def _status_from_events(events: list[CaseEvent]) -> CaseStatus:
    if any(event.event_type == CaseEventType.CLASSIFIED.value for event in events):
        return CaseStatus.CLASSIFIED
    if any(event.event_type == CaseEventType.REVIEW_STARTED.value for event in events):
        return CaseStatus.IN_REVIEW
    return CaseStatus.OPEN


def _opening_facts(
    *,
    display_id: str,
    external_transaction_id: str,
    feature_snapshot_checksum: str,
    assessment_checksum: str,
    priority: str,
    opening_reason: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "display_id": display_id,
        "external_transaction_id": external_transaction_id,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "assessment_checksum": assessment_checksum,
        "priority": priority,
        "opening_reason": opening_reason,
        "created_at": _timestamp_text(created_at),
    }


def _event_facts(
    *,
    opening_checksum: str,
    sequence_number: int,
    event_type: str,
    payload: dict[str, object],
    actor_username: str,
    previous_event_checksum: str | None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "opening_checksum": opening_checksum,
        "sequence_number": sequence_number,
        "event_type": event_type,
        "payload": payload,
        "actor_username": actor_username,
        "previous_event_checksum": previous_event_checksum,
        "created_at": _timestamp_text(created_at),
    }


def _outcome_facts(
    *,
    opening_checksum: str,
    external_transaction_id: str,
    feature_snapshot_checksum: str,
    assessment_checksum: str,
    classification: str,
    rationale: str,
    determined_by: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "opening_checksum": opening_checksum,
        "external_transaction_id": external_transaction_id,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "assessment_checksum": assessment_checksum,
        "classification": classification,
        "rationale": rationale,
        "determined_by": determined_by,
        "created_at": _timestamp_text(created_at),
    }


def _review_facts(
    *,
    outcome_checksum: str,
    status: str,
    reason: str,
    reviewed_by: str,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "outcome_checksum": outcome_checksum,
        "status": status,
        "reason": reason,
        "reviewed_by": reviewed_by,
        "created_at": _timestamp_text(created_at),
    }


def _display_id(value: UUID) -> str:
    return f"CASE-{value.hex[:8].upper()}"


def _timestamp_text(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat()


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
