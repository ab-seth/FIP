from fastapi import APIRouter

from fip_api.api.routes import (
    admin,
    audit,
    auth,
    cases,
    evaluation,
    health,
    models,
    training_datasets,
    training_runs,
    transactions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(audit.router)
api_router.include_router(models.router)
api_router.include_router(transactions.router)
api_router.include_router(cases.router)
api_router.include_router(training_datasets.router)
api_router.include_router(training_runs.router)
api_router.include_router(evaluation.router)
