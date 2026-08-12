from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from orderflow.infrastructure.database import Base
from orderflow.modules.payments.domain import (
    PaymentEventType,
    PaymentStatus,
    RefundStatus,
    WebhookOutcome,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("provider = 'mock'", name="payment_provider"),
        CheckConstraint("amount_minor > 0", name="payment_positive_amount"),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name="payment_currency_format",
        ),
        CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'cancelled', 'refunded')",
            name="payment_status",
        ),
        UniqueConstraint(
            "customer_id",
            "idempotency_key",
            name="uq_payments_customer_idempotency_key",
        ),
        Index("ix_payments_customer_created", "customer_id", "created_at"),
        Index("ix_payments_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    checkout_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="payment_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('payment.succeeded', 'payment.failed')",
            name="payment_webhook_event_type",
        ),
        CheckConstraint(
            "outcome IN ('processed', 'ignored')",
            name="payment_webhook_outcome",
        ),
        Index("ix_payment_webhook_events_payment_created", "payment_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider_event_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[PaymentEventType] = mapped_column(
        Enum(
            PaymentEventType,
            name="payment_event_type",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[WebhookOutcome] = mapped_column(
        Enum(
            WebhookOutcome,
            name="webhook_outcome",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="payment_refund_positive_amount"),
        CheckConstraint(
            "char_length(currency) = 3 AND currency = upper(currency)",
            name="payment_refund_currency_format",
        ),
        CheckConstraint("status IN ('succeeded')", name="payment_refund_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"),
        unique=True,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_refund_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        Enum(
            RefundStatus,
            name="refund_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
