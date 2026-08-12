from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from fip_api.benchmarking.generator import (
    GENERATOR_VERSION,
    SyntheticBenchmarkDataset,
    generate_synthetic_benchmark,
    synthetic_transaction_set_checksum,
)
from fip_api.core.checksums import canonical_json_checksum
from fip_api.models import (
    AnalystCase,
    BenchmarkRunStatus,
    IngestionBatch,
    IngestionSourceType,
    ScoringRuntimeObservation,
    SyntheticBenchmarkRun,
    SyntheticBenchmarkRunEvent,
    Transaction,
    TransactionFeatureSnapshot,
    TransactionRuleAssessment,
    User,
)
from fip_api.schemas.benchmark import (
    BenchmarkResultResponse,
    BenchmarkRunCreate,
    BenchmarkRunEventResponse,
    BenchmarkRunResponse,
)
from fip_api.schemas.transaction import TransactionCreate
from fip_api.scoring import verify_scoring_runtime_observation_components

BENCHMARK_REPORT_SCHEMA_VERSION = "synthetic-system-benchmark-v1.0.0"
BENCHMARK_VOLUME_TARGET = 10_000
SCORING_LATENCY_TARGET_MILLISECONDS = 2_000


class BenchmarkRunNotFound(LookupError):
    pass


class BenchmarkRunConflict(ValueError):
    pass


class BenchmarkRunStateError(ValueError):
    pass


def request_benchmark_run(
    db: Session,
    *,
    payload: BenchmarkRunCreate,
    actor: User,
) -> tuple[SyntheticBenchmarkRun, bool]:
    configuration_checksum = canonical_json_checksum(
        _configuration_facts(payload.transaction_count, payload.seed)
    )
    existing = db.scalar(
        select(SyntheticBenchmarkRun).where(
            SyntheticBenchmarkRun.configuration_checksum == configuration_checksum
        )
    )
    if existing is not None:
        return existing, False

    dataset = generate_synthetic_benchmark(
        transaction_count=payload.transaction_count,
        seed=payload.seed,
        configuration_checksum=configuration_checksum,
    )
    run_id = uuid4()
    created_at = datetime.now(UTC)
    run = SyntheticBenchmarkRun(
        id=str(run_id),
        display_id=f"BMK-{run_id.hex[:10].upper()}",
        requested_by_id=actor.id,
        transaction_count=payload.transaction_count,
        seed=payload.seed,
        request_reason=payload.reason,
        generator_version=GENERATOR_VERSION,
        configuration_checksum=configuration_checksum,
        dataset_checksum=dataset.checksum,
        profile_distribution=dataset.profile_distribution,
        status=BenchmarkRunStatus.QUEUED.value,
        attempt_count=0,
        created_at=created_at,
    )
    db.add(run)
    db.flush()
    _append_event(
        db,
        run=run,
        from_status=None,
        to_status=BenchmarkRunStatus.QUEUED,
        detail="Administrator queued a fixed-seed synthetic system benchmark.",
        actor_username=actor.username,
        created_at=created_at,
    )
    db.flush()
    return run, True


def list_benchmark_runs(db: Session) -> list[SyntheticBenchmarkRun]:
    return list(
        db.scalars(
            select(SyntheticBenchmarkRun).order_by(
                SyntheticBenchmarkRun.created_at.desc(),
                SyntheticBenchmarkRun.id,
            )
        ).all()
    )


def get_benchmark_run(db: Session, run_id: str) -> SyntheticBenchmarkRun:
    run = db.scalar(
        select(SyntheticBenchmarkRun).where(
            or_(
                SyntheticBenchmarkRun.id == run_id,
                SyntheticBenchmarkRun.display_id == run_id,
            )
        )
    )
    if run is None:
        raise BenchmarkRunNotFound("Synthetic benchmark run not found.")
    return run


