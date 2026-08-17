from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orderflow.infrastructure.database import Base
from orderflow.modules.outbox.domain import OutboxEventType, OutboxStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="outbox_attempts_nonnegative"),
        CheckConstraint(
            "event_type IN ('order.created', 'order.cancelled', 'payment.succeeded', "
            "'payment.failed', 'payment.refunded')",
            name="outbox_event_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'published', 'dead_letter')",
            name="outbox_status",
        ),
        Index(
            "ix_outbox_events_dispatch",
            "status",
            "available_at",
            "created_at",
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_outbox_events_analytics", "event_type", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[OutboxEventType] = mapped_column(
        Enum(
            OutboxEventType,
            name="outbox_event_type",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(
            OutboxStatus,
            name="outbox_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
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


class InboxEvent(Base):
    __tablename__ = "inbox_events"

    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
