from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.cases import verify_case_integrity
from fip_api.core.checksums import canonical_json_checksum
from fip_api.features import FEATURE_SET_VERSION
from fip_api.models import (
    AnalystCase,
    CaseClassification,
    CaseOutcome,
    CaseOutcomeReview,
    DatasetReadinessStatus,
    DatasetSplit,
    OperationalDatasetRow,
    OperationalDatasetSnapshot,
    OutcomeReviewStatus,
    Transaction,
    TransactionFeatureSnapshot,
    User,
)
from fip_api.schemas.training_dataset import (
    DatasetDetailResponse,
    DatasetReadinessGateResponse,
    DatasetReadinessResponse,
    DatasetRowResponse,
    DatasetSplitCountsResponse,
    DatasetSummaryResponse,
)

LABEL_CONTRACT_VERSION = "reviewed-binary-case-outcome-v1.0.0"
SPLIT_CONTRACT_VERSION = "temporal-70-15-15-v1.0.0"
MINIMUM_ROWS = 100
MINIMUM_POSITIVE_LABELS = 20
MINIMUM_NEGATIVE_LABELS = 20
MINIMUM_TIME_SPAN_DAYS = 7

# Direct identifiers and post-decision values are deliberately absent. This allow-list is the
# operational training contract; adding or removing a field requires a new feature-set version.
TRAINING_FEATURE_NAMES = (
    "amount",
    "amount_to_median_ratio_30d",
    "channel",
    "currency",
    "destination_country",
    "is_cross_border",
    "is_off_hours_utc",
    "is_weekend_utc",
    "merchant_category_code",
    "merchant_seen_before_30d",
    "occurred_day_of_week_utc",
    "occurred_hour_utc",
    "prior_same_currency_count_30d",
    "prior_same_currency_median_amount_30d",
    "prior_transaction_count_1h",
    "prior_transaction_count_24h",
    "prior_transaction_count_30d",
    "source_country",
)


class DatasetNotFound(LookupError):
    pass


class DatasetNoEligibleLabels(ValueError):
    pass


class ReadinessGate(TypedDict):
    gate: str
    passed: bool
    observed: object
    required: str
    detail: str


@dataclass(frozen=True)
class EligibleSource:
    case: AnalystCase
    transaction: Transaction
    snapshot: TransactionFeatureSnapshot
    outcome: CaseOutcome
    review: CaseOutcomeReview
    label: int
    features: dict[str, object]


@dataclass(frozen=True)
class ReadinessEvidence:
    cutoff_at: datetime
    sources: list[EligibleSource]
    integrity_failures: int
    feature_contract_mismatches: int
    temporal_leakage: int
    gates: list[ReadinessGate]

    @property
    def status(self) -> DatasetReadinessStatus:
        return (
            DatasetReadinessStatus.READY
            if all(bool(gate["passed"]) for gate in self.gates)
            else DatasetReadinessStatus.BLOCKED
        )


