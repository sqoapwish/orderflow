from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from orderflow.modules.audit.domain import AuditFilters
from orderflow.modules.audit.models import AuditEvent


class AuditWriterProtocol(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class AuditRepositoryProtocol(AuditWriterProtocol, Protocol):
    async def get(self, event_id: UUID) -> AuditEvent | None: ...

    async def list_events(self, filters: AuditFilters) -> tuple[list[AuditEvent], int]: ...


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(event)

    async def get(self, event_id: UUID) -> AuditEvent | None:
        return await self._session.get(AuditEvent, event_id)

    async def list_events(self, filters: AuditFilters) -> tuple[list[AuditEvent], int]:
        conditions: list[ColumnElement[bool]] = []
        if filters.action is not None:
            conditions.append(AuditEvent.action == filters.action)
        if filters.actor_id is not None:
            conditions.append(AuditEvent.actor_id == filters.actor_id)
        if filters.resource_type is not None:
            conditions.append(AuditEvent.resource_type == filters.resource_type)
        if filters.resource_id is not None:
            conditions.append(AuditEvent.resource_id == filters.resource_id)
        if filters.correlation_id is not None:
            conditions.append(AuditEvent.correlation_id == filters.correlation_id)
        if filters.occurred_from is not None:
            conditions.append(AuditEvent.occurred_at >= filters.occurred_from)
        if filters.occurred_to is not None:
            conditions.append(AuditEvent.occurred_at <= filters.occurred_to)

        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(AuditEvent).where(*conditions)
                )
            )
            or 0
        )
        statement = (
            select(AuditEvent)
            .where(*conditions)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        events = list((await self._session.execute(statement)).scalars().all())
        return events, total
