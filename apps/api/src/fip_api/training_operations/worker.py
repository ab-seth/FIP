from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import suppress
from time import sleep
from uuid import uuid4

from sqlalchemy.orm import Session

from fip_api.core.config import get_settings
from fip_api.db.session import SessionLocal
from fip_api.models import OperationalDatasetSnapshot, OperationalTrainingRun
from fip_api.operational_ml.dataset import (
    OperationalTrainingBlocked,
    OperationalTrainingContractError,
)
from fip_api.operational_ml.pipeline import (
    OperationalTrainingConfig,
    run_operational_training,
)
from fip_api.training_operations.artifacts import (
    TrainingArtifactStore,
    TrainingBundleError,
)
from fip_api.training_operations.service import (
    claim_next_training_run,
    complete_training_run,
    fail_training_run,
    get_training_artifact_store,
    inspect_completed_bundle,
)

LOGGER = logging.getLogger("fip.training-worker")
TrainingRunner = Callable[[Session, str, OperationalTrainingConfig], dict[str, object]]
SessionFactory = Callable[[], Session]


def process_next_training_run(
    *,
    session_factory: SessionFactory = SessionLocal,
    store: TrainingArtifactStore | None = None,
    worker_id: str | None = None,
    lease_minutes: int | None = None,
    runner: TrainingRunner = run_operational_training,
) -> bool:
    settings = get_settings()
    artifact_store = store or get_training_artifact_store()
    identity = worker_id or _worker_id()
    lease = lease_minutes or settings.training_worker_lease_minutes

    with session_factory() as db:
        run = claim_next_training_run(db, worker_id=identity, lease_minutes=lease)
        if run is None:
            db.commit()
            return False
        run_id = run.id
        dataset_id = run.dataset_id
        config = OperationalTrainingConfig(
            output_directory=artifact_store.output_directory(run.id),
            version=run.candidate_version,
            seed=run.seed,
            maximum_false_positive_rate=float(run.maximum_false_positive_rate),
        )
        db.commit()

    try:
        artifact_store.root.mkdir(mode=0o750, parents=True, exist_ok=True)
        with session_factory() as db:
            dataset = db.get(OperationalDatasetSnapshot, dataset_id)
            if dataset is None:
                raise OperationalTrainingBlocked(
                    "The queued operational dataset is no longer available."
                )
            dataset_display_id = dataset.display_id
            dataset_feature_set_version = dataset.feature_set_version
            # A prior worker may have written the atomic bundle before losing its
            # lease. Fresh inspection below decides whether it can be recovered.
            with suppress(FileExistsError):
                runner(db, dataset_id, config)
        with session_factory() as db:
            claimed = db.get(OperationalTrainingRun, run_id)
            if claimed is None:
                raise OperationalTrainingBlocked("The queued training run no longer exists.")
            inspection = inspect_completed_bundle(
                claimed,
                dataset_display_id=dataset_display_id,
                dataset_feature_set_version=dataset_feature_set_version,
                store=artifact_store,
            )
            artifact_store.make_immutable(run_id)
            complete_training_run(
                db,
                run_id=run_id,
                worker_id=identity,
                inspection=inspection,
            )
            db.commit()
        LOGGER.info("training run %s completed", run_id)
    except Exception as exc:
        error_code, error_message = _safe_failure(exc)
        with session_factory() as db:
            try:
                fail_training_run(
                    db,
                    run_id=run_id,
                    worker_id=identity,
                    error_code=error_code,
                    error_message=error_message,
                )
                db.commit()
            except Exception:
                db.rollback()
                LOGGER.exception("could not record failure for training run %s", run_id)
        LOGGER.warning("training run %s failed: %s", run_id, error_code)
    return True


def main() -> int:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker_id = _worker_id()
    LOGGER.info("training worker %s started", worker_id)
    try:
        while True:
            processed = process_next_training_run(
                worker_id=worker_id,
                lease_minutes=settings.training_worker_lease_minutes,
            )
            if not processed:
                sleep(settings.training_worker_poll_seconds)
    except KeyboardInterrupt:
        LOGGER.info("training worker %s stopped", worker_id)
    return 0


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"[:120]


def _safe_failure(error: Exception) -> tuple[str, str]:
    if isinstance(error, (OperationalTrainingBlocked, OperationalTrainingContractError)):
        return "training_admission_failed", str(error)[:500]
    if isinstance(error, TrainingBundleError):
        return "candidate_bundle_integrity_failed", str(error)[:500]
    if isinstance(error, FileExistsError):
        return (
            "candidate_bundle_conflict",
            "A candidate bundle already exists for this immutable training run.",
        )
    return (
        "training_execution_failed",
        "Candidate training failed. Review worker diagnostics before choosing a new version.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
