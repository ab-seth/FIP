from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fip_api.cases import open_case_for_assessment
from fip_api.ingestion.csv_parser import ParsedUpload
from fip_api.models import IngestionBatch, IngestionSourceType, Transaction, User
from fip_api.schemas.transaction import (
    CsvValidationError,
    IngestionBatchReceipt,
    TransactionCreate,
    TransactionPreview,
    UploadValidationResponse,
)
from fip_api.scoring import assess_transaction


def find_batch_by_checksum(db: Session, checksum: str) -> IngestionBatch | None:
    return db.scalar(select(IngestionBatch).where(IngestionBatch.source_checksum == checksum))


def find_transaction_by_external_id(db: Session, external_id: str) -> Transaction | None:
    return db.scalar(select(Transaction).where(Transaction.external_transaction_id == external_id))


def apply_existing_transaction_conflicts(db: Session, upload: ParsedUpload) -> None:
    external_ids = [row.transaction.external_transaction_id for row in upload.transactions]
    existing_ids: set[str] = set()
    for chunk in _chunks(external_ids, 500):
        existing_ids.update(
            db.scalars(
                select(Transaction.external_transaction_id).where(
                    Transaction.external_transaction_id.in_(chunk)
                )
            ).all()
        )

    if not existing_ids:
        return

    accepted = []
    for row in upload.transactions:
        if row.transaction.external_transaction_id in existing_ids:
            upload.add_error(
                CsvValidationError(
                    row_number=row.row_number,
                    field="external_transaction_id",
                    code="already_imported",
                    message="The transaction identifier already exists in FIP.",
                )
            )
        else:
            accepted.append(row)
    upload.transactions = accepted
    upload.finalize_errors()


def validation_response(
    db: Session,
    upload: ParsedUpload,
    *,
    existing_batch: IngestionBatch | None = None,
) -> UploadValidationResponse:
    receipt = receipt_from_batch(db, existing_batch) if existing_batch is not None else None
    return UploadValidationResponse(
        valid=upload.valid or receipt is not None,
        filename=upload.filename,
        checksum=upload.checksum,
        byte_count=upload.byte_count,
        row_count=existing_batch.row_count if existing_batch is not None else upload.row_count,
        valid_rows=existing_batch.row_count if existing_batch is not None else upload.valid_rows,
        rejected_rows=0 if existing_batch is not None else upload.rejected_rows,
        preview=[
            TransactionPreview(
                external_transaction_id=row.transaction.external_transaction_id,
                occurred_at=row.transaction.occurred_at,
                amount=row.transaction.amount,
                currency=row.transaction.currency,
            )
            for row in upload.transactions[:3]
        ],
        errors=[] if existing_batch is not None else upload.errors,
        existing_batch=receipt,
    )


def create_csv_ingestion(db: Session, upload: ParsedUpload, user: User) -> IngestionBatch:
    batch = _new_batch(
        source_type=IngestionSourceType.CSV,
        source_filename=upload.filename,
        source_checksum=upload.checksum,
        byte_count=upload.byte_count,
        row_count=upload.row_count,
        imported_by_id=user.id,
    )
    db.add(batch)
    db.flush()
    transactions = [
        _transaction_model(
            row.transaction,
            ingestion_batch_id=batch.id,
            source_row_number=row.row_number,
        )
        for row in upload.transactions
    ]
    db.add_all(transactions)
    db.flush()
    for transaction in sorted(
        transactions,
        key=lambda item: (item.occurred_at, item.external_transaction_id),
    ):
        snapshot, assessment = assess_transaction(db, transaction)
        open_case_for_assessment(db, transaction, snapshot, assessment)
    db.commit()
    db.refresh(batch)
    return batch


def create_api_ingestion(
    db: Session, payload: TransactionCreate, user: User
) -> tuple[IngestionBatch, Transaction]:
    canonical_bytes = canonical_transaction_bytes(payload)
    batch = _new_batch(
        source_type=IngestionSourceType.API,
        source_filename=None,
        source_checksum=hashlib.sha256(canonical_bytes).hexdigest(),
        byte_count=len(canonical_bytes),
        row_count=1,
        imported_by_id=user.id,
    )
    transaction = _transaction_model(
        payload,
        ingestion_batch_id=batch.id,
        source_row_number=1,
    )
    db.add_all([batch, transaction])
    db.flush()
    snapshot, assessment = assess_transaction(db, transaction)
    open_case_for_assessment(db, transaction, snapshot, assessment)
    db.commit()
    db.refresh(batch)
    db.refresh(transaction)
    return batch, transaction


def canonical_transaction_bytes(payload: TransactionCreate) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def receipt_from_batch(db: Session, batch: IngestionBatch) -> IngestionBatchReceipt:
    username = db.scalar(select(User.username).where(User.id == batch.imported_by_id))
    return IngestionBatchReceipt(
        id=batch.id,
        display_id=batch.display_id,
        source_type=IngestionSourceType(batch.source_type),
        source_filename=batch.source_filename,
        source_checksum=batch.source_checksum,
        byte_count=batch.byte_count,
        row_count=batch.row_count,
        imported_by=username or "unknown",
        created_at=batch.created_at,
    )


def _new_batch(
    *,
    source_type: IngestionSourceType,
    source_filename: str | None,
    source_checksum: str,
    byte_count: int,
    row_count: int,
    imported_by_id: str,
) -> IngestionBatch:
    batch_id = uuid4()
    return IngestionBatch(
        id=str(batch_id),
        display_id=_display_id(batch_id),
        source_type=source_type.value,
        source_filename=source_filename,
        source_checksum=source_checksum,
        byte_count=byte_count,
        row_count=row_count,
        imported_by_id=imported_by_id,
    )


def _transaction_model(
    payload: TransactionCreate,
    *,
    ingestion_batch_id: str,
    source_row_number: int,
) -> Transaction:
    return Transaction(
        external_transaction_id=payload.external_transaction_id,
        occurred_at=payload.occurred_at,
        amount=payload.amount,
        currency=payload.currency,
        account_reference=payload.account_reference,
        merchant_reference=payload.merchant_reference,
        merchant_category_code=payload.merchant_category_code,
        channel=payload.channel.value if payload.channel is not None else None,
        source_country=payload.source_country,
        destination_country=payload.destination_country,
        ingestion_batch_id=ingestion_batch_id,
        source_row_number=source_row_number,
    )


def _display_id(value: UUID) -> str:
    return f"IMP-{value.hex[:8].upper()}"


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]