def build_dataset_readiness(
    db: Session,
    cutoff_at: datetime | None = None,
) -> ReadinessEvidence:
    cutoff = _utc_datetime(cutoff_at or datetime.now(UTC))
    candidates = db.execute(
        select(
            AnalystCase,
            Transaction,
            TransactionFeatureSnapshot,
            CaseOutcome,
            CaseOutcomeReview,
        )
        .join(Transaction, Transaction.id == AnalystCase.transaction_id)
        .join(
            TransactionFeatureSnapshot,
            TransactionFeatureSnapshot.id == AnalystCase.feature_snapshot_id,
        )
        .join(CaseOutcome, CaseOutcome.case_id == AnalystCase.id)
        .join(CaseOutcomeReview, CaseOutcomeReview.outcome_id == CaseOutcome.id)
        .where(
            CaseOutcomeReview.status == OutcomeReviewStatus.APPROVED.value,
            CaseOutcome.classification.in_(
                [
                    CaseClassification.CONFIRMED_FRAUD.value,
                    CaseClassification.LEGITIMATE.value,
                ]
            ),
            CaseOutcomeReview.created_at <= cutoff,
        )
        .order_by(Transaction.occurred_at, TransactionFeatureSnapshot.snapshot_checksum)
    ).all()

    sources: list[EligibleSource] = []
    integrity_failures = 0
    feature_contract_mismatches = 0
    temporal_leakage = 0
    for case, transaction, snapshot, outcome, review in candidates:
        if snapshot.feature_set_version != FEATURE_SET_VERSION or not all(
            name in snapshot.feature_values for name in TRAINING_FEATURE_NAMES
        ):
            feature_contract_mismatches += 1
            continue
        if _utc_datetime(snapshot.created_at) > _utc_datetime(outcome.created_at) or _utc_datetime(
            transaction.occurred_at
        ) > _utc_datetime(outcome.created_at):
            temporal_leakage += 1
            continue
        if not verify_case_integrity(db, case):
            integrity_failures += 1
            continue
        label = 1 if outcome.classification == CaseClassification.CONFIRMED_FRAUD.value else 0
        sources.append(
            EligibleSource(
                case=case,
                transaction=transaction,
                snapshot=snapshot,
                outcome=outcome,
                review=review,
                label=label,
                features={name: snapshot.feature_values[name] for name in TRAINING_FEATURE_NAMES},
            )
        )

    gates = _readiness_gates(
        sources,
        integrity_failures=integrity_failures,
        feature_contract_mismatches=feature_contract_mismatches,
        temporal_leakage=temporal_leakage,
    )
    return ReadinessEvidence(
        cutoff_at=cutoff,
        sources=sources,
        integrity_failures=integrity_failures,
        feature_contract_mismatches=feature_contract_mismatches,
        temporal_leakage=temporal_leakage,
        gates=gates,
    )


def create_dataset_snapshot(
    db: Session,
    actor: User,
    reason: str,
    cutoff_at: datetime | None = None,
) -> tuple[OperationalDatasetSnapshot, bool]:
    evidence = build_dataset_readiness(db, cutoff_at)
    if not evidence.sources:
        raise DatasetNoEligibleLabels(
            "No independently approved, integrity-verified binary labels are available."
        )

    assignments = _split_assignments(len(evidence.sources))
    manifest_facts = _source_manifest_facts(evidence.sources, evidence.gates)
    source_manifest_checksum = canonical_json_checksum(manifest_facts)
    existing = db.scalar(
        select(OperationalDatasetSnapshot).where(
            OperationalDatasetSnapshot.source_manifest_checksum == source_manifest_checksum
        )
    )
    if existing is not None:
        return existing, False

    snapshot_id = uuid4()
    created_at = datetime.now(UTC)
    split_counts = _split_counts(assignments)
    positive_count = sum(source.label for source in evidence.sources)
    dataset = OperationalDatasetSnapshot(
        id=str(snapshot_id),
        display_id=_display_id(snapshot_id),
        feature_set_version=FEATURE_SET_VERSION,
        label_contract_version=LABEL_CONTRACT_VERSION,
        split_contract_version=SPLIT_CONTRACT_VERSION,
        feature_names=list(TRAINING_FEATURE_NAMES),
        row_count=len(evidence.sources),
        positive_count=positive_count,
        negative_count=len(evidence.sources) - positive_count,
        train_count=split_counts[DatasetSplit.TRAIN.value],
        validation_count=split_counts[DatasetSplit.VALIDATION.value],
        test_count=split_counts[DatasetSplit.TEST.value],
        readiness_status=evidence.status.value,
        readiness_gates=evidence.gates,
        creation_reason=reason.strip(),
        cutoff_at=evidence.cutoff_at,
        created_by_id=actor.id,
        source_manifest_checksum=source_manifest_checksum,
        dataset_checksum="pending",
        created_at=created_at,
    )

    rows: list[OperationalDatasetRow] = []
    paired_sources = zip(evidence.sources, assignments, strict=True)
    for index, (source, split) in enumerate(paired_sources, start=1):
        row_facts = _row_facts(
            source_manifest_checksum=source_manifest_checksum,
            row_index=index,
            occurred_at=source.transaction.occurred_at,
            split=split,
            label=source.label,
            feature_values=source.features,
            feature_snapshot_checksum=source.snapshot.snapshot_checksum,
            outcome_checksum=source.outcome.outcome_checksum,
            review_checksum=source.review.review_checksum,
        )
        rows.append(
            OperationalDatasetRow(
                dataset_id=dataset.id,
                row_index=index,
                case_id=source.case.id,
                feature_snapshot_id=source.snapshot.id,
                outcome_id=source.outcome.id,
                review_id=source.review.id,
                occurred_at=_utc_datetime(source.transaction.occurred_at),
                split=split,
                label=source.label,
                feature_values=source.features,
                feature_snapshot_checksum=source.snapshot.snapshot_checksum,
                outcome_checksum=source.outcome.outcome_checksum,
                review_checksum=source.review.review_checksum,
                row_checksum=canonical_json_checksum(row_facts),
            )
        )

    dataset.dataset_checksum = canonical_json_checksum(_dataset_facts(dataset, rows))
    db.add(dataset)
    db.add_all(rows)
    db.flush()
    return dataset, True


