from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from fip_api.models import IngestionSourceType, TransactionChannel


class TransactionCreate(BaseModel):
    external_transaction_id: str = Field(min_length=1, max_length=120)
    occurred_at: datetime
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    account_reference: str = Field(min_length=1, max_length=120)
    merchant_reference: str | None = Field(default=None, max_length=120)
    merchant_category_code: str | None = Field(default=None, max_length=12)
    channel: TransactionChannel | None = None
    source_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    destination_country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")

    @field_validator("external_transaction_id", "account_reference", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "merchant_reference",
        "merchant_category_code",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("source_country", "destination_country", mode="before")
    @classmethod
    def normalize_optional_country(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().upper()
            return value or None
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a valid timezone")
        return value.astimezone(UTC)


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_transaction_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str
    account_reference: str
    merchant_reference: str | None
    merchant_category_code: str | None
    channel: TransactionChannel | None
    source_country: str | None
    destination_country: str | None
    ingestion_batch_id: str
    source_row_number: int
    created_at: datetime


class TransactionPreview(BaseModel):
    external_transaction_id: str
    occurred_at: datetime
    amount: Decimal
    currency: str


class CsvValidationError(BaseModel):
    row_number: int | None = None
    field: str | None = None
    code: str
    message: str


class IngestionBatchReceipt(BaseModel):
    id: str
    display_id: str
    source_type: IngestionSourceType
    source_filename: str | None
    source_checksum: str
    byte_count: int
    row_count: int
    imported_by: str
    created_at: datetime


class UploadValidationResponse(BaseModel):
    valid: bool
    filename: str
    checksum: str
    byte_count: int
    row_count: int
    valid_rows: int
    rejected_rows: int
    preview: list[TransactionPreview]
    errors: list[CsvValidationError]
    existing_batch: IngestionBatchReceipt | None = None


class UploadImportResponse(BaseModel):
    created: bool
    batch: IngestionBatchReceipt


class TransactionIngestResponse(BaseModel):
    created: bool
    batch: IngestionBatchReceipt
    transaction: TransactionResponse
