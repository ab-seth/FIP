from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.core.config import get_settings
from fip_api.db.session import get_db
from fip_api.hybrid_scoring import (
    HybridEvidenceNotFound,
    HybridEvidenceViolation,
    build_hybrid_assessment_response,
    create_hybrid_assessment,
    list_hybrid_assessments,
)
from fip_api.ingestion.csv_parser import parse_csv_upload
from fip_api.ingestion.service import (
    apply_existing_transaction_conflicts,
    canonical_transaction_bytes,
    create_api_ingestion,
    create_csv_ingestion,
    find_batch_by_checksum,
    find_transaction_by_external_id,
    receipt_from_batch,
    validation_response,
)
from fip_api.model_registry import build_shadow_prediction_response, list_shadow_predictions
from fip_api.models import RuleRiskLevel, Transaction, User, UserRole
from fip_api.rules import EVALUATED_RULE_COUNT
from fip_api.schemas.hybrid_risk import (
    HybridAssessmentCreate,
    HybridAssessmentCreationResponse,
    HybridRiskAssessmentResponse,
)
from fip_api.schemas.model_registry import ShadowPredictionResponse
from fip_api.schemas.risk import (
    FeatureSnapshotResponse,
    RuleAssessmentResponse,
    RuleTriggerResponse,
    SemanticFeatureValues,
)
from fip_api.schemas.transaction import (
    TransactionCreate,
    TransactionIngestResponse,
    TransactionResponse,
    UploadImportResponse,
    UploadValidationResponse,
)
from fip_api.scoring import find_current_rule_assessment

router = APIRouter(prefix="/transactions", tags=["transactions"])
IntakeUser = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.ANALYST)),
]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
HybridEvidenceActor = Annotated[
    User,
    Depends(require_roles(UserRole.ADMINISTRATOR, UserRole.EVALUATOR)),
]
Database = Annotated[Session, Depends(get_db)]
SourceFilename = Annotated[str | None, Header(alias="X-FIP-Filename")]


@router.post("/upload/validate", response_model=UploadValidationResponse)
async def validate_upload(
    request: Request,
    db: Database,
    user: IntakeUser,
    source_filename: SourceFilename = None,
) -> UploadValidationResponse:
    del user
    settings = get_settings()
    content = await _read_upload(request, settings.transaction_upload_max_bytes)
    upload = parse_csv_upload(
        content,
        filename=source_filename,
        max_rows=settings.transaction_upload_max_rows,
    )

    existing_batch = find_batch_by_checksum(db, upload.checksum) if upload.valid else None
    if existing_batch is None and upload.valid:
        apply_existing_transaction_conflicts(db, upload)
    return validation_response(db, upload, existing_batch=existing_batch)


@router.post("/upload", response_model=UploadImportResponse)
async def import_upload(
    request: Request,
    db: Database,
    user: IntakeUser,
    source_filename: SourceFilename = None,
) -> UploadImportResponse | JSONResponse:
    settings = get_settings()
    content = await _read_upload(request, settings.transaction_upload_max_bytes)
    upload = parse_csv_upload(
        content,
        filename=source_filename,
        max_rows=settings.transaction_upload_max_rows,
    )

    if upload.valid:
        existing_batch = find_batch_by_checksum(db, upload.checksum)
        if existing_batch is not None:
            return UploadImportResponse(
                created=False,
                batch=receipt_from_batch(db, existing_batch),
            )
        apply_existing_transaction_conflicts(db, upload)

    if not upload.valid:
        validation = validation_response(db, upload)
        return JSONResponse(status_code=422, content=validation.model_dump(mode="json"))

    try:
        batch = create_csv_ingestion(db, upload, user)
    except IntegrityError:
        db.rollback()
        existing_batch = find_batch_by_checksum(db, upload.checksum)
        if existing_batch is not None:
            return UploadImportResponse(
                created=False,
                batch=receipt_from_batch(db, existing_batch),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload conflicts with transactions already stored in FIP.",
        ) from None

    return UploadImportResponse(created=True, batch=receipt_from_batch(db, batch))


