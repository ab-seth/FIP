from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AuditCategory = Literal[
    "case",
    "model",
    "scoring",
    "explanation",
    "hybrid",
    "dataset",
    "training",
    "benchmark",
    "evaluation",
]
AuditIntegrityFilter = Literal["all", "verified", "failed"]


class AuditLedgerEntryResponse(BaseModel):
    id: str
    category: AuditCategory
    action: str
    subject_id: str
    subject_label: str
    actor_username: str
    detail: str
    sequence_number: int | None
    occurred_at: datetime
    checksum: str
    previous_checksum: str | None
    integrity_verified: bool
    href: str
    metadata: dict[str, object]


class AuditLedgerSummaryResponse(BaseModel):
    total_records: int
    verified_records: int
    failed_records: int
    chained_records: int
    category_counts: dict[str, int]


class AuditLedgerResponse(BaseModel):
    schema_version: str
    entries: list[AuditLedgerEntryResponse]
    summary: AuditLedgerSummaryResponse
    total: int
    page: int
    page_size: int
    page_count: int
    category: AuditCategory | None
    integrity: AuditIntegrityFilter
    query: str | None
    read_only: bool = True
    changes_operational_state: bool = False