def list_dataset_snapshots(db: Session) -> list[OperationalDatasetSnapshot]:
    return list(
        db.scalars(
            select(OperationalDatasetSnapshot).order_by(
                OperationalDatasetSnapshot.created_at.desc()
            )
        ).all()
    )


def get_dataset(db: Session, dataset_id: str) -> OperationalDatasetSnapshot:
    dataset = db.scalar(
        select(OperationalDatasetSnapshot).where(
            (OperationalDatasetSnapshot.id == dataset_id)
            | (OperationalDatasetSnapshot.display_id == dataset_id)
        )
    )
    if dataset is None:
        raise DatasetNotFound("Operational dataset snapshot not found.")
    return dataset


def verify_dataset_integrity(db: Session, dataset: OperationalDatasetSnapshot) -> bool:
    rows = _dataset_rows(db, dataset.id)
    if len(rows) != dataset.row_count:
        return False
    if [row.row_index for row in rows] != list(range(1, dataset.row_count + 1)):
        return False
    if [row.split for row in rows] != _split_assignments(dataset.row_count):
        return False

    included_sources: list[dict[str, object]] = []
    for row in rows:
        case = db.get(AnalystCase, row.case_id)
        snapshot = db.get(TransactionFeatureSnapshot, row.feature_snapshot_id)
        outcome = db.get(CaseOutcome, row.outcome_id)
        review = db.get(CaseOutcomeReview, row.review_id)
        transaction = db.get(Transaction, case.transaction_id) if case is not None else None
        expected_label = (
            1
            if outcome is not None
            and outcome.classification == CaseClassification.CONFIRMED_FRAUD.value
            else 0
        )
        if (
            case is None
            or snapshot is None
            or outcome is None
            or review is None
            or transaction is None
            or case.feature_snapshot_id != snapshot.id
            or outcome.case_id != case.id
            or review.outcome_id != outcome.id
            or snapshot.snapshot_checksum != row.feature_snapshot_checksum
            or outcome.outcome_checksum != row.outcome_checksum
            or review.review_checksum != row.review_checksum
            or review.status != OutcomeReviewStatus.APPROVED.value
            or outcome.classification
            not in {
                CaseClassification.CONFIRMED_FRAUD.value,
                CaseClassification.LEGITIMATE.value,
            }
            or row.label != expected_label
            or _utc_datetime(row.occurred_at) != _utc_datetime(transaction.occurred_at)
            or _utc_datetime(snapshot.created_at) > _utc_datetime(outcome.created_at)
            or _utc_datetime(transaction.occurred_at) > _utc_datetime(outcome.created_at)
            or _utc_datetime(review.created_at) > _utc_datetime(dataset.cutoff_at)
            or not verify_case_integrity(db, case)
        ):
            return False
        expected_features = {
            name: snapshot.feature_values.get(name) for name in TRAINING_FEATURE_NAMES
        }
        if row.feature_values != expected_features:
            return False
        expected_row_checksum = canonical_json_checksum(
            _row_facts(
                source_manifest_checksum=dataset.source_manifest_checksum,
                row_index=row.row_index,
                occurred_at=row.occurred_at,
                split=row.split,
                label=row.label,
                feature_values=row.feature_values,
                feature_snapshot_checksum=row.feature_snapshot_checksum,
                outcome_checksum=row.outcome_checksum,
                review_checksum=row.review_checksum,
            )
        )
        if row.row_checksum != expected_row_checksum:
            return False
        included_sources.append(
            _included_source_facts(
                feature_snapshot_checksum=row.feature_snapshot_checksum,
                outcome_checksum=row.outcome_checksum,
                review_checksum=row.review_checksum,
                label=row.label,
            )
        )

    expected_manifest = canonical_json_checksum(
        {
            "feature_set_version": FEATURE_SET_VERSION,
            "feature_names": list(TRAINING_FEATURE_NAMES),
            "label_contract_version": LABEL_CONTRACT_VERSION,
            "sources": included_sources,
            "readiness_gates": dataset.readiness_gates,
        }
    )
    return (
        dataset.feature_set_version == FEATURE_SET_VERSION
        and dataset.feature_names == list(TRAINING_FEATURE_NAMES)
        and dataset.label_contract_version == LABEL_CONTRACT_VERSION
        and dataset.split_contract_version == SPLIT_CONTRACT_VERSION
        and dataset.source_manifest_checksum == expected_manifest
        and dataset.dataset_checksum == canonical_json_checksum(_dataset_facts(dataset, rows))
        and dataset.positive_count == sum(row.label for row in rows)
        and dataset.negative_count == sum(1 - row.label for row in rows)
        and dataset.train_count == sum(row.split == DatasetSplit.TRAIN.value for row in rows)
        and dataset.validation_count
        == sum(row.split == DatasetSplit.VALIDATION.value for row in rows)
        and dataset.test_count == sum(row.split == DatasetSplit.TEST.value for row in rows)
    )


