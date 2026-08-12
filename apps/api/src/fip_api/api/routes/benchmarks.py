from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fip_api.api.dependencies import get_current_user, require_roles
from fip_api.benchmarking import (
    BENCHMARK_REPORT_SCHEMA_VERSION,
    BenchmarkRunConflict,
    BenchmarkRunNotFound,
    BenchmarkRunStateError,
    benchmark_report_facts,
    build_benchmark_run_response,
    get_benchmark_run,
    list_benchmark_runs,
    request_benchmark_run,
    retry_benchmark_run,
)
from fip_api.db.session import get_db
from fip_api.models import BenchmarkRunStatus, User, UserRole
from fip_api.schemas.benchmark import (
    BenchmarkReportResponse,
    BenchmarkRunCreate,
    BenchmarkRunCreationResponse,
    BenchmarkRunResponse,
)

router = APIRouter(prefix="/evaluation/benchmarks", tags=["evaluation-benchmarks"])
Database = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
BenchmarkOperator = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]


@router.post(
    "",
    response_model=BenchmarkRunCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_benchmark_run(
    payload: BenchmarkRunCreate,
    response: Response,
    db: Database,
    user: BenchmarkOperator,
) -> BenchmarkRunCreationResponse:
    try:
        run, created = request_benchmark_run(db, payload=payload, actor=user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The benchmark configuration changed concurrently.",
        ) from exc
    db.refresh(run)
    if not created:
        response.status_code = status.HTTP_200_OK
    return BenchmarkRunCreationResponse(
        created=created,
        run=build_benchmark_run_response(db, run),
    )


@router.get("", response_model=list[BenchmarkRunResponse])
def get_benchmark_runs(
    db: Database,
    user: AuthenticatedUser,
) -> list[BenchmarkRunResponse]:
    del user
    return [build_benchmark_run_response(db, run) for run in list_benchmark_runs(db)]


@router.get("/{run_id}", response_model=BenchmarkRunResponse)
def get_benchmark_run_detail(
    run_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> BenchmarkRunResponse:
    del user
    try:
        return build_benchmark_run_response(db, get_benchmark_run(db, run_id))
    except BenchmarkRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BenchmarkRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{run_id}/retry", response_model=BenchmarkRunResponse)
def retry_failed_benchmark_run(
    run_id: str,
    db: Database,
    user: BenchmarkOperator,
) -> BenchmarkRunResponse:
    try:
        run = retry_benchmark_run(db, run_id=run_id, actor=user)
        db.commit()
    except BenchmarkRunNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BenchmarkRunConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(run)
    return build_benchmark_run_response(db, run)


@router.get("/{run_id}/report", response_model=BenchmarkReportResponse)
def download_benchmark_report(
    run_id: str,
    db: Database,
    user: AuthenticatedUser,
) -> JSONResponse:
    del user
    try:
        run = get_benchmark_run(db, run_id)
        response = build_benchmark_run_response(db, run)
        if (
            run.status != BenchmarkRunStatus.SUCCEEDED.value
            or not response.integrity_verified
            or run.report_checksum is None
        ):
            raise BenchmarkRunConflict("A verified benchmark report is not available.")
        report = BenchmarkReportResponse(
            schema_version=BENCHMARK_REPORT_SCHEMA_VERSION,
            run=response,
            report_checksum=run.report_checksum,
            evidence_statement=(
                "Measured synthetic system-throughput evidence; not model-efficacy evidence."
            ),
        )
        # Force validation of the compact checksum-bearing report facts as part of retrieval.
        benchmark_report_facts(run)
    except BenchmarkRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BenchmarkRunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(
        report.model_dump(mode="json"),
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="fip-{run.display_id}-report.json"',
        },
    )
