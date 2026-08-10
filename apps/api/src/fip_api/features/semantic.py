from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fip_api.core.checksums import canonical_json_checksum
from fip_api.models import Transaction

FEATURE_SET_VERSION = "semantic-transaction-v1.0.0"
HISTORY_WINDOW_DAYS = 30
JsonScalar = str | int | bool | None


@dataclass(frozen=True)
class SemanticFeatureVector:
    amount: str
    currency: str
    occurred_hour_utc: int
    occurred_day_of_week_utc: int
    is_weekend_utc: bool
    is_off_hours_utc: bool
    is_cross_border: bool | None
    channel: str | None
    merchant_reference: str | None
    merchant_category_code: str | None
    source_country: str | None
    destination_country: str | None
    prior_transaction_count_1h: int
    prior_transaction_count_24h: int
    prior_transaction_count_30d: int
    prior_same_currency_count_30d: int
    prior_same_currency_median_amount_30d: str | None
    amount_to_median_ratio_30d: str | None
    merchant_seen_before_30d: bool | None

    def as_dict(self) -> dict[str, JsonScalar]:
        return {
            "amount": self.amount,
            "amount_to_median_ratio_30d": self.amount_to_median_ratio_30d,
            "channel": self.channel,
            "currency": self.currency,
            "destination_country": self.destination_country,
            "is_cross_border": self.is_cross_border,
            "is_off_hours_utc": self.is_off_hours_utc,
            "is_weekend_utc": self.is_weekend_utc,
            "merchant_category_code": self.merchant_category_code,
            "merchant_reference": self.merchant_reference,
            "merchant_seen_before_30d": self.merchant_seen_before_30d,
            "occurred_day_of_week_utc": self.occurred_day_of_week_utc,
            "occurred_hour_utc": self.occurred_hour_utc,
            "prior_same_currency_count_30d": self.prior_same_currency_count_30d,
            "prior_same_currency_median_amount_30d": (self.prior_same_currency_median_amount_30d),
            "prior_transaction_count_1h": self.prior_transaction_count_1h,
            "prior_transaction_count_24h": self.prior_transaction_count_24h,
            "prior_transaction_count_30d": self.prior_transaction_count_30d,
            "source_country": self.source_country,
        }


def build_semantic_features(
    transaction: Transaction,
    history: Sequence[Transaction],
) -> SemanticFeatureVector:
    occurred_at = _as_utc(transaction.occurred_at)
    window_start = occurred_at - timedelta(days=HISTORY_WINDOW_DAYS)
    eligible_history = sorted(
        (
            item
            for item in history
            if item.account_reference == transaction.account_reference
            and window_start <= _as_utc(item.occurred_at) < occurred_at
            and item.id != transaction.id
        ),
        key=lambda item: (_as_utc(item.occurred_at), item.external_transaction_id),
    )
    one_hour_start = occurred_at - timedelta(hours=1)
    one_day_start = occurred_at - timedelta(days=1)
    same_currency = [item for item in eligible_history if item.currency == transaction.currency]
    median_amount = _median([Decimal(item.amount) for item in same_currency])
    amount = Decimal(transaction.amount)
    amount_ratio = None
    if median_amount is not None and median_amount > 0:
        amount_ratio = (amount / median_amount).quantize(Decimal("0.001"), ROUND_HALF_UP)

    merchant_seen = None
    if transaction.merchant_reference is not None:
        merchant_seen = any(
            item.merchant_reference == transaction.merchant_reference for item in eligible_history
        )

    cross_border = None
    if transaction.source_country is not None and transaction.destination_country is not None:
        cross_border = transaction.source_country != transaction.destination_country

    return SemanticFeatureVector(
        amount=_money_text(amount),
        currency=transaction.currency,
        occurred_hour_utc=occurred_at.hour,
        occurred_day_of_week_utc=occurred_at.weekday(),
        is_weekend_utc=occurred_at.weekday() >= 5,
        is_off_hours_utc=occurred_at.hour < 5,
        is_cross_border=cross_border,
        channel=transaction.channel,
        merchant_reference=transaction.merchant_reference,
        merchant_category_code=transaction.merchant_category_code,
        source_country=transaction.source_country,
        destination_country=transaction.destination_country,
        prior_transaction_count_1h=sum(
            _as_utc(item.occurred_at) >= one_hour_start for item in eligible_history
        ),
        prior_transaction_count_24h=sum(
            _as_utc(item.occurred_at) >= one_day_start for item in eligible_history
        ),
        prior_transaction_count_30d=len(eligible_history),
        prior_same_currency_count_30d=len(same_currency),
        prior_same_currency_median_amount_30d=(
            _money_text(median_amount) if median_amount is not None else None
        ),
        amount_to_median_ratio_30d=(format(amount_ratio, "f") if amount_ratio else None),
        merchant_seen_before_30d=merchant_seen,
    )


def history_checksum(history: Sequence[Transaction]) -> str:
    ordered_history = sorted(
        history,
        key=lambda item: (_as_utc(item.occurred_at), item.external_transaction_id),
    )
    return canonical_json_checksum(
        [
            {
                "account_reference": item.account_reference,
                "amount": _money_text(Decimal(item.amount)),
                "channel": item.channel,
                "currency": item.currency,
                "destination_country": item.destination_country,
                "external_transaction_id": item.external_transaction_id,
                "merchant_category_code": item.merchant_category_code,
                "merchant_reference": item.merchant_reference,
                "occurred_at": _as_utc(item.occurred_at).isoformat(),
                "source_country": item.source_country,
            }
            for item in ordered_history
        ]
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01"), ROUND_HALF_UP), "f")
