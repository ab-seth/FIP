from fastapi import APIRouter

from fip_api.api.routes import admin, auth, cases, health, models, transactions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
api_router.include_router(models.router)
api_router.include_router(transactions.router)
api_router.include_router(cases.router)