def build_dataset_readiness_response(
    db: Session,
    cutoff_at: datetime | None = None,
) -> DatasetReadinessResponse:
    evidence = build_dataset_readiness(db, cutoff_at)
    positives = sum(source.label for source in evidence.sources)
    return DatasetReadinessResponse(
        cutoff_at=evidence.cutoff_at,
        eligible_label_count=len(evidence.sources),
        positive_label_count=positives,
        negative_label_count=len(evidence.sources) - positives,
        excluded_integrity_failures=evidence.integrity_failures,
        excluded_feature_contract_mismatches=evidence.feature_contract_mismatches,
        excluded_temporal_leakage=evidence.temporal_leakage,
        feature_set_version=FEATURE_SET_VERSION,
        label_contract_version=LABEL_CONTRACT_VERSION,
        readiness_status=evidence.status,
        gates=[DatasetReadinessGateResponse(**gate) for gate in evidence.gates],
    )


def build_dataset_summary_response(
    db: Session,
    dataset: OperationalDatasetSnapshot,
) -> DatasetSummaryResponse:
    creator = db.get(User, dataset.created_by_id)
    return DatasetSummaryResponse(
        id=dataset.id,
        display_id=dataset.display_id,
        feature_set_version=dataset.feature_set_version,
        label_contract_version=dataset.label_contract_version,
        split_contract_version=dataset.split_contract_version,
        feature_names=dataset.feature_names,
        row_count=dataset.row_count,
        positive_count=dataset.positive_count,
        negative_count=dataset.negative_count,
        split_counts=DatasetSplitCountsResponse(
            train=dataset.train_count,
            validation=dataset.validation_count,
            test=dataset.test_count,
        ),
        readiness_status=DatasetReadinessStatus(dataset.readiness_status),
        readiness_gates=[
            DatasetReadinessGateResponse.model_validate(gate) for gate in dataset.readiness_gates
        ],
        creation_reason=dataset.creation_reason,
        cutoff_at=_utc_datetime(dataset.cutoff_at),
        created_by=creator.username if creator is not None else "unknown",
        source_manifest_checksum=dataset.source_manifest_checksum,
        dataset_checksum=dataset.dataset_checksum,
        integrity_verified=verify_dataset_integrity(db, dataset),
        created_at=_utc_datetime(dataset.created_at),
    )


