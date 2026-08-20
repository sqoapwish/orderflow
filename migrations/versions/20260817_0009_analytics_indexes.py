"""Add reporting index for operational analytics.

Revision ID: 20260817_0009
Revises: 20260817_0008
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0009"
down_revision: str | Sequence[str] | None = "20260817_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_outbox_events_analytics",
        "outbox_events",
        ["event_type", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_analytics", table_name="outbox_events")
