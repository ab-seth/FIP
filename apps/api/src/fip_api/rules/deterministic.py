from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fip_api.features import SemanticFeatureVector
from fip_api.models import RuleRiskLevel

RULESET_VERSION = "semantic-rules-v1.0.0"
RISK_BAND_VERSION = "rule-risk-bands-v1.0.0"
EVALUATED_RULE_COUNT = 6
ELEVATED_REVIEW_MCCS = frozenset({"4829", "6010", "6011", "6051", "6211", "6540", "7995"})
JsonScalar = str | int | bool | None


@dataclass(frozen=True)
class RuleTrigger:
    rule_id: str
    title: str
    contribution_points: int
    evidence: dict[str, JsonScalar]

    def as_dict(self) -> dict[str, object]:
        return {
            "contribution_points": self.contribution_points,
            "evidence": self.evidence,
            "rule_id": self.rule_id,
            "title": self.title,
        }


@dataclass(frozen=True)
class RuleEvaluation:
    rule_score: int
    risk_level: RuleRiskLevel
    triggered_rules: tuple[RuleTrigger, ...]


def evaluate_rules(features: SemanticFeatureVector) -> RuleEvaluation:
    triggers: list[RuleTrigger] = []

    if features.prior_transaction_count_1h >= 3:
        triggers.append(
            RuleTrigger(
                rule_id="R001_RAPID_ACCOUNT_ACTIVITY",
                title="Rapid account activity",
                contribution_points=25,
                evidence={
                    "prior_transaction_count_1h": features.prior_transaction_count_1h,
                    "threshold": 3,
                },
            )
        )

    amount_ratio = (
        Decimal(features.amount_to_median_ratio_30d)
        if features.amount_to_median_ratio_30d is not None
        else None
    )
    if (
        features.prior_same_currency_count_30d >= 5
        and amount_ratio is not None
        and amount_ratio >= Decimal(5)
    ):
        triggers.append(
            RuleTrigger(
                rule_id="R002_AMOUNT_SPIKE",
                title="Amount materially exceeds the account baseline",
                contribution_points=25,
                evidence={
                    "amount": features.amount,
                    "amount_to_median_ratio_30d": features.amount_to_median_ratio_30d,
                    "currency": features.currency,
                    "minimum_history_count": 5,
                    "prior_same_currency_count_30d": (features.prior_same_currency_count_30d),
                    "ratio_threshold": "5.000",
                },
            )
        )

    if features.prior_transaction_count_30d >= 5 and features.merchant_seen_before_30d is False:
        triggers.append(
            RuleTrigger(
                rule_id="R003_NEW_MERCHANT",
                title="Merchant not seen in the account history window",
                contribution_points=15,
                evidence={
                    "merchant_seen_before_30d": False,
                    "merchant_reference": features.merchant_reference,
                    "minimum_history_count": 5,
                    "prior_transaction_count_30d": features.prior_transaction_count_30d,
                },
            )
        )

    card_not_present = features.channel == "card_not_present"
    if features.is_cross_border is True and card_not_present:
        triggers.append(
            RuleTrigger(
                rule_id="R004_CROSS_BORDER_CARD_NOT_PRESENT",
                title="Cross-border card-not-present transaction",
                contribution_points=15,
                evidence={
                    "channel": features.channel,
                    "destination_country": features.destination_country,
                    "is_cross_border": True,
                    "source_country": features.source_country,
                },
            )
        )

    if features.merchant_category_code in ELEVATED_REVIEW_MCCS:
        triggers.append(
            RuleTrigger(
                rule_id="R005_ELEVATED_REVIEW_MCC",
                title="Merchant category selected for elevated review",
                contribution_points=10,
                evidence={"merchant_category_code": features.merchant_category_code},
            )
        )

    if features.is_off_hours_utc and card_not_present:
        triggers.append(
            RuleTrigger(
                rule_id="R006_OFF_HOURS_CARD_NOT_PRESENT",
                title="Card-not-present activity during UTC off-hours",
                contribution_points=10,
                evidence={
                    "channel": features.channel,
                    "occurred_hour_utc": features.occurred_hour_utc,
                    "off_hours_utc": "00:00-04:59",
                },
            )
        )

    score = sum(trigger.contribution_points for trigger in triggers)
    return RuleEvaluation(
        rule_score=score,
        risk_level=_risk_level(score),
        triggered_rules=tuple(triggers),
    )


def _risk_level(score: int) -> RuleRiskLevel:
    if score >= 70:
        return RuleRiskLevel.HIGH
    if score >= 40:
        return RuleRiskLevel.MEDIUM
    return RuleRiskLevel.LOW
