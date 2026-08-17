from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Any
from uuid import UUID, uuid4

from orderflow.modules.audit.domain import AuditActorType, AuditFilters
from orderflow.modules.audit.errors import AuditEventNotFoundError, InvalidAuditTimeRangeError
from orderflow.modules.audit.models import AuditEvent
from orderflow.modules.audit.repository import AuditRepositoryProtocol, AuditWriterProtocol

_SAFE_DETAIL_FIELDS: dict[str, frozenset[str]] = {
    "order.created": frozenset({"order_number", "status", "total_minor", "currency", "item_count"}),
    "order.cancelled": frozenset({"status", "payment_id"}),
    "payment.succeeded": frozenset(
        {
            "order_id",
            "amount_minor",
            "currency",
            "status",
            "order_status",
            "provider_event_id",
        }
    ),
    "payment.failed": frozenset(
        {
            "order_id",
            "amount_minor",
            "currency",
            "status",
            "order_status",
            "failure_code",
            "provider_event_id",
        }
    ),
    "payment.refunded": frozenset({"order_id", "refund_id", "amount_minor", "currency", "status"}),
}
_USER_ACTIONS = frozenset({"order.created", "order.cancelled", "payment.refunded"})
_ALLOWED_ROLES = frozenset({"customer", "manager", "admin"})


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: list[AuditEvent]
    total: int
    page: int
    page_size: int
    total_pages: int


class AuditService:
    def __init__(self, repository: AuditRepositoryProtocol) -> None:
        self._repository = repository

    async def list_events(self, filters: AuditFilters) -> AuditPage:
        if (
            filters.occurred_from is not None
            and filters.occurred_to is not None
            and filters.occurred_from > filters.occurred_to
        ):
            raise InvalidAuditTimeRangeError
        items, total = await self._repository.list_events(filters)
        return AuditPage(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def get_event(self, event_id: UUID) -> AuditEvent:
        event = await self._repository.get(event_id)
        if event is None:
            raise AuditEventNotFoundError
        return event


class AuditDomainEventHandler:
    def __init__(self, repository: AuditWriterProtocol) -> None:
        self._repository = repository

    async def handle(
        self,
        *,
        event_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        occurred_at: str,
        correlation_id: str | None,
    ) -> None:
        actor_type, actor_id, actor_role = self._actor(event_type, payload)
        safe_fields = _SAFE_DETAIL_FIELDS.get(event_type, frozenset())
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                source_event_id=event_id,
                action=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_role=actor_role,
                resource_type=aggregate_type,
                resource_id=aggregate_id,
                correlation_id=correlation_id,
                details={key: payload[key] for key in safe_fields if key in payload},
                occurred_at=self._parse_occurred_at(occurred_at),
                recorded_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _actor(
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[AuditActorType, UUID | None, str | None]:
        if event_type not in _USER_ACTIONS:
            return AuditActorType.SYSTEM, None, None
        raw_actor_id = payload.get("actor_id") or payload.get("customer_id")
        actor_id = UUID(str(raw_actor_id))
        raw_role = payload.get("actor_role")
        actor_role = raw_role if isinstance(raw_role, str) and raw_role in _ALLOWED_ROLES else None
        if actor_role is None and event_type == "order.created":
            actor_role = "customer"
        return AuditActorType.USER, actor_id, actor_role

    @staticmethod
    def _parse_occurred_at(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