def retry_benchmark_run(
    db: Session,
    *,
    run_id: str,
    actor: User,
) -> SyntheticBenchmarkRun:
    run = db.scalar(
        select(SyntheticBenchmarkRun)
        .where(
            or_(
                SyntheticBenchmarkRun.id == run_id,
                SyntheticBenchmarkRun.display_id == run_id,
            )
        )
        .with_for_update()
    )
    if run is None:
        raise BenchmarkRunNotFound("Synthetic benchmark run not found.")
    if run.status != BenchmarkRunStatus.FAILED.value:
        raise BenchmarkRunConflict("Only a failed benchmark run may be queued again.")
    if not _generator_lineage_matches(run):
        raise BenchmarkRunConflict("The pinned synthetic generator contract no longer reproduces.")
    now = datetime.now(UTC)
    run.status = BenchmarkRunStatus.QUEUED.value
    run.worker_id = None
    run.lease_expires_at = None
    run.started_at = None
    run.completed_at = None
    run.error_code = None
    run.error_message = None
    _append_event(
        db,
        run=run,
        from_status=BenchmarkRunStatus.FAILED,
        to_status=BenchmarkRunStatus.QUEUED,
        detail="Administrator authorized another attempt for the same synthetic configuration.",
        actor_username=actor.username,
        created_at=now,
    )
    db.flush()
    return run


