"""Add immutable audit history.

Revision ID: 20260817_0008
Revises: 20260817_0007
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0008"
down_revision: str | Sequence[str] | None = "20260817_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum(
                "user",
                "system",
                name="audit_actor_type",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(actor_type = 'system' AND actor_id IS NULL) "
            "OR (actor_type = 'user' AND actor_id IS NOT NULL)",
            name=op.f("ck_audit_events_audit_actor_identity"),
        ),
        sa.CheckConstraint(
            "actor_role IS NULL OR actor_role IN ('customer', 'manager', 'admin')",
            name=op.f("ck_audit_events_audit_actor_role"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'system')",
            name=op.f("ck_audit_events_audit_actor_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint(
            "source_event_id",
            name=op.f("uq_audit_events_source_event_id"),
        ),
    )
    op.create_index(
        "ix_audit_events_action_occurred",
        "audit_events",
        ["action", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_actor_occurred",
        "audit_events",
        ["actor_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_correlation_id",
        "audit_events",
        ["correlation_id"],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_resource_occurred",
        "audit_events",
        ["resource_type", "resource_id", "occurred_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION prevent_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation()")
    op.drop_index("ix_audit_events_resource_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_action_occurred", table_name="audit_events")
    op.drop_table("audit_events")
