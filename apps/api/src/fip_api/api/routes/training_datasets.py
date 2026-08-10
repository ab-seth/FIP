from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.db.session import get_db
from fip_api.models import User, UserRole
from fip_api.schemas.training_dataset import (
    DatasetDetailResponse,
    DatasetReadinessResponse,
    DatasetSnapshotCreate,
    DatasetSnapshotCreateResponse,
    DatasetSummaryResponse,
)
from fip_api.training_datasets import (
    DatasetNoEligibleLabels,
    DatasetNotFound,
    build_dataset_detail_response,
    build_dataset_readiness_response,
    build_dataset_summary_response,
    create_dataset_snapshot,
    get_dataset,
    list_dataset_snapshots,
)

router = APIRouter(prefix="/ml/datasets", tags=["ml-datasets"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
DatasetCurator = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]


@router.get("/readiness", response_model=DatasetReadinessResponse)
def get_dataset_readiness(
    db: Database,
    user: AuthenticatedUser,
) -> DatasetReadinessResponse:
    del user
    return build_dataset_readiness_response(db)


@router.get("", response_model=list[DatasetSummaryResponse])
def get_datasets(
    db: Database,
    user: AuthenticatedUser,
) -> list[DatasetSummaryResponse]:
    del user
    return [build_dataset_summary_response(db, dataset) for dataset in list_dataset_snapshots(db)]


@router.post("/snapshots", response_model=DatasetSnapshotCreateResponse)
def create_snapshot(
    payload: DatasetSnapshotCreate,
    db: Database,
    user: DatasetCurator,
) -> DatasetSnapshotCreateResponse:
    try:
        dataset, created = create_dataset_snapshot(
            db,
            actor=user,
            reason=payload.reason,
            cutoff_at=payload.cutoff_at,
        )
        db.commit()
    except DatasetNoEligibleLabels as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The approved label set changed while the snapshot was being created.",
        ) from exc
    db.refresh(dataset)
    return DatasetSnapshotCreateResponse(
        created=created,
        dataset=build_dataset_detail_response(db, dataset),
    )


@router.get("/{dataset_id}", response_model=DatasetDetailResponse)
def get_dataset_detail(
    dataset_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> DatasetDetailResponse:
    del user
    try:
        dataset = get_dataset(db, dataset_id)
    except DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_dataset_detail_response(db, dataset)
