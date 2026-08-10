from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "development-only-secret-change-before-use"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FIP_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FIP API"
    app_version: str = "0.1.0"
    environment: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://fip:fip@localhost:5432/fip"
    jwt_secret: SecretStr = SecretStr(DEFAULT_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    login_max_attempts: int = Field(default=3, ge=2, le=10)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)
    transaction_upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    transaction_upload_max_rows: int = Field(default=10_000, ge=1, le=100_000)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:3000"]

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        jwt_secret = self.jwt_secret.get_secret_value()
        if len(jwt_secret) < 32:
            raise ValueError("FIP_JWT_SECRET must contain at least 32 characters")
        if self.environment == "production" and (
            jwt_secret == DEFAULT_JWT_SECRET or jwt_secret.startswith("replace-")
        ):
            raise ValueError("FIP_JWT_SECRET must be replaced in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
