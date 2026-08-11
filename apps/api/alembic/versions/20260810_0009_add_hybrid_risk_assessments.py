"""Add immutable hybrid risk evidence assessments.

Revision ID: 20260810_0009
Revises: 20260809_0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0009"
down_revision: str | None = "20260809_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hybrid_risk_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("rule_assessment_id", sa.String(length=36), nullable=False),
        sa.Column("supervised_prediction_id", sa.String(length=36), nullable=False),
        sa.Column("anomaly_prediction_id", sa.String(length=36), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_schema_version", sa.String(length=64), nullable=False),
        sa.Column("rules_weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("supervised_weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("anomaly_weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("rule_score", sa.Integer(), nullable=False),
        sa.Column("supervised_score", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("anomaly_score", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("combined_score", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("evidence_package", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("assessment_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rules_weight >= 0 AND rules_weight <= 1",
            name="ck_hybrid_risk_rules_weight_range",
        ),
        sa.CheckConstraint(
            "supervised_weight >= 0 AND supervised_weight <= 1",
            name="ck_hybrid_risk_supervised_weight_range",
        ),
        sa.CheckConstraint(
            "anomaly_weight >= 0 AND anomaly_weight <= 1",
            name="ck_hybrid_risk_anomaly_weight_range",
        ),
        sa.CheckConstraint(
            "rules_weight + supervised_weight + anomaly_weight = 1",
            name="ck_hybrid_risk_weights_total",
        ),
        sa.CheckConstraint(
            "rule_score >= 0 AND rule_score <= 100",
            name="ck_hybrid_risk_rule_score_range",
        ),
        sa.CheckConstraint(
            "supervised_score >= 0 AND supervised_score <= 1",
            name="ck_hybrid_risk_supervised_score_range",
        ),
        sa.CheckConstraint(
            "anomaly_score >= 0 AND anomaly_score <= 1",
            name="ck_hybrid_risk_anomaly_score_range",
        ),
        sa.CheckConstraint(
            "combined_score >= 0 AND combined_score <= 100",
            name="ck_hybrid_risk_combined_score_range",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="ck_hybrid_risk_level",
        ),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["transaction_feature_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_assessment_id"],
            ["transaction_rule_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supervised_prediction_id"],
            ["shadow_model_predictions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["anomaly_prediction_id"],
            ["shadow_model_predictions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_checksum"),
        sa.UniqueConstraint(
            "feature_snapshot_id",
            "rule_assessment_id",
            "policy_version",
            "supervised_prediction_id",
            "anomaly_prediction_id",
            name="uq_hybrid_risk_evidence_set",
        ),
    )
    op.create_index(
        "ix_hybrid_risk_transaction_id",
        "hybrid_risk_assessments",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hybrid_risk_transaction_id",
        table_name="hybrid_risk_assessments",
    )
    op.drop_table("hybrid_risk_assessments")
