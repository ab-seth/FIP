from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    model_artifact_root: Path = Path("/var/lib/fip/model-artifacts")
    model_artifact_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    training_artifact_root: Path = Path("/var/lib/fip/training-artifacts")
    training_artifact_max_bytes: int = Field(default=256 * 1024 * 1024, ge=1024)
    training_worker_poll_seconds: int = Field(default=2, ge=1, le=60)
    training_worker_lease_minutes: int = Field(default=360, ge=30, le=1440)
    benchmark_worker_poll_seconds: int = Field(default=2, ge=1, le=60)
    benchmark_worker_lease_minutes: int = Field(default=360, ge=30, le=1440)
    artifact_store: Literal["filesystem", "s3"] = "filesystem"
    object_store_endpoint: str | None = None
    object_store_bucket: str | None = None
    object_store_access_key_id: SecretStr | None = None
    object_store_secret_access_key: SecretStr | None = None
    object_store_region: str = "auto"
    object_store_prefix: str = "fip"
    llm_adapter: Literal["json-http", "openai-compatible"] = "json-http"
    llm_endpoint: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_provider_name: str = Field(default="json-http", min_length=2, max_length=64)
    llm_timeout_seconds: int = Field(default=8, ge=1, le=120)
    llm_max_response_bytes: int = Field(default=256 * 1024, ge=1024, le=1024 * 1024)
    llm_max_completion_tokens: int = Field(default=1800, ge=256, le=8192)
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:3000"]
    trusted_hosts: list[str] = []

    @field_validator(
        "llm_endpoint",
        "llm_model",
        "llm_api_key",
        "object_store_endpoint",
        "object_store_bucket",
        "object_store_access_key_id",
        "object_store_secret_access_key",
        mode="before",
    )
    @classmethod
    def normalize_optional_llm_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        jwt_secret = self.jwt_secret.get_secret_value()
        if len(jwt_secret) < 32:
            raise ValueError("FIP_JWT_SECRET must contain at least 32 characters")
        if self.environment in {"staging", "production"} and (
            jwt_secret == DEFAULT_JWT_SECRET or jwt_secret.startswith("replace-")
        ):
            raise ValueError("FIP_JWT_SECRET must be replaced outside local development")
        if self.artifact_store == "s3":
            required = {
                "FIP_OBJECT_STORE_ENDPOINT": self.object_store_endpoint,
                "FIP_OBJECT_STORE_BUCKET": self.object_store_bucket,
                "FIP_OBJECT_STORE_ACCESS_KEY_ID": self.object_store_access_key_id,
                "FIP_OBJECT_STORE_SECRET_ACCESS_KEY": self.object_store_secret_access_key,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(f"S3 artifact storage requires {', '.join(sorted(missing))}")
            if self.environment in {"staging", "production"} and not str(
                self.object_store_endpoint
            ).startswith("https://"):
                raise ValueError("FIP_OBJECT_STORE_ENDPOINT must use HTTPS outside development")
        prefix = self.object_store_prefix.strip("/")
        if not prefix or ".." in prefix.split("/"):
            raise ValueError("FIP_OBJECT_STORE_PREFIX must be a safe non-empty key prefix")
        self.object_store_prefix = prefix
        if self.llm_endpoint is not None:
            if not self.llm_endpoint.startswith(("http://", "https://")):
                raise ValueError("FIP_LLM_ENDPOINT must use HTTP or HTTPS")
            if self.llm_model is None or not self.llm_model.strip():
                raise ValueError("FIP_LLM_MODEL is required when FIP_LLM_ENDPOINT is configured")
            if self.environment in {"staging", "production"} and not self.llm_endpoint.startswith(
                "https://"
            ):
                raise ValueError("FIP_LLM_ENDPOINT must use HTTPS outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
