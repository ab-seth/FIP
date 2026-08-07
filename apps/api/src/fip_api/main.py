from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fip_api.api.router import api_router
from fip_api.core.config import get_settings
from fip_api.schemas.health import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Explainable transaction-risk analysis with human decision authority.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router)

    @application.get("/health", response_model=HealthResponse, tags=["health"])
    def liveness() -> HealthResponse:
        return HealthResponse(service=settings.app_name, version=settings.app_version)

    return application


app = create_app()
