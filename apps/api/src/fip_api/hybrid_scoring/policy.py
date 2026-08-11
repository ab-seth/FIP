from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fip_api.models import RuleRiskLevel

HYBRID_POLICY_VERSION = "hybrid-risk-v1.0.0"
EVIDENCE_SCHEMA_VERSION = "hybrid-risk-evidence-v1.0.0"
SCORE_QUANTUM = Decimal("0.0001")


@dataclass(frozen=True)
class HybridRiskPolicy:
    version: str
    rules_weight: Decimal
    supervised_weight: Decimal
    anomaly_weight: Decimal
    medium_minimum: Decimal
    high_minimum: Decimal

    def risk_level(self, score: Decimal) -> RuleRiskLevel:
        if score >= self.high_minimum:
            return RuleRiskLevel.HIGH
        if score >= self.medium_minimum:
            return RuleRiskLevel.MEDIUM
        return RuleRiskLevel.LOW

    def evidence_facts(self) -> dict[str, object]:
        return {
            "version": self.version,
            "weights": {
                "rules": decimal_text(self.rules_weight),
                "supervised": decimal_text(self.supervised_weight),
                "anomaly": decimal_text(self.anomaly_weight),
            },
            "risk_bands": {
                "low": {"minimum": "0", "maximum_exclusive": "40"},
                "medium": {"minimum": "40", "maximum_exclusive": "70"},
                "high": {"minimum": "70", "maximum_inclusive": "100"},
            },
            "score_range": {"minimum": "0", "maximum": "100"},
        }


DEFAULT_HYBRID_POLICY = HybridRiskPolicy(
    version=HYBRID_POLICY_VERSION,
    rules_weight=Decimal("0.2"),
    supervised_weight=Decimal("0.6"),
    anomaly_weight=Decimal("0.2"),
    medium_minimum=Decimal("40"),
    high_minimum=Decimal("70"),
)


def decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")