def claim_next_benchmark_run(
    db: Session,
    *,
    worker_id: str,
    lease_minutes: int,
) -> SyntheticBenchmarkRun | None:
    now = datetime.now(UTC)
    expired = list(
        db.scalars(
            select(SyntheticBenchmarkRun)
            .where(
                SyntheticBenchmarkRun.status == BenchmarkRunStatus.RUNNING.value,
                SyntheticBenchmarkRun.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    for abandoned in expired:
        _transition_to_failed(
            db,
            run=abandoned,
            error_code="worker_lease_expired",
            error_message="The benchmark worker lease expired before completion.",
            completed_at=now,
        )

    run = db.scalar(
        select(SyntheticBenchmarkRun)
        .where(SyntheticBenchmarkRun.status == BenchmarkRunStatus.QUEUED.value)
        .order_by(SyntheticBenchmarkRun.created_at, SyntheticBenchmarkRun.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    run.status = BenchmarkRunStatus.RUNNING.value
    run.worker_id = worker_id[:120]
    run.attempt_count += 1
    run.started_at = now
    run.completed_at = None
    run.lease_expires_at = now + timedelta(minutes=lease_minutes)
    run.error_code = None
    run.error_message = None
    _append_event(
        db,
        run=run,
        from_status=BenchmarkRunStatus.QUEUED,
        to_status=BenchmarkRunStatus.RUNNING,
        detail=f"Worker {run.worker_id} claimed the synthetic benchmark.",
        actor_username="benchmark-worker",
        created_at=now,
    )
    db.flush()
    return run


def complete_benchmark_run(
    db: Session,
    *,
    run_id: str,
    worker_id: str,
    ingestion_batch_id: str,
    result: dict[str, object],
) -> SyntheticBenchmarkRun:
    run = db.scalar(
        select(SyntheticBenchmarkRun).where(SyntheticBenchmarkRun.id == run_id).with_for_update()
    )
    if run is None:
        raise BenchmarkRunNotFound("Synthetic benchmark run not found.")
    _require_worker_ownership(run, worker_id)
    BenchmarkResultResponse.model_validate(result)
    completed_at = datetime.now(UTC)
    run.status = BenchmarkRunStatus.SUCCEEDED.value
    run.worker_id = None
    run.ingestion_batch_id = ingestion_batch_id
    run.result_summary = result
    run.report_checksum = canonical_json_checksum(_report_facts(run, result))
    run.completed_at = completed_at
    run.lease_expires_at = None
    _append_event(
        db,
        run=run,
        from_status=BenchmarkRunStatus.RUNNING,
        to_status=BenchmarkRunStatus.SUCCEEDED,
        detail="Synthetic transactions completed validation, scoring, and case routing.",
        actor_username="benchmark-worker",
        created_at=completed_at,
    )
    db.flush()
    return run


def fail_benchmark_run(
    db: Session,
    *,
    run_id: str,
    worker_id: str,
    error_code: str,
    error_message: str,
) -> SyntheticBenchmarkRun:
    run = db.scalar(
        select(SyntheticBenchmarkRun).where(SyntheticBenchmarkRun.id == run_id).with_for_update()
    )
    if run is None:
        raise BenchmarkRunNotFound("Synthetic benchmark run not found.")
    _require_worker_ownership(run, worker_id)
    _transition_to_failed(
        db,
        run=run,
        error_code=error_code,
        error_message=error_message,
        completed_at=datetime.now(UTC),
    )
    db.flush()
    return run


def build_benchmark_result(
    db: Session,
    batch: IngestionBatch,
    *,
    elapsed_milliseconds: int | None,
) -> dict[str, object]:
    transactions = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.ingestion_batch_id == batch.id)
            .order_by(Transaction.external_transaction_id)
        ).all()
    )
    assessment_rows = db.execute(
        select(TransactionRuleAssessment, Transaction)
        .join(Transaction, Transaction.id == TransactionRuleAssessment.transaction_id)
        .where(Transaction.ingestion_batch_id == batch.id)
        .order_by(Transaction.external_transaction_id)
    ).all()
    observation_rows = db.execute(
        select(
            ScoringRuntimeObservation,
            Transaction,
            TransactionFeatureSnapshot,
            TransactionRuleAssessment,
        )
        .join(Transaction, Transaction.id == ScoringRuntimeObservation.transaction_id)
        .join(
            TransactionFeatureSnapshot,
            TransactionFeatureSnapshot.id == ScoringRuntimeObservation.feature_snapshot_id,
        )
        .join(
            TransactionRuleAssessment,
            TransactionRuleAssessment.id == ScoringRuntimeObservation.rule_assessment_id,
        )
        .where(Transaction.ingestion_batch_id == batch.id)
        .order_by(Transaction.external_transaction_id)
    ).all()
    case_rows = db.execute(
        select(AnalystCase, Transaction)
        .join(Transaction, Transaction.id == AnalystCase.transaction_id)
        .where(Transaction.ingestion_batch_id == batch.id)
        .order_by(Transaction.external_transaction_id)
    ).all()

    verified_observations = [
        observation
        for observation, transaction, snapshot, assessment in observation_rows
        if verify_scoring_runtime_observation_components(
            observation,
            transaction,
            snapshot,
            assessment,
        )
    ]
    latencies = [observation.runtime_milliseconds for observation in verified_observations]
    risk_counts = Counter(assessment.risk_level for assessment, _ in assessment_rows)
    processed_count = len(transactions)
    assessment_count = len(assessment_rows)
    verified_count = len(verified_observations)
    pipeline_complete = processed_count == batch.row_count == assessment_count == verified_count
    maximum_latency = max(latencies, default=None)
    volume_target_met = processed_count >= BENCHMARK_VOLUME_TARGET and pipeline_complete
    latency_target_met = (
        pipeline_complete
        and maximum_latency is not None
        and maximum_latency < SCORING_LATENCY_TARGET_MILLISECONDS
    )
    throughput = (
        _decimal_text(Decimal(processed_count * 1_000) / Decimal(elapsed_milliseconds))
        if elapsed_milliseconds is not None and elapsed_milliseconds > 0
        else None
    )
    result: dict[str, object] = {
        "processed_transaction_count": processed_count,
        "rule_assessment_count": assessment_count,
        "verified_runtime_observation_count": verified_count,
        "risk_distribution": {risk: risk_counts.get(risk, 0) for risk in ("low", "medium", "high")},
        "opened_case_count": len(case_rows),
        "mean_scoring_milliseconds": _mean_text(latencies),
        "p95_scoring_milliseconds": _p95_text(latencies),
        "maximum_scoring_milliseconds": maximum_latency,
        "under_latency_target_count": sum(
            value < SCORING_LATENCY_TARGET_MILLISECONDS for value in latencies
        ),
        "elapsed_milliseconds": elapsed_milliseconds,
        "throughput_per_second": throughput,
        "transaction_set_checksum": synthetic_transaction_set_checksum(
            [
                TransactionCreate.model_validate(
                    {
                        "external_transaction_id": transaction.external_transaction_id,
                        "occurred_at": _timestamp_text(transaction.occurred_at),
                        "amount": transaction.amount,
                        "currency": transaction.currency,
                        "account_reference": transaction.account_reference,
                        "merchant_reference": transaction.merchant_reference,
                        "merchant_category_code": transaction.merchant_category_code,
                        "channel": transaction.channel,
                        "source_country": transaction.source_country,
                        "destination_country": transaction.destination_country,
                    }
                )
                for transaction in transactions
            ]
        ),
        "assessment_set_checksum": canonical_json_checksum(
            [
                {
                    "external_transaction_id": transaction.external_transaction_id,
                    "assessment_checksum": assessment.assessment_checksum,
                    "risk_level": assessment.risk_level,
                    "rule_score": assessment.rule_score,
                }
                for assessment, transaction in assessment_rows
            ]
        ),
        "runtime_set_checksum": canonical_json_checksum(
            [
                {
                    "external_transaction_id": transaction.external_transaction_id,
                    "observation_checksum": observation.observation_checksum,
                    "runtime_milliseconds": observation.runtime_milliseconds,
                }
                for observation, transaction, _, _ in observation_rows
            ]
        ),
        "case_set_checksum": canonical_json_checksum(
            [
                {
                    "external_transaction_id": transaction.external_transaction_id,
                    "opening_checksum": case.opening_checksum,
                }
                for case, transaction in case_rows
            ]
        ),
        "volume_target_met": volume_target_met,
        "latency_target_met": latency_target_met,
        "pipeline_complete": pipeline_complete,
        "acceptance_met": volume_target_met and latency_target_met,
    }
    BenchmarkResultResponse.model_validate(result)
    return result


def build_benchmark_run_response(
    db: Session,
    run: SyntheticBenchmarkRun,
) -> BenchmarkRunResponse:
    requester = db.get(User, run.requested_by_id)
    if requester is None:
        raise BenchmarkRunStateError("The benchmark run references a missing requester.")
    batch = db.get(IngestionBatch, run.ingestion_batch_id) if run.ingestion_batch_id else None
    events = _events(db, run.id)
    integrity_verified = verify_benchmark_run_integrity(
        db,
        run,
        requester=requester,
        batch=batch,
        events=events,
    )
    result = (
        BenchmarkResultResponse.model_validate(run.result_summary)
        if integrity_verified and run.result_summary is not None
        else None
    )
    return BenchmarkRunResponse(
        id=run.id,
        display_id=run.display_id,
        requested_by=requester.username,
        transaction_count=run.transaction_count,
        seed=run.seed,
        reason=run.request_reason,
        generator_version=run.generator_version,
        configuration_checksum=run.configuration_checksum,
        dataset_checksum=run.dataset_checksum,
        profile_distribution=run.profile_distribution,
        status=BenchmarkRunStatus(run.status),
        attempt_count=run.attempt_count,
        ingestion_batch_id=batch.id if batch is not None else None,
        ingestion_batch_display_id=batch.display_id if batch is not None else None,
        result=result,
        report_checksum=run.report_checksum,
        error_code=run.error_code,
        error_message=run.error_message,
        integrity_verified=integrity_verified,
        events=[
            BenchmarkRunEventResponse(
                sequence_number=event.sequence_number,
                from_status=(
                    BenchmarkRunStatus(event.from_status) if event.from_status is not None else None
                ),
                to_status=BenchmarkRunStatus(event.to_status),
                detail=event.detail,
                actor_username=event.actor_username,
                previous_event_checksum=event.previous_event_checksum,
                event_checksum=event.event_checksum,
                created_at=event.created_at,
            )
            for event in events
        ],
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


def verify_benchmark_run_integrity(
    db: Session,
    run: SyntheticBenchmarkRun,
    *,
    requester: User | None = None,
    batch: IngestionBatch | None = None,
    events: list[SyntheticBenchmarkRunEvent] | None = None,
) -> bool:
    requester = requester or db.get(User, run.requested_by_id)
    events = events if events is not None else _events(db, run.id)
    reproduced_dataset = _reproduce_run_dataset(run)
    if requester is None or reproduced_dataset is None or not _verify_event_chain(run, events):
        return False
    status = BenchmarkRunStatus(run.status)
    if status is BenchmarkRunStatus.SUCCEEDED:
        summary = run.result_summary
        ingestion_batch_id = run.ingestion_batch_id
        if (
            ingestion_batch_id is None
            or summary is None
            or run.report_checksum is None
            or run.completed_at is None
        ):
            return False
        batch = batch or db.get(IngestionBatch, ingestion_batch_id)
        if (
            batch is None
            or batch.source_type != IngestionSourceType.SYNTHETIC.value
            or batch.source_checksum != run.dataset_checksum
            or batch.row_count != run.transaction_count
            or batch.imported_by_id != run.requested_by_id
        ):
            return False
        elapsed = summary.get("elapsed_milliseconds")
        if elapsed is not None and not isinstance(elapsed, int):
            return False
        expected_result = build_benchmark_result(
            db,
            batch,
            elapsed_milliseconds=elapsed,
        )
        return (
            expected_result == summary
            and expected_result["transaction_set_checksum"]
            == reproduced_dataset.transaction_set_checksum
            and run.report_checksum == canonical_json_checksum(_report_facts(run, expected_result))
            and run.error_code is None
            and run.error_message is None
        )
    if status is BenchmarkRunStatus.FAILED:
        return (
            run.completed_at is not None
            and run.error_code is not None
            and run.error_message is not None
            and run.ingestion_batch_id is None
            and run.result_summary is None
            and run.report_checksum is None
        )
    return (
        run.ingestion_batch_id is None
        and run.result_summary is None
        and run.report_checksum is None
        and run.completed_at is None
    )


def benchmark_report_facts(run: SyntheticBenchmarkRun) -> dict[str, object]:
    if run.result_summary is None or run.report_checksum is None:
        raise BenchmarkRunConflict("A sealed benchmark report is not available for this run.")
    return {
        "schema_version": BENCHMARK_REPORT_SCHEMA_VERSION,
        "run_id": run.id,
        "display_id": run.display_id,
        "generator_version": run.generator_version,
        "configuration_checksum": run.configuration_checksum,
        "dataset_checksum": run.dataset_checksum,
        "transaction_count": run.transaction_count,
        "seed": run.seed,
        "profile_distribution": run.profile_distribution,
        "result": run.result_summary,
        "report_checksum": run.report_checksum,
        "synthetic_only": True,
        "eligible_for_operational_training": False,
        "model_efficacy_claim": False,
        "changes_operational_configuration": False,
    }


def _generator_lineage_matches(run: SyntheticBenchmarkRun) -> bool:
    return _reproduce_run_dataset(run) is not None


def _reproduce_run_dataset(
    run: SyntheticBenchmarkRun,
) -> SyntheticBenchmarkDataset | None:
    expected_configuration = canonical_json_checksum(
        _configuration_facts(run.transaction_count, run.seed)
    )
    if (
        run.generator_version != GENERATOR_VERSION
        or run.configuration_checksum != expected_configuration
    ):
        return None
    dataset = generate_synthetic_benchmark(
        transaction_count=run.transaction_count,
        seed=run.seed,
        configuration_checksum=run.configuration_checksum,
    )
    return (
        dataset
        if (
            dataset.checksum == run.dataset_checksum
            and dataset.profile_distribution == run.profile_distribution
        )
        else None
    )


def _transition_to_failed(
    db: Session,
    *,
    run: SyntheticBenchmarkRun,
    error_code: str,
    error_message: str,
    completed_at: datetime,
) -> None:
    previous = BenchmarkRunStatus(run.status)
    run.status = BenchmarkRunStatus.FAILED.value
    run.worker_id = None
    run.lease_expires_at = None
    run.ingestion_batch_id = None
    run.result_summary = None
    run.report_checksum = None
    run.error_code = error_code[:120]
    run.error_message = error_message[:500]
    run.completed_at = completed_at
    _append_event(
        db,
        run=run,
        from_status=previous,
        to_status=BenchmarkRunStatus.FAILED,
        detail=run.error_message,
        actor_username="benchmark-worker",
        created_at=completed_at,
    )


def _require_worker_ownership(run: SyntheticBenchmarkRun, worker_id: str) -> None:
    if run.status != BenchmarkRunStatus.RUNNING.value or run.worker_id != worker_id[:120]:
        raise BenchmarkRunStateError("The worker no longer owns this benchmark run.")


def _events(db: Session, run_id: str) -> list[SyntheticBenchmarkRunEvent]:
    return list(
        db.scalars(
            select(SyntheticBenchmarkRunEvent)
            .where(SyntheticBenchmarkRunEvent.benchmark_run_id == run_id)
            .order_by(SyntheticBenchmarkRunEvent.sequence_number)
        ).all()
    )


def _append_event(
    db: Session,
    *,
    run: SyntheticBenchmarkRun,
    from_status: BenchmarkRunStatus | None,
    to_status: BenchmarkRunStatus,
    detail: str,
    actor_username: str,
    created_at: datetime,
) -> None:
    previous = db.scalar(
        select(SyntheticBenchmarkRunEvent)
        .where(SyntheticBenchmarkRunEvent.benchmark_run_id == run.id)
        .order_by(SyntheticBenchmarkRunEvent.sequence_number.desc())
        .limit(1)
    )
    sequence_number = previous.sequence_number + 1 if previous is not None else 1
    previous_checksum = previous.event_checksum if previous is not None else None
    facts = _event_facts(
        run.id,
        sequence_number,
        from_status.value if from_status is not None else None,
        to_status.value,
        detail,
        actor_username,
        previous_checksum,
        created_at,
    )
    db.add(
        SyntheticBenchmarkRunEvent(
            benchmark_run_id=run.id,
            sequence_number=sequence_number,
            from_status=from_status.value if from_status is not None else None,
            to_status=to_status.value,
            detail=detail,
            actor_username=actor_username,
            previous_event_checksum=previous_checksum,
            event_checksum=canonical_json_checksum(facts),
            created_at=created_at,
        )
    )


def _verify_event_chain(
    run: SyntheticBenchmarkRun,
    events: list[SyntheticBenchmarkRunEvent],
) -> bool:
    if not events or events[-1].to_status != run.status:
        return False
    allowed = {
        (None, BenchmarkRunStatus.QUEUED.value),
        (BenchmarkRunStatus.QUEUED.value, BenchmarkRunStatus.RUNNING.value),
        (BenchmarkRunStatus.RUNNING.value, BenchmarkRunStatus.SUCCEEDED.value),
        (BenchmarkRunStatus.RUNNING.value, BenchmarkRunStatus.FAILED.value),
        (BenchmarkRunStatus.FAILED.value, BenchmarkRunStatus.QUEUED.value),
    }
    previous_checksum: str | None = None
    previous_status: str | None = None
    for sequence_number, event in enumerate(events, start=1):
        expected = canonical_json_checksum(
            _event_facts(
                run.id,
                event.sequence_number,
                event.from_status,
                event.to_status,
                event.detail,
                event.actor_username,
                event.previous_event_checksum,
                event.created_at,
            )
        )
        if (
            event.sequence_number != sequence_number
            or event.from_status != previous_status
            or event.previous_event_checksum != previous_checksum
            or (event.from_status, event.to_status) not in allowed
            or event.event_checksum != expected
        ):
            return False
        previous_status = event.to_status
        previous_checksum = event.event_checksum
    return True


def _configuration_facts(transaction_count: int, seed: int) -> dict[str, object]:
    return {
        "generator_version": GENERATOR_VERSION,
        "transaction_count": transaction_count,
        "seed": seed,
        "synthetic_only": True,
        "eligible_for_operational_training": False,
        "model_efficacy_claim": False,
    }


def _report_facts(
    run: SyntheticBenchmarkRun,
    result: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": BENCHMARK_REPORT_SCHEMA_VERSION,
        "run_id": run.id,
        "requested_by_id": run.requested_by_id,
        "generator_version": run.generator_version,
        "configuration_checksum": run.configuration_checksum,
        "dataset_checksum": run.dataset_checksum,
        "profile_distribution": run.profile_distribution,
        "result": result,
        "synthetic_only": True,
        "eligible_for_operational_training": False,
        "model_efficacy_claim": False,
    }


def _event_facts(
    run_id: str,
    sequence_number: int,
    from_status: str | None,
    to_status: str,
    detail: str,
    actor_username: str,
    previous_event_checksum: str | None,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "benchmark_run_id": run_id,
        "sequence_number": sequence_number,
        "from_status": from_status,
        "to_status": to_status,
        "detail": detail,
        "actor_username": actor_username,
        "previous_event_checksum": previous_event_checksum,
        "created_at": _timestamp_text(created_at),
    }


def _mean_text(values: list[int]) -> str | None:
    if not values:
        return None
    return _decimal_text(Decimal(sum(values)) / Decimal(len(values)))


def _p95_text(values: list[int]) -> str | None:
    if not values:
        return None
    ordered = sorted(values)
    position = Decimal(len(ordered) - 1) * Decimal("0.95")
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    value = Decimal(ordered[lower_index]) + (
        Decimal(ordered[upper_index] - ordered[lower_index]) * fraction
    )
    return _decimal_text(value)


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.001")), "f")


def _timestamp_text(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat()
