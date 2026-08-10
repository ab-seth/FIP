from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fip_api.features import FEATURE_SET_VERSION, build_semantic_features, history_checksum
from fip_api.models import RuleRiskLevel, Transaction
from fip_api.rules import RISK_BAND_VERSION, RULESET_VERSION, evaluate_rules


def transaction(
    transaction_id: str,
    *,
    occurred_at: datetime,
    amount: str = "100.00",
    currency: str = "USD",
    merchant_reference: str | None = "MER-BASE",
    merchant_category_code: str | None = "5411",
    channel: str | None = "card_present",
    source_country: str | None = "RW",
    destination_country: str | None = "RW",
) -> Transaction:
    return Transaction(
        id=transaction_id,
        external_transaction_id=f"EXT-{transaction_id}",
        occurred_at=occurred_at,
        amount=Decimal(amount),
        currency=currency,
        account_reference="ACC-1",
        merchant_reference=merchant_reference,
        merchant_category_code=merchant_category_code,
        channel=channel,
        source_country=source_country,
        destination_country=destination_country,
        ingestion_batch_id="BATCH-1",
        source_row_number=1,
    )


def test_semantic_features_ignore_future_events_and_preserve_currency_context() -> None:
    occurred_at = datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    history = [
        transaction(
            f"TX-{index}",
            occurred_at=occurred_at - timedelta(minutes=10 * (index + 1)),
            amount="100.00",
        )
        for index in range(5)
    ]
    history.extend(
        [
            transaction(
                "TX-EUR",
                occurred_at=occurred_at - timedelta(minutes=5),
                amount="900.00",
                currency="EUR",
            ),
            transaction(
                "TX-FUTURE",
                occurred_at=occurred_at + timedelta(minutes=1),
                amount="1.00",
            ),
        ]
    )
    current = transaction(
        "TX-CURRENT",
        occurred_at=occurred_at,
        amount="600.00",
        merchant_reference="MER-NEW",
        merchant_category_code="6011",
        channel="card_not_present",
        destination_country="KE",
    )

    features = build_semantic_features(current, history)

    assert FEATURE_SET_VERSION == "semantic-transaction-v1.0.0"
    assert features.prior_transaction_count_1h == 6
    assert features.prior_transaction_count_30d == 6
    assert features.prior_same_currency_count_30d == 5
    assert features.prior_same_currency_median_amount_30d == "100.00"
    assert features.amount_to_median_ratio_30d == "6.000"
    assert features.merchant_seen_before_30d is False
    assert features.is_cross_border is True
    assert features.is_off_hours_utc is True


def test_rule_evaluation_is_explainable_and_bounded() -> None:
    occurred_at = datetime(2026, 8, 9, 3, 30, tzinfo=UTC)
    history = [
        transaction(
            f"TX-{index}",
            occurred_at=occurred_at - timedelta(minutes=10 * (index + 1)),
        )
        for index in range(5)
    ]
    current = transaction(
        "TX-CURRENT",
        occurred_at=occurred_at,
        amount="600.00",
        merchant_reference="MER-NEW",
        merchant_category_code="6011",
        channel="card_not_present",
        destination_country="KE",
    )

    evaluation = evaluate_rules(build_semantic_features(current, history))

    assert RULESET_VERSION == "semantic-rules-v1.0.0"
    assert RISK_BAND_VERSION == "rule-risk-bands-v1.0.0"
    assert evaluation.rule_score == 100
    assert evaluation.risk_level is RuleRiskLevel.HIGH
    assert [trigger.rule_id for trigger in evaluation.triggered_rules] == [
        "R001_RAPID_ACCOUNT_ACTIVITY",
        "R002_AMOUNT_SPIKE",
        "R003_NEW_MERCHANT",
        "R004_CROSS_BORDER_CARD_NOT_PRESENT",
        "R005_ELEVATED_REVIEW_MCC",
        "R006_OFF_HOURS_CARD_NOT_PRESENT",
    ]
    assert (
        sum(trigger.contribution_points for trigger in evaluation.triggered_rules)
        == evaluation.rule_score
    )


def test_rule_risk_bands_include_medium_review_priority() -> None:
    occurred_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    history = [
        transaction(
            f"TX-{index}",
            occurred_at=occurred_at - timedelta(minutes=10 * (index + 1)),
        )
        for index in range(5)
    ]
    current = transaction(
        "TX-CURRENT",
        occurred_at=occurred_at,
        merchant_reference="MER-NEW",
    )

    evaluation = evaluate_rules(build_semantic_features(current, history))

    assert evaluation.rule_score == 40
    assert evaluation.risk_level is RuleRiskLevel.MEDIUM


def test_history_checksum_is_stable_across_input_order() -> None:
    occurred_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    first = transaction("TX-1", occurred_at=occurred_at - timedelta(hours=2))
    second = transaction("TX-2", occurred_at=occurred_at - timedelta(hours=1))

    assert history_checksum([first, second]) == history_checksum([second, first])

    database_replay = transaction("DB-REPLAY", occurred_at=first.occurred_at)
    database_replay.external_transaction_id = first.external_transaction_id
    assert history_checksum([first]) == history_checksum([database_replay])