def build_dataset_detail_response(
    db: Session,
    dataset: OperationalDatasetSnapshot,
    *,
    row_limit: int = 20,
) -> DatasetDetailResponse:
    rows = _dataset_rows(db, dataset.id)
    summary = build_dataset_summary_response(db, dataset)
    return DatasetDetailResponse(
        **summary.model_dump(),
        rows=[
            DatasetRowResponse(
                row_index=row.row_index,
                occurred_at=_utc_datetime(row.occurred_at),
                split=DatasetSplit(row.split),
                label=row.label,
                feature_values=row.feature_values,
                feature_snapshot_checksum=row.feature_snapshot_checksum,
                outcome_checksum=row.outcome_checksum,
                review_checksum=row.review_checksum,
                row_checksum=row.row_checksum,
            )
            for row in rows[:row_limit]
        ],
        rows_truncated=len(rows) > row_limit,
    )


def _readiness_gates(
    sources: list[EligibleSource],
    *,
    integrity_failures: int,
    feature_contract_mismatches: int,
    temporal_leakage: int,
) -> list[ReadinessGate]:
    row_count = len(sources)
    positives = sum(source.label for source in sources)
    negatives = row_count - positives
    span_days = 0
    if len(sources) > 1:
        span = _utc_datetime(sources[-1].transaction.occurred_at) - _utc_datetime(
            sources[0].transaction.occurred_at
        )
        span_days = max(0, span.days)
    assignments = _split_assignments(row_count)
    split_labels = {
        split.value: {0: 0, 1: 0}
        for split in (DatasetSplit.TRAIN, DatasetSplit.VALIDATION, DatasetSplit.TEST)
    }
    for source, split in zip(sources, assignments, strict=True):
        split_labels[split][source.label] += 1
    holdout_passed = all(counts[0] > 0 and counts[1] > 0 for counts in split_labels.values())
    return [
        _gate(
            "verified_source_integrity",
            integrity_failures == 0,
            integrity_failures,
            "0 failures",
            "Every included or pending approved label must retain a valid case evidence chain.",
        ),
        _gate(
            "canonical_feature_contract",
            feature_contract_mismatches == 0,
            feature_contract_mismatches,
            "0 mismatches",
            "All labels must reference the current operational semantic feature contract.",
        ),
        _gate(
            "pre_decision_features_only",
            temporal_leakage == 0,
            temporal_leakage,
            "0 violations",
            "Feature snapshots must predate the analyst outcome.",
        ),
        _gate(
            "minimum_rows",
            row_count >= MINIMUM_ROWS,
            row_count,
            f">= {MINIMUM_ROWS}",
            "Small label collections cannot be represented as training-ready evidence.",
        ),
        _gate(
            "minimum_positive_labels",
            positives >= MINIMUM_POSITIVE_LABELS,
            positives,
            f">= {MINIMUM_POSITIVE_LABELS}",
            "Confirmed-fraud examples are required for supervised evaluation.",
        ),
        _gate(
            "minimum_negative_labels",
            negatives >= MINIMUM_NEGATIVE_LABELS,
            negatives,
            f">= {MINIMUM_NEGATIVE_LABELS}",
            "Legitimate examples are required to measure false-positive behavior.",
        ),
        _gate(
            "temporal_coverage",
            span_days >= MINIMUM_TIME_SPAN_DAYS,
            span_days,
            f">= {MINIMUM_TIME_SPAN_DAYS} days",
            "The source period must span enough time to support a temporal holdout.",
        ),
        _gate(
            "temporal_holdout_class_coverage",
            holdout_passed,
            {
                split: {"legitimate": counts[0], "fraud": counts[1]}
                for split, counts in split_labels.items()
            },
            "both labels in train, validation, and test",
            "Every chronological partition must contain both classes before model training.",
        ),
    ]


def _gate(
    gate: str,
    passed: bool,
    observed: object,
    required: str,
    detail: str,
) -> ReadinessGate:
    return {
        "gate": gate,
        "passed": passed,
        "observed": observed,
        "required": required,
        "detail": detail,
    }


