from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from orderflow.infrastructure.database import Base
from orderflow.modules.audit.domain import AuditActorType


def utc_now() -> datetime:
    return datetime.now(UTC)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system')",
            name="audit_actor_type",
        ),
        CheckConstraint(
            "(actor_type = 'system' AND actor_id IS NULL) "
            "OR (actor_type = 'user' AND actor_id IS NOT NULL)",
            name="audit_actor_identity",
        ),
        CheckConstraint(
            "actor_role IS NULL OR actor_role IN ('customer', 'manager', 'admin')",
            name="audit_actor_role",
        ),
        Index("ix_audit_events_action_occurred", "action", "occurred_at"),
        Index("ix_audit_events_actor_occurred", "actor_id", "occurred_at"),
        Index(
            "ix_audit_events_resource_occurred",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
        Index("ix_audit_events_correlation_id", "correlation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_event_id: Mapped[UUID] = mapped_column(unique=True, nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_type: Mapped[AuditActorType] = mapped_column(
        Enum(
            AuditActorType,
            name="audit_actor_type",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
