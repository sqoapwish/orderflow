import asyncio
from typing import Any, Literal
from uuid import UUID

from celery import shared_task

from orderflow.core.config import Settings
from orderflow.core.logging import configure_logging
from orderflow.infrastructure.database import Database
from orderflow.modules.outbox.publisher import CeleryEventPublisher
from orderflow.modules.outbox.repository import InboxRepository, OutboxRepository
from orderflow.modules.outbox.service import InboxService, OutboxDispatcher
from orderflow.workers.celery_app import celery_app


@shared_task(name="orderflow.health.ping")  # type: ignore[untyped-decorator]
def ping() -> dict[str, Literal["pong"]]:
    """A lightweight task used to verify worker registration."""
    return {"status": "pong"}


@shared_task(name="orderflow.outbox.dispatch")  # type: ignore[untyped-decorator]
def dispatch_outbox_events() -> dict[str, int]:
    return asyncio.run(_dispatch_outbox_events())


async def _dispatch_outbox_events() -> dict[str, int]:
    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            dispatcher = OutboxDispatcher(
                OutboxRepository(session),
                CeleryEventPublisher(celery_app),
                batch_size=settings.outbox_dispatch_batch_size,
                max_attempts=settings.outbox_max_attempts,
                retry_base_seconds=settings.outbox_retry_base_seconds,
                retry_max_seconds=settings.outbox_retry_max_seconds,
            )
            summary = await dispatcher.dispatch_batch()
            return {
                "claimed": summary.claimed,
                "published": summary.published,
                "retried": summary.retried,
                "dead_lettered": summary.dead_lettered,
            }
    finally:
        await database.close()


@shared_task(name="orderflow.events.consume")  # type: ignore[untyped-decorator]
def consume_domain_event(
    *,
    event_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
    occurred_at: str,
    correlation_id: str | None,
) -> dict[str, str]:
    outcome = asyncio.run(
        _consume_domain_event(
            event_id=UUID(event_id),
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=UUID(aggregate_id),
            payload=payload,
            occurred_at=occurred_at,
            correlation_id=correlation_id,
        )
    )
    return {"status": outcome}


async def _consume_domain_event(
    *,
    event_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, Any],
    occurred_at: str,
    correlation_id: str | None,
) -> str:
    settings = Settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    try:
        async with database.session_factory() as session:
            outcome = await InboxService(InboxRepository(session)).consume(
                event_id=event_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
                occurred_at=occurred_at,
                correlation_id=correlation_id,
            )
            return outcome.value
    finally:
        await database.close()