def _split_assignments(row_count: int) -> list[str]:
    if row_count == 0:
        return []
    if row_count == 1:
        return [DatasetSplit.TRAIN.value]
    if row_count == 2:
        return [DatasetSplit.TRAIN.value, DatasetSplit.VALIDATION.value]
    train_end = max(1, int(row_count * 0.70))
    validation_end = max(train_end + 1, int(row_count * 0.85))
    validation_end = min(validation_end, row_count - 1)
    return [
        DatasetSplit.TRAIN.value
        if index < train_end
        else (DatasetSplit.VALIDATION.value if index < validation_end else DatasetSplit.TEST.value)
        for index in range(row_count)
    ]


def _split_counts(assignments: list[str]) -> dict[str, int]:
    return {
        split.value: assignments.count(split.value)
        for split in (DatasetSplit.TRAIN, DatasetSplit.VALIDATION, DatasetSplit.TEST)
    }


def _source_manifest_facts(
    sources: list[EligibleSource],
    readiness_gates: list[ReadinessGate],
) -> dict[str, object]:
    return {
        "feature_set_version": FEATURE_SET_VERSION,
        "feature_names": list(TRAINING_FEATURE_NAMES),
        "label_contract_version": LABEL_CONTRACT_VERSION,
        "sources": [
            _included_source_facts(
                feature_snapshot_checksum=source.snapshot.snapshot_checksum,
                outcome_checksum=source.outcome.outcome_checksum,
                review_checksum=source.review.review_checksum,
                label=source.label,
            )
            for source in sources
        ],
        "readiness_gates": readiness_gates,
    }


def _included_source_facts(
    *,
    feature_snapshot_checksum: str,
    outcome_checksum: str,
    review_checksum: str,
    label: int,
) -> dict[str, object]:
    return {
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "outcome_checksum": outcome_checksum,
        "review_checksum": review_checksum,
        "label": label,
    }


def _row_facts(
    *,
    source_manifest_checksum: str,
    row_index: int,
    occurred_at: datetime,
    split: str,
    label: int,
    feature_values: dict[str, object],
    feature_snapshot_checksum: str,
    outcome_checksum: str,
    review_checksum: str,
) -> dict[str, object]:
    return {
        "source_manifest_checksum": source_manifest_checksum,
        "row_index": row_index,
        "occurred_at": _timestamp_text(occurred_at),
        "split": split,
        "label": label,
        "feature_values": feature_values,
        "feature_snapshot_checksum": feature_snapshot_checksum,
        "outcome_checksum": outcome_checksum,
        "review_checksum": review_checksum,
    }


def _dataset_facts(
    dataset: OperationalDatasetSnapshot,
    rows: list[OperationalDatasetRow],
) -> dict[str, Any]:
    return {
        "feature_set_version": dataset.feature_set_version,
        "label_contract_version": dataset.label_contract_version,
        "split_contract_version": dataset.split_contract_version,
        "feature_names": dataset.feature_names,
        "row_count": dataset.row_count,
        "positive_count": dataset.positive_count,
        "negative_count": dataset.negative_count,
        "split_counts": {
            "train": dataset.train_count,
            "validation": dataset.validation_count,
            "test": dataset.test_count,
        },
        "readiness_status": dataset.readiness_status,
        "readiness_gates": dataset.readiness_gates,
        "source_manifest_checksum": dataset.source_manifest_checksum,
        "row_checksums": [row.row_checksum for row in rows],
    }


def _dataset_rows(db: Session, dataset_id: str) -> list[OperationalDatasetRow]:
    return list(
        db.scalars(
            select(OperationalDatasetRow)
            .where(OperationalDatasetRow.dataset_id == dataset_id)
            .order_by(OperationalDatasetRow.row_index)
        ).all()
    )


def _display_id(value: UUID) -> str:
    return f"ODS-{value.hex[:10].upper()}"


def _timestamp_text(value: datetime) -> str:
    return _utc_datetime(value).isoformat()


def _utc_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
