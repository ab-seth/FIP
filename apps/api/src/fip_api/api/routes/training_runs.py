from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.db.session import get_db
from fip_api.models import TrainingRunStatus, User, UserRole
from fip_api.schemas.training_run import (
    TrainingRunCreate,
    TrainingRunCreationResponse,
    TrainingRunResponse,
)
from fip_api.training_operations import (
    TrainingArtifactStore,
    TrainingBundleError,
    TrainingRunConflict,
    TrainingRunNotFound,
    TrainingRunStateError,
    build_training_run_response,
    get_training_artifact_store,
    get_training_run,
    list_training_runs,
    request_training_run,
    retry_training_run,
    verify_training_run_integrity,
)

router = APIRouter(prefix="/ml/training-runs", tags=["ml-training-runs"])
Database = Annotated[Session, Depends(get_db)]
ArtifactStore = Annotated[TrainingArtifactStore, Depends(get_training_artifact_store)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
TrainingOperator = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]
ModelKindPath = Literal["supervised", "anomaly"]
ArtifactNamePath = Literal["registration", "model-card", "model"]
EvidenceNamePath = Literal["training-evidence", "run-manifest"]


@router.post(
    "",
    response_model=TrainingRunCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_training_run(
    payload: TrainingRunCreate,
    response: Response,
    db: Database,
    store: ArtifactStore,
    user: TrainingOperator,
) -> TrainingRunCreationResponse:
    try:
        run, created = request_training_run(db, payload=payload, actor=user)
        db.commit()
    except TrainingRunNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrainingRunConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The training configuration changed concurrently.",
        ) from exc
    db.refresh(run)
    if not created:
        response.status_code = status.HTTP_200_OK
    return TrainingRunCreationResponse(
        created=created,
        run=build_training_run_response(db, run, store),
    )


@router.get("", response_model=list[TrainingRunResponse])
def get_training_runs(
    db: Database,
    store: ArtifactStore,
    user: AuthenticatedUser,
) -> list[TrainingRunResponse]:
    del user
    return [build_training_run_response(db, run, store) for run in list_training_runs(db)]


@router.get("/{run_id}", response_model=TrainingRunResponse)
def get_training_run_detail(
    run_id: str,
    db: Database,
    store: ArtifactStore,
    user: AuthenticatedUser,
) -> TrainingRunResponse:
    del user
    try:
        run = get_training_run(db, run_id)
        return build_training_run_response(db, run, store)
    except TrainingRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrainingRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/retry", response_model=TrainingRunResponse)
def retry_failed_training_run(
    run_id: str,
    db: Database,
    store: ArtifactStore,
    user: TrainingOperator,
) -> TrainingRunResponse:
    try:
        run = retry_training_run(db, run_id=run_id, actor=user)
        db.commit()
    except TrainingRunNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TrainingRunConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(run)
    return build_training_run_response(db, run, store)


@router.get("/{run_id}/artifacts/{model_kind}/{artifact_name}")
def download_training_artifact(
    run_id: str,
    model_kind: ModelKindPath,
    artifact_name: ArtifactNamePath,
    db: Database,
    store: ArtifactStore,
    user: AuthenticatedUser,
) -> FileResponse:
    if artifact_name == "model" and user.role != UserRole.ADMINISTRATOR.value:
        raise HTTPException(
            status_code=403,
            detail="Only an administrator may retrieve an executable candidate artifact.",
        )
    try:
        run = get_training_run(db, run_id)
        if run.status != TrainingRunStatus.SUCCEEDED.value or run.bundle_key is None:
            raise TrainingRunConflict("Candidate artifacts are not available for this run.")
        if not verify_training_run_integrity(db, run, store=store):
            raise TrainingRunConflict("The candidate bundle failed integrity verification.")
        path = store.artifact_path(
            run.bundle_key,
            model_kind=model_kind,
            artifact_name=artifact_name,
        )
    except TrainingRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TrainingRunConflict, TrainingBundleError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    extension, media_type = {
        "registration": ("registration-payload.json", "application/json"),
        "model-card": ("model-card.md", "text/markdown; charset=utf-8"),
        "model": ("model.joblib", "application/octet-stream"),
    }[artifact_name]
    return FileResponse(
        path,
        filename=f"fip-{run.candidate_version}-{model_kind}-{extension}",
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{run_id}/evidence/{evidence_name}")
def download_training_evidence(
    run_id: str,
    evidence_name: EvidenceNamePath,
    db: Database,
    store: ArtifactStore,
    user: AuthenticatedUser,
) -> FileResponse:
    del user
    try:
        run = get_training_run(db, run_id)
        if run.status != TrainingRunStatus.SUCCEEDED.value or run.bundle_key is None:
            raise TrainingRunConflict("Candidate evidence is not available for this run.")
        if not verify_training_run_integrity(db, run, store=store):
            raise TrainingRunConflict("The candidate bundle failed integrity verification.")
        path = store.evidence_path(run.bundle_key, evidence_name=evidence_name)
    except TrainingRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TrainingRunConflict, TrainingBundleError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileResponse(
        path,
        filename=f"fip-{run.candidate_version}-{evidence_name}.json",
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
