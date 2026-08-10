from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import PurePath
from urllib.parse import unquote

from pydantic import ValidationError

from fip_api.schemas.transaction import CsvValidationError, TransactionCreate

REQUIRED_FIELDS = (
    "external_transaction_id",
    "occurred_at",
    "amount",
    "currency",
    "account_reference",
)
OPTIONAL_FIELDS = (
    "merchant_reference",
    "merchant_category_code",
    "channel",
    "source_country",
    "destination_country",
)
ALLOWED_FIELDS = frozenset((*REQUIRED_FIELDS, *OPTIONAL_FIELDS))
MAX_RETURNED_ERRORS = 100


@dataclass(frozen=True)
class ParsedTransaction:
    row_number: int
    transaction: TransactionCreate


@dataclass
class ParsedUpload:
    filename: str
    checksum: str
    byte_count: int
    row_count: int = 0
    transactions: list[ParsedTransaction] = field(default_factory=list)
    errors: list[CsvValidationError] = field(default_factory=list)
    error_count: int = 0

    @property
    def valid(self) -> bool:
        return self.row_count > 0 and self.error_count == 0

    @property
    def valid_rows(self) -> int:
        return len(self.transactions)

    @property
    def rejected_rows(self) -> int:
        return max(0, self.row_count - self.valid_rows)

    def add_error(self, error: CsvValidationError) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_RETURNED_ERRORS:
            self.errors.append(error)

    def finalize_errors(self) -> None:
        if self.error_count > MAX_RETURNED_ERRORS:
            self.errors[-1] = CsvValidationError(
                code="errors_truncated",
                message=(
                    f"Only the first {MAX_RETURNED_ERRORS - 1} validation errors are shown. "
                    f"The file contains {self.error_count} errors."
                ),
            )


def sanitize_filename(value: str | None) -> str:
    decoded = unquote(value or "transactions.csv").replace("\\", "/")
    filename = PurePath(decoded).name.strip()
    filename = "".join(character for character in filename if character.isprintable())
    return (filename or "transactions.csv")[:255]


def parse_csv_upload(
    content: bytes,
    *,
    filename: str | None,
    max_rows: int,
) -> ParsedUpload:
    result = ParsedUpload(
        filename=sanitize_filename(filename),
        checksum=hashlib.sha256(content).hexdigest(),
        byte_count=len(content),
    )

    if not result.filename.lower().endswith(".csv"):
        result.add_error(
            CsvValidationError(
                field="file",
                code="invalid_file_type",
                message="The source file must use the .csv extension.",
            )
        )
        return result

    if not content:
        result.add_error(
            CsvValidationError(
                field="file",
                code="empty_file",
                message="The source file is empty.",
            )
        )
        return result

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        result.add_error(
            CsvValidationError(
                field="file",
                code="invalid_encoding",
                message="The CSV file must be UTF-8 encoded.",
            )
        )
        return result

    if "\x00" in decoded:
        result.add_error(
            CsvValidationError(
                field="file",
                code="invalid_content",
                message="The CSV file contains unsupported null characters.",
            )
        )
        return result

    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        raw_headers = reader.fieldnames
        if raw_headers is None:
            result.add_error(
                CsvValidationError(
                    field="header",
                    code="missing_header",
                    message="The CSV file must include a header row.",
                )
            )
            return result

        headers = [header.strip() for header in raw_headers]
        reader.fieldnames = headers
        _validate_headers(headers, result)
        if result.error_count:
            result.finalize_errors()
            return result

        seen_external_ids: dict[str, int] = {}
        for row_number, row in enumerate(reader, start=2):
            if _is_blank_row(row):
                continue

            result.row_count += 1
            if result.row_count > max_rows:
                result.add_error(
                    CsvValidationError(
                        field="file",
                        code="row_limit_exceeded",
                        message=f"The CSV file cannot contain more than {max_rows:,} rows.",
                    )
                )
                break

            if None in row:
                result.add_error(
                    CsvValidationError(
                        row_number=row_number,
                        code="extra_values",
                        message="The row contains more values than the header defines.",
                    )
                )
                continue

            try:
                transaction = TransactionCreate.model_validate(_normalize_row(row))
            except ValidationError as exc:
                for validation_error in exc.errors(include_url=False, include_input=False):
                    location = validation_error.get("loc", ())
                    field_name = str(location[0]) if location else None
                    message = str(validation_error["msg"]).removeprefix("Value error, ")
                    result.add_error(
                        CsvValidationError(
                            row_number=row_number,
                            field=field_name,
                            code=_error_code(str(validation_error["type"])),
                            message=message,
                        )
                    )
                continue

            previous_row = seen_external_ids.get(transaction.external_transaction_id)
            if previous_row is not None:
                result.add_error(
                    CsvValidationError(
                        row_number=row_number,
                        field="external_transaction_id",
                        code="duplicate_in_file",
                        message=f"The identifier duplicates row {previous_row}.",
                    )
                )
                continue

            seen_external_ids[transaction.external_transaction_id] = row_number
            result.transactions.append(
                ParsedTransaction(row_number=row_number, transaction=transaction)
            )
    except csv.Error as exc:
        result.add_error(
            CsvValidationError(
                field="file",
                code="invalid_csv",
                message=f"The CSV structure is invalid: {exc}.",
            )
        )

    if result.row_count == 0 and result.error_count == 0:
        result.add_error(
            CsvValidationError(
                field="file",
                code="no_transactions",
                message="The CSV file does not contain any transaction rows.",
            )
        )

    result.finalize_errors()
    return result


def _validate_headers(headers: list[str], result: ParsedUpload) -> None:
    if any(not header for header in headers):
        result.add_error(
            CsvValidationError(
                field="header",
                code="blank_header",
                message="Every CSV column must have a name.",
            )
        )

    duplicates = sorted({header for header in headers if headers.count(header) > 1})
    if duplicates:
        result.add_error(
            CsvValidationError(
                field="header",
                code="duplicate_header",
                message=f"Duplicate CSV columns: {', '.join(duplicates)}.",
            )
        )

    missing = sorted(set(REQUIRED_FIELDS) - set(headers))
    if missing:
        result.add_error(
            CsvValidationError(
                field="header",
                code="missing_columns",
                message=f"Missing required columns: {', '.join(missing)}.",
            )
        )

    unexpected = sorted(set(headers) - ALLOWED_FIELDS)
    if unexpected:
        result.add_error(
            CsvValidationError(
                field="header",
                code="unexpected_columns",
                message=f"Unsupported columns: {', '.join(unexpected)}.",
            )
        )


def _normalize_row(row: dict[str | None, str | list[str] | None]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for field_name in ALLOWED_FIELDS:
        value = row.get(field_name)
        normalized[field_name] = value.strip() if isinstance(value, str) else value
    for field_name in OPTIONAL_FIELDS:
        if normalized.get(field_name) == "":
            normalized[field_name] = None
    return normalized


def _is_blank_row(row: dict[str | None, str | list[str] | None]) -> bool:
    return all(
        value is None or value == [] or (isinstance(value, str) and not value.strip())
        for value in row.values()
    )


def _error_code(error_type: str) -> str:
    if error_type == "missing":
        return "required"
    if "datetime" in error_type:
        return "invalid_datetime"
    if error_type in {"string_pattern_mismatch", "enum"}:
        return "invalid_format"
    if error_type.startswith("decimal") or error_type in {"greater_than", "less_than"}:
        return "invalid_amount"
    return "invalid_value"
