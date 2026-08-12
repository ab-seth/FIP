from __future__ import annotations

import csv
import hashlib
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fip_api.core.checksums import canonical_json_checksum
from fip_api.schemas.transaction import TransactionCreate

GENERATOR_VERSION = "synthetic-transaction-generator-v1.0.0"
BASE_TIMESTAMP = datetime(2026, 1, 1, 12, tzinfo=UTC)
ROWS_PER_ACCOUNT = 20
PROFILE_CYCLE = (
    *("normal",) * 70,
    *("amount_spike",) * 10,
    *("rapid_cross_border",) * 8,
    *("cross_border",) * 6,
    *("elevated_mcc",) * 4,
    *("combined",) * 2,
)
CSV_FIELDS = (
    "external_transaction_id",
    "occurred_at",
    "amount",
    "currency",
    "account_reference",
    "merchant_reference",
    "merchant_category_code",
    "channel",
    "source_country",
    "destination_country",
)


@dataclass(frozen=True)
class SyntheticBenchmarkDataset:
    content: bytes
    checksum: str
    transaction_set_checksum: str
    profile_distribution: dict[str, object]
    first_occurred_at: datetime
    last_occurred_at: datetime


def generate_synthetic_benchmark(
    *,
    transaction_count: int,
    seed: int,
    configuration_checksum: str,
) -> SyntheticBenchmarkDataset:
    if not 100 <= transaction_count <= 10_000:
        raise ValueError("transaction_count must be between 100 and 10,000")
    if seed < 0:
        raise ValueError("seed must be non-negative")

    randomizer = random.Random(seed)
    transactions: list[TransactionCreate] = []
    profile_accounts: dict[str, int] = {profile: 0 for profile in dict.fromkeys(PROFILE_CYCLE)}
    profile_transactions: dict[str, int] = {profile: 0 for profile in dict.fromkeys(PROFILE_CYCLE)}
    remaining = transaction_count
    account_index = 0
    while remaining:
        group_size = min(ROWS_PER_ACCOUNT, remaining)
        profile = PROFILE_CYCLE[(account_index + seed) % len(PROFILE_CYCLE)]
        profile_accounts[profile] += 1
        profile_transactions[profile] += group_size
        transactions.extend(
            _account_transactions(
                account_index=account_index,
                configuration_checksum=configuration_checksum,
                group_size=group_size,
                profile=profile,
                randomizer=randomizer,
            )
        )
        remaining -= group_size
        account_index += 1

    transactions.sort(key=lambda item: (item.occurred_at, item.external_transaction_id))
    content = _csv_bytes(transactions)
    return SyntheticBenchmarkDataset(
        content=content,
        checksum=hashlib.sha256(content).hexdigest(),
        transaction_set_checksum=synthetic_transaction_set_checksum(transactions),
        profile_distribution={
            "account_profiles": profile_accounts,
            "transaction_profiles": profile_transactions,
            "account_count": account_index,
            "rows_per_account": ROWS_PER_ACCOUNT,
        },
        first_occurred_at=transactions[0].occurred_at,
        last_occurred_at=transactions[-1].occurred_at,
    )


def synthetic_transaction_set_checksum(
    transactions: Sequence[TransactionCreate],
) -> str:
    return canonical_json_checksum(
        [
            transaction.model_dump(mode="json")
            for transaction in sorted(
                transactions,
                key=lambda item: item.external_transaction_id,
            )
        ]
    )


def _account_transactions(
    *,
    account_index: int,
    configuration_checksum: str,
    group_size: int,
    profile: str,
    randomizer: random.Random,
) -> list[TransactionCreate]:
    prefix = configuration_checksum[:12].upper()
    account = f"SYN-ACC-{prefix}-{account_index:05d}"
    rows: list[TransactionCreate] = []
    burst_start = BASE_TIMESTAMP + timedelta(days=19, seconds=account_index)
    for row_index in range(group_size):
        amount = (Decimal(randomizer.randrange(2_000, 18_000)) / Decimal(100)).quantize(
            Decimal("0.01")
        )
        occurred_at = BASE_TIMESTAMP + timedelta(days=row_index, seconds=account_index)
        merchant = f"SYN-MERCHANT-{account_index % 25:03d}"
        merchant_category_code = "5411"
        channel = "card_present"
        destination_country = "US"

        final_row = row_index == group_size - 1
        burst_row = group_size >= 5 and row_index >= group_size - 5
        if profile in {"rapid_cross_border", "combined"} and burst_row:
            occurred_at = burst_start + timedelta(minutes=(row_index - (group_size - 5)) * 10)
            channel = "card_not_present"
            destination_country = "KE"
            merchant = f"SYN-BURST-{account_index:05d}"
        if final_row and profile in {"cross_border", "combined"}:
            occurred_at = occurred_at.replace(hour=2)
            channel = "card_not_present"
            destination_country = "KE"
            merchant = f"SYN-NEW-{account_index:05d}"
        if final_row and profile in {"amount_spike", "combined"}:
            amount = Decimal("1500.00")
        if final_row and profile in {"elevated_mcc", "combined"}:
            merchant_category_code = "6011"
            merchant = f"SYN-MCC-{account_index:05d}"

        rows.append(
            TransactionCreate(
                external_transaction_id=(f"SYN-{prefix}-{account_index:05d}-{row_index + 1:02d}"),
                occurred_at=occurred_at,
                amount=amount,
                currency="USD",
                account_reference=account,
                merchant_reference=merchant,
                merchant_category_code=merchant_category_code,
                channel=channel,
                source_country="US",
                destination_country=destination_country,
            )
        )
    return rows


def _csv_bytes(transactions: list[TransactionCreate]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for transaction in transactions:
        payload = transaction.model_dump(mode="json")
        writer.writerow(
            {field: "" if payload.get(field) is None else payload[field] for field in CSV_FIELDS}
        )
    return output.getvalue().encode("utf-8")
