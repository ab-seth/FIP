"""Add governed shadow model registry and immutable predictions.

Revision ID: 20260809_0005
Revises: 20260809_0004
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_0005"
down_revision: str | None = "20260809_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registered_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("model_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("runtime_contract", sa.String(length=48), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("feature_set_version", sa.String(length=64), nullable=False),
        sa.Column("training_dataset_id", sa.String(length=160), nullable=False),
        sa.Column("training_dataset_checksum", sa.String(length=64), nullable=False),
        sa.Column("training_data_approved", sa.Boolean(), nullable=False),
        sa.Column("operational_feature_compatible", sa.Boolean(), nullable=False),
        sa.Column("decision_threshold", sa.Numeric(precision=12, scale=10), nullable=True),
        sa.Column("evaluation_metrics", sa.JSON(), nullable=False),
        sa.Column("model_card_reference", sa.String(length=500), nullable=False),
        sa.Column("model_card_checksum", sa.String(length=64), nullable=False),
        sa.Column("registered_by_id", sa.String(length=36), nullable=False),
        sa.Column("registration_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_threshold IS NULL OR (decision_threshold >= 0 AND decision_threshold <= 1)",
            name="ck_registered_models_threshold_range",
        ),
        sa.CheckConstraint(
            "kind IN ('supervised', 'anomaly')",
            name="ck_registered_models_kind",
        ),
        sa.CheckConstraint(
            "purpose IN ('research', 'operational')",
            name="ck_registered_models_purpose",
        ),
        sa.CheckConstraint(
            "runtime_contract IN ('binary-probability-v1', 'anomaly-score-v1')",
            name="ck_registered_models_runtime_contract",
        ),
        sa.ForeignKeyConstraint(["registered_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("registration_checksum"),
        sa.UniqueConstraint("model_key", "version", name="uq_registered_model_key_version"),
    )
    op.create_index(
        "ix_registered_models_model_key",
        "registered_models",
        ["model_key"],
        unique=False,
    )
    op.create_table(
        "model_lifecycle_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("previous_event_checksum", sa.String(length=64), nullable=True),
        sa.Column("event_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('candidate', 'shadow', 'retired', 'rejected')",
            name="ck_model_lifecycle_events_from_status",
        ),
        sa.CheckConstraint(
            "sequence_number > 0",
            name="ck_model_lifecycle_events_sequence_positive",
        ),
        sa.CheckConstraint(
            "to_status IN ('candidate', 'shadow', 'retired', 'rejected')",
            name="ck_model_lifecycle_events_to_status",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_id"], ["registered_models.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_checksum"),
        sa.UniqueConstraint(
            "model_id",
            "sequence_number",
            name="uq_model_lifecycle_event_sequence",
        ),
    )
    op.create_index(
        "ix_model_lifecycle_events_model_id",
        "model_lifecycle_events",
        ["model_id"],
        unique=False,
    )
    op.create_table(
        "shadow_model_predictions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("feature_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_event_id", sa.String(length=36), nullable=False),
        sa.Column("output_schema_version", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column("would_exceed_threshold", sa.Boolean(), nullable=False),
        sa.Column("factor_contributions", sa.JSON(), nullable=False),
        sa.Column("runtime_milliseconds", sa.Integer(), nullable=False),
        sa.Column("prediction_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "runtime_milliseconds >= 0",
            name="ck_shadow_model_predictions_runtime_nonnegative",
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1",
            name="ck_shadow_model_predictions_score_range",
        ),
        sa.CheckConstraint(
            "threshold >= 0 AND threshold <= 1",
            name="ck_shadow_model_predictions_threshold_range",
        ),
        sa.ForeignKeyConstraint(
            ["authorization_event_id"],
            ["model_lifecycle_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["feature_snapshot_id"],
            ["transaction_feature_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["model_id"], ["registered_models.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prediction_checksum"),
        sa.UniqueConstraint(
            "feature_snapshot_id",
            "model_id",
            name="uq_shadow_prediction_snapshot_model",
        ),
    )
    op.create_index(
        "ix_shadow_predictions_model_id",
        "shadow_model_predictions",
        ["model_id"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_predictions_transaction_id",
        "shadow_model_predictions",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_predictions_transaction_id",
        table_name="shadow_model_predictions",
    )
    op.drop_index("ix_shadow_predictions_model_id", table_name="shadow_model_predictions")
    op.drop_table("shadow_model_predictions")
    op.drop_index("ix_model_lifecycle_events_model_id", table_name="model_lifecycle_events")
    op.drop_table("model_lifecycle_events")
    op.drop_index("ix_registered_models_model_key", table_name="registered_models")
    op.drop_table("registered_models")
