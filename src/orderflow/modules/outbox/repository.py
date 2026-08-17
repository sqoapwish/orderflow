from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.outbox.domain import OutboxStatus
from orderflow.modules.outbox.models import InboxEvent, OutboxEvent


class OutboxWriterProtocol(Protocol):
    def add(self, event: OutboxEvent) -> None: ...


class OutboxRepositoryProtocol(OutboxWriterProtocol, Protocol):
    async def claim_pending(self, *, now: datetime, limit: int) -> list[OutboxEvent]: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InboxRepositoryProtocol(Protocol):
    async def try_add(self, event: InboxEvent) -> bool: ...

    async def get(self, event_id: UUID) -> InboxEvent | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> None:
        self._session.add(event)

    async def claim_pending(self, *, now: datetime, limit: int) -> list[OutboxEvent]:
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxStatus.PENDING,
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class InboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_add(self, event: InboxEvent) -> bool:
        statement = (
            insert(InboxEvent)
            .values(
                event_id=event.event_id,
                event_type=event.event_type,
                payload_hash=event.payload_hash,
                correlation_id=event.correlation_id,
                processed_at=event.processed_at,
            )
            .on_conflict_do_nothing(index_elements=[InboxEvent.event_id])
            .returning(InboxEvent.event_id)
        )
        return (await self._session.scalar(statement)) is not None

    async def get(self, event_id: UUID) -> InboxEvent | None:
        return await self._session.get(InboxEvent, event_id)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