@router.post(
    "",
    response_model=TransactionIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_transaction(
    payload: TransactionCreate,
    response: Response,
    db: Database,
    user: IntakeUser,
) -> TransactionIngestResponse:
    checksum = hashlib.sha256(canonical_transaction_bytes(payload)).hexdigest()
    existing_batch = find_batch_by_checksum(db, checksum)
    existing_transaction = find_transaction_by_external_id(db, payload.external_transaction_id)

    if (
        existing_batch is not None
        and existing_transaction is not None
        and existing_transaction.ingestion_batch_id == existing_batch.id
    ):
        response.status_code = status.HTTP_200_OK
        return TransactionIngestResponse(
            created=False,
            batch=receipt_from_batch(db, existing_batch),
            transaction=TransactionResponse.model_validate(existing_transaction),
        )
    if existing_batch is not None or existing_transaction is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The external transaction identifier already exists with different data.",
        )

    try:
        batch, transaction = create_api_ingestion(db, payload, user)
    except IntegrityError:
        db.rollback()
        existing_batch = find_batch_by_checksum(db, checksum)
        existing_transaction = find_transaction_by_external_id(db, payload.external_transaction_id)
        if (
            existing_batch is not None
            and existing_transaction is not None
            and existing_transaction.ingestion_batch_id == existing_batch.id
        ):
            response.status_code = status.HTTP_200_OK
            return TransactionIngestResponse(
                created=False,
                batch=receipt_from_batch(db, existing_batch),
                transaction=TransactionResponse.model_validate(existing_transaction),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The external transaction identifier already exists with different data.",
        ) from None

    response.status_code = status.HTTP_201_CREATED
    return TransactionIngestResponse(
        created=True,
        batch=receipt_from_batch(db, batch),
        transaction=TransactionResponse.model_validate(transaction),
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    transaction_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> Transaction:
    del user
    transaction = db.scalar(select(Transaction).where(Transaction.id == transaction_id))
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@router.get("/{transaction_id}/rule-assessment", response_model=RuleAssessmentResponse)
def get_rule_assessment(
    transaction_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> RuleAssessmentResponse:
    del user
    result = find_current_rule_assessment(db, transaction_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Rule assessment not found")
    snapshot, assessment = result
    return RuleAssessmentResponse(
        transaction_id=assessment.transaction_id,
        ruleset_version=assessment.ruleset_version,
        risk_band_version=assessment.risk_band_version,
        evaluated_rule_count=EVALUATED_RULE_COUNT,
        rule_score=assessment.rule_score,
        risk_level=RuleRiskLevel(assessment.risk_level),
        triggered_rules=[
            RuleTriggerResponse.model_validate(trigger) for trigger in assessment.triggered_rules
        ],
        assessment_checksum=assessment.assessment_checksum,
        feature_snapshot=FeatureSnapshotResponse(
            feature_set_version=snapshot.feature_set_version,
            history_window_start=snapshot.history_window_start,
            history_window_end=snapshot.history_window_end,
            history_checksum=snapshot.history_checksum,
            snapshot_checksum=snapshot.snapshot_checksum,
            values=SemanticFeatureValues.model_validate(snapshot.feature_values),
            created_at=snapshot.created_at,
        ),
        created_at=assessment.created_at,
    )


@router.get(
    "/{transaction_id}/shadow-predictions",
    response_model=list[ShadowPredictionResponse],
)
def get_shadow_predictions(
    transaction_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> list[ShadowPredictionResponse]:
    del user
    if db.get(Transaction, transaction_id) is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return [
        build_shadow_prediction_response(db, prediction)
        for prediction in list_shadow_predictions(db, transaction_id)
    ]


@router.post(
    "/{transaction_id}/hybrid-assessments",
    response_model=HybridAssessmentCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction_hybrid_assessment(
    transaction_id: str,
    payload: HybridAssessmentCreate,
    response: Response,
    db: Database,
    user: HybridEvidenceActor,
) -> HybridAssessmentCreationResponse:
    try:
        assessment, created = create_hybrid_assessment(
            db,
            transaction_id=transaction_id,
            supervised_prediction_id=payload.supervised_prediction_id,
            anomaly_prediction_id=payload.anomaly_prediction_id,
            actor=user,
        )
        db.commit()
    except HybridEvidenceNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HybridEvidenceViolation as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The hybrid evidence set changed concurrently.",
        ) from exc

    db.refresh(assessment)
    if not created:
        response.status_code = status.HTTP_200_OK
    return HybridAssessmentCreationResponse(
        created=created,
        assessment=build_hybrid_assessment_response(db, assessment),
    )


@router.get(
    "/{transaction_id}/hybrid-assessments",
    response_model=list[HybridRiskAssessmentResponse],
)
def get_transaction_hybrid_assessments(
    transaction_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> list[HybridRiskAssessmentResponse]:
    del user
    if db.get(Transaction, transaction_id) is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return [
        build_hybrid_assessment_response(db, assessment)
        for assessment in list_hybrid_assessments(db, transaction_id)
    ]


async def _read_upload(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > max_bytes:
        raise _upload_too_large(max_bytes)

    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > max_bytes:
            raise _upload_too_large(max_bytes)
        content.extend(chunk)
    return bytes(content)


def _upload_too_large(max_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        detail=f"The CSV file cannot exceed {max_bytes // (1024 * 1024)} MB.",
    )
