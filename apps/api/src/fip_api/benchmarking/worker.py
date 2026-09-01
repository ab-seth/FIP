from __future__ import annotations

import argparse
import logging
import os
import socket
from collections.abc import Callable, Sequence
from time import perf_counter_ns, sleep
from uuid import uuid4

from sqlalchemy.orm import Session

from fip_api.benchmarking.generator import generate_synthetic_benchmark
from fip_api.benchmarking.service import (
    BenchmarkRunStateError,
    build_benchmark_result,
    claim_next_benchmark_run,
    complete_benchmark_run,
    fail_benchmark_run,
)
from fip_api.core.config import get_settings
from fip_api.db.session import SessionLocal
from fip_api.ingestion.csv_parser import parse_csv_upload
from fip_api.ingestion.service import create_synthetic_ingestion, find_batch_by_checksum
from fip_api.models import IngestionBatch, IngestionSourceType, SyntheticBenchmarkRun, User

LOGGER = logging.getLogger("fip.benchmark-worker")
SessionFactory = Callable[[], Session]


def process_next_benchmark_run(
    *,
    session_factory: SessionFactory = SessionLocal,
    worker_id: str | None = None,
    lease_minutes: int | None = None,
) -> bool:
    settings = get_settings()
    identity = worker_id or _worker_id()
    lease = lease_minutes or settings.benchmark_worker_lease_minutes

    with session_factory() as db:
        run = claim_next_benchmark_run(db, worker_id=identity, lease_minutes=lease)
        if run is None:
            db.commit()
            return False
        run_id = run.id
        db.commit()

    try:
        with session_factory() as db:
            run = db.get(SyntheticBenchmarkRun, run_id)
            if run is None:
                raise BenchmarkRunStateError("The claimed benchmark run no longer exists.")
            batch, elapsed_milliseconds = _execute_benchmark(db, run)
            result = build_benchmark_result(
                db,
                batch,
                elapsed_milliseconds=elapsed_milliseconds,
            )
            complete_benchmark_run(
                db,
                run_id=run.id,
                worker_id=identity,
                ingestion_batch_id=batch.id,
                result=result,
            )
            db.commit()
        LOGGER.info("synthetic benchmark %s completed", run_id)
    except Exception as exc:
        error_code, error_message = _safe_failure(exc)
        with session_factory() as db:
            try:
                fail_benchmark_run(
                    db,
                    run_id=run_id,
                    worker_id=identity,
                    error_code=error_code,
                    error_message=error_message,
                )
                db.commit()
            except Exception:
                db.rollback()
                LOGGER.exception("could not record failure for benchmark run %s", run_id)
        LOGGER.exception("synthetic benchmark %s failed: %s", run_id, error_code)
    return True


def _execute_benchmark(
    db: Session,
    run: SyntheticBenchmarkRun,
) -> tuple[IngestionBatch, int | None]:
    requester = db.get(User, run.requested_by_id)
    if requester is None:
        raise BenchmarkRunStateError("The benchmark requester no longer exists.")
    dataset = generate_synthetic_benchmark(
        transaction_count=run.transaction_count,
        seed=run.seed,
        configuration_checksum=run.configuration_checksum,
    )
    if dataset.checksum != run.dataset_checksum:
        raise BenchmarkRunStateError("The pinned generator did not reproduce the sealed dataset.")

    existing = find_batch_by_checksum(db, dataset.checksum)
    if existing is not None:
        if (
            existing.source_type != IngestionSourceType.SYNTHETIC.value
            or existing.row_count != run.transaction_count
            or existing.imported_by_id != run.requested_by_id
        ):
            raise BenchmarkRunStateError("The dataset checksum belongs to incompatible evidence.")
        return existing, None

    upload = parse_csv_upload(
        dataset.content,
        filename=f"fip-benchmark-{run.display_id}.csv",
        max_rows=run.transaction_count,
    )
    if not upload.valid or upload.checksum != run.dataset_checksum:
        raise BenchmarkRunStateError("Generated benchmark data failed the ingestion contract.")
    started_at = perf_counter_ns()
    batch = create_synthetic_ingestion(db, upload, requester)
    elapsed_milliseconds = max(0, (perf_counter_ns() - started_at) // 1_000_000)
    return batch, elapsed_milliseconds


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the governed FIP benchmark worker.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued run and exit (for scheduled cloud jobs).",
    )
    arguments = parser.parse_args(argv)
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker_id = _worker_id()
    LOGGER.info("benchmark worker %s started", worker_id)
    if arguments.once:
        processed = process_next_benchmark_run(
            worker_id=worker_id,
            lease_minutes=settings.benchmark_worker_lease_minutes,
        )
        LOGGER.info("benchmark worker %s completed one-shot processed=%s", worker_id, processed)
        return 0
    try:
        while True:
            processed = process_next_benchmark_run(
                worker_id=worker_id,
                lease_minutes=settings.benchmark_worker_lease_minutes,
            )
            if not processed:
                sleep(settings.benchmark_worker_poll_seconds)
    except KeyboardInterrupt:
        LOGGER.info("benchmark worker %s stopped", worker_id)
    return 0


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"[:120]


def _safe_failure(error: Exception) -> tuple[str, str]:
    if isinstance(error, BenchmarkRunStateError):
        return "benchmark_integrity_failed", str(error)[:500]
    return (
        "benchmark_execution_failed",
        "Synthetic benchmark execution failed. Review worker diagnostics before retrying.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
