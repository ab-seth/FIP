from fastapi import APIRouter

from fip_api.api.routes import admin, auth, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(admin.router)
