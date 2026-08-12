"""Add Mock Payment lifecycle, signed webhook events, and refunds.

Revision ID: 20260812_0006
Revises: 20260812_0005
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0006"
down_revision: str | Sequence[str] | None = "20260812_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_order_status"),
        "orders",
        "status IN ('pending_payment', 'paid', 'payment_failed', 'cancelled', 'refunded')",
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_payment_id", sa.String(length=64), nullable=False),
        sa.Column("checkout_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "succeeded",
                "failed",
                "cancelled",
                "refunded",
                name="payment_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider = 'mock'",
            name=op.f("ck_payments_payment_provider"),
        ),
        sa.CheckConstraint(
            "amount_minor > 0",
            name=op.f("ck_payments_payment_positive_amount"),
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name=op.f("ck_payments_payment_currency_format"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'cancelled', 'refunded')",
            name=op.f("ck_payments_payment_status"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name="fk_payments_order_id_orders",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name="fk_payments_customer_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("order_id", name="uq_payments_order_id"),
        sa.UniqueConstraint("provider_payment_id", name="uq_payments_provider_payment_id"),
        sa.UniqueConstraint(
            "customer_id",
            "idempotency_key",
            name="uq_payments_customer_idempotency_key",
        ),
    )
    op.create_index(
        "ix_payments_customer_created",
        "payments",
        ["customer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_payments_status_created",
        "payments",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "payment.succeeded",
                "payment.failed",
                name="payment_event_type",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "processed",
                "ignored",
                name="webhook_outcome",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('payment.succeeded', 'payment.failed')",
            name=op.f("ck_payment_webhook_events_payment_webhook_event_type"),
        ),
        sa.CheckConstraint(
            "outcome IN ('processed', 'ignored')",
            name=op.f("ck_payment_webhook_events_payment_webhook_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_payment_webhook_events_payment_id_payments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_webhook_events"),
        sa.UniqueConstraint(
            "provider_event_id",
            name="uq_payment_webhook_events_provider_event_id",
        ),
    )
    op.create_index(
        "ix_payment_webhook_events_payment_created",
        "payment_webhook_events",
        ["payment_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("provider_refund_id", sa.String(length=64), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "succeeded",
                name="refund_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_minor > 0",
            name=op.f("ck_payment_refunds_payment_refund_positive_amount"),
        ),
        sa.CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name=op.f("ck_payment_refunds_payment_refund_currency_format"),
        ),
        sa.CheckConstraint(
            "status IN ('succeeded')",
            name=op.f("ck_payment_refunds_payment_refund_status"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["payments.id"],
            name="fk_payment_refunds_payment_id_payments",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_payment_refunds_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_refunds"),
        sa.UniqueConstraint("payment_id", name="uq_payment_refunds_payment_id"),
        sa.UniqueConstraint(
            "provider_refund_id",
            name="uq_payment_refunds_provider_refund_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("payment_refunds")
    op.drop_index(
        "ix_payment_webhook_events_payment_created",
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")
    op.drop_index("ix_payments_status_created", table_name="payments")
    op.drop_index("ix_payments_customer_created", table_name="payments")
    op.drop_table("payments")

    op.drop_constraint(op.f("ck_orders_order_status"), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_order_status"),
        "orders",
        "status IN ('pending_payment')",
    )
