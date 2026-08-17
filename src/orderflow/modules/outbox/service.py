import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

import structlog

from orderflow.core.correlation import get_correlation_id
from orderflow.modules.outbox.domain import InboxOutcome, OutboxEventType, OutboxStatus
from orderflow.modules.outbox.errors import InboxEventConflictError
from orderflow.modules.outbox.models import InboxEvent, OutboxEvent
from orderflow.modules.outbox.repository import InboxRepositoryProtocol, OutboxRepositoryProtocol


class EventPublisherProtocol(Protocol):
    async def publish(self, event: OutboxEvent) -> None: ...


class DomainEventHandlerProtocol(Protocol):
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
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DispatchSummary:
    claimed: int
    published: int
    retried: int
    dead_lettered: int


def build_outbox_event(
    *,
    event_type: OutboxEventType,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
    deduplication_key: str,
) -> OutboxEvent:
    now = datetime.now(UTC)
    return OutboxEvent(
        id=uuid4(),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        deduplication_key=deduplication_key,
        correlation_id=get_correlation_id(),
        status=OutboxStatus.PENDING,
        attempts=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )


class OutboxDispatcher:
    def __init__(
        self,
        repository: OutboxRepositoryProtocol,
        publisher: EventPublisherProtocol,
        *,
        batch_size: int,
        max_attempts: int,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._logger = structlog.get_logger()

    async def dispatch_batch(self, *, now: datetime | None = None) -> DispatchSummary:
        resolved_now = now or datetime.now(UTC)
        published = 0
        retried = 0
        dead_lettered = 0
        try:
            events = await self._repository.claim_pending(
                now=resolved_now,
                limit=self._batch_size,
            )
            for event in events:
                try:
                    await self._publisher.publish(event)
                except Exception as exc:
                    event.attempts += 1
                    event.last_error = type(exc).__name__[:255]
                    if event.attempts >= self._max_attempts:
                        event.status = OutboxStatus.DEAD_LETTER
                        dead_lettered += 1
                        self._logger.error(
                            "outbox_event_dead_lettered",
                            event_id=str(event.id),
                            event_type=event.event_type.value,
                            attempts=event.attempts,
                            error_type=event.last_error,
                            correlation_id=event.correlation_id,
                        )
                    else:
                        event.available_at = resolved_now + timedelta(
                            seconds=self._retry_delay(event.attempts)
                        )
                        retried += 1
                        self._logger.warning(
                            "outbox_event_retry_scheduled",
                            event_id=str(event.id),
                            event_type=event.event_type.value,
                            attempts=event.attempts,
                            available_at=event.available_at.isoformat(),
                            error_type=event.last_error,
                            correlation_id=event.correlation_id,
                        )
                else:
                    event.status = OutboxStatus.PUBLISHED
                    event.published_at = resolved_now
                    event.last_error = None
                    published += 1
                    self._logger.info(
                        "outbox_event_published",
                        event_id=str(event.id),
                        event_type=event.event_type.value,
                        attempts=event.attempts,
                        correlation_id=event.correlation_id,
                    )
            await self._repository.commit()
            return DispatchSummary(
                claimed=len(events),
                published=published,
                retried=retried,
                dead_lettered=dead_lettered,
            )
        except Exception:
            await self._repository.rollback()
            raise

    def _retry_delay(self, attempts: int) -> int:
        multiplier = 1 << max(attempts - 1, 0)
        return min(
            self._retry_base_seconds * multiplier,
            self._retry_max_seconds,
        )


class InboxService:
    def __init__(
        self,
        repository: InboxRepositoryProtocol,
        handler: DomainEventHandlerProtocol | None = None,
    ) -> None:
        self._repository = repository
        self._handler = handler
        self._logger = structlog.get_logger()

    async def consume(
        self,
        *,
        event_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        occurred_at: str,
        correlation_id: str | None,
    ) -> InboxOutcome:
        payload_hash = self._payload_hash(
            event_id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at=occurred_at,
        )
        event = InboxEvent(
            event_id=event_id,
            event_type=event_type,
            payload_hash=payload_hash,
            correlation_id=correlation_id,
            processed_at=datetime.now(UTC),
        )
        try:
            if await self._repository.try_add(event):
                if self._handler is not None:
                    await self._handler.handle(
                        event_id=event_id,
                        event_type=event_type,
                        aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id,
                        payload=payload,
                        occurred_at=occurred_at,
                        correlation_id=correlation_id,
                    )
                await self._repository.commit()
                self._logger.info(
                    "domain_event_consumed",
                    event_id=str(event_id),
                    event_type=event_type,
                    aggregate_type=aggregate_type,
                    aggregate_id=str(aggregate_id),
                    correlation_id=correlation_id,
                )
                return InboxOutcome.PROCESSED

            existing = await self._repository.get(event_id)
            if existing is None or existing.payload_hash != payload_hash:
                raise InboxEventConflictError
            await self._repository.commit()
            self._logger.info(
                "domain_event_duplicate_ignored",
                event_id=str(event_id),
                event_type=event_type,
                correlation_id=correlation_id,
            )
            return InboxOutcome.DUPLICATE
        except Exception:
            await self._repository.rollback()
            raise

    @staticmethod
    def _payload_hash(
        *,
        event_id: UUID,
        event_type: str,
        aggregate_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        occurred_at: str,
    ) -> str:
        canonical = json.dumps(
            {
                "aggregate_id": str(aggregate_id),
                "aggregate_type": aggregate_type,
                "event_id": str(event_id),
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(canonical).hexdigest()
