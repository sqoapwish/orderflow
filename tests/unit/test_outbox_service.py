from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from orderflow.modules.outbox.domain import InboxOutcome, OutboxEventType, OutboxStatus
from orderflow.modules.outbox.errors import InboxEventConflictError
from orderflow.modules.outbox.models import OutboxEvent
from orderflow.modules.outbox.publisher import CeleryEventPublisher
from orderflow.modules.outbox.service import InboxService, OutboxDispatcher, build_outbox_event
from tests.fakes import FakeInboxRepository, FakeOutboxRepository


class SelectivePublisher:
    def __init__(self, failures: dict[UUID, int] | None = None) -> None:
        self.failures = failures or {}
        self.published: list[UUID] = []

    async def publish(self, event: OutboxEvent) -> None:
        remaining = self.failures.get(event.id, 0)
        if remaining:
            self.failures[event.id] = remaining - 1
            raise ConnectionError
        self.published.append(event.id)


class RecordingCeleryApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, Any],
        task_id: str,
        queue: str,
        headers: dict[str, str],
    ) -> object:
        self.calls.append(
            {
                "name": name,
                "kwargs": kwargs,
                "task_id": task_id,
                "queue": queue,
                "headers": headers,
            }
        )
        return object()


def event(marker: str) -> OutboxEvent:
    event_id = uuid4()
    return build_outbox_event(
        event_type=OutboxEventType.ORDER_CREATED,
        aggregate_type="order",
        aggregate_id=event_id,
        payload={"order_id": str(event_id), "marker": marker},
        deduplication_key=f"order:{event_id}:created",
    )


async def test_dispatcher_publishes_and_retries_with_exponential_delay() -> None:
    repository = FakeOutboxRepository()
    immediate = event("immediate")
    retried = event("retried")
    repository.events.extend([immediate, retried])
    publisher = SelectivePublisher({retried.id: 1})
    dispatcher = OutboxDispatcher(
        repository,
        publisher,
        batch_size=10,
        max_attempts=3,
        retry_base_seconds=5,
        retry_max_seconds=60,
    )
    now = datetime.now(UTC)

    first = await dispatcher.dispatch_batch(now=now)
    assert (first.claimed, first.published, first.retried, first.dead_lettered) == (2, 1, 1, 0)
    assert immediate.status is OutboxStatus.PUBLISHED
    assert retried.status is OutboxStatus.PENDING
    assert retried.attempts == 1
    assert retried.available_at == now + timedelta(seconds=5)
    assert retried.last_error == "ConnectionError"

    too_early = await dispatcher.dispatch_batch(now=now + timedelta(seconds=4))
    assert too_early.claimed == 0
    second = await dispatcher.dispatch_batch(now=now + timedelta(seconds=5))
    assert (second.claimed, second.published) == (1, 1)
    assert retried.status.value == OutboxStatus.PUBLISHED.value
    assert retried.last_error is None


async def test_dispatcher_dead_letters_after_maximum_attempts() -> None:
    repository = FakeOutboxRepository()
    failed = event("dead")
    repository.add(failed)
    publisher = SelectivePublisher({failed.id: 2})
    dispatcher = OutboxDispatcher(
        repository,
        publisher,
        batch_size=1,
        max_attempts=2,
        retry_base_seconds=3,
        retry_max_seconds=30,
    )
    now = datetime.now(UTC)

    first = await dispatcher.dispatch_batch(now=now)
    second = await dispatcher.dispatch_batch(now=now + timedelta(seconds=3))

    assert first.retried == 1
    assert second.dead_lettered == 1
    assert failed.status is OutboxStatus.DEAD_LETTER
    assert failed.attempts == 2
    assert repository.commits == 2


async def test_inbox_is_idempotent_and_rejects_mutated_duplicate() -> None:
    repository = FakeInboxRepository()
    service = InboxService(repository)
    event_id = uuid4()
    aggregate_id = uuid4()

    async def consume(payload: dict[str, Any]) -> InboxOutcome:
        return await service.consume(
            event_id=event_id,
            event_type="order.created",
            aggregate_type="order",
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at="2026-08-17T12:00:00+00:00",
            correlation_id="correlation-42",
        )

    first = await consume({"order_id": str(aggregate_id)})
    duplicate = await consume({"order_id": str(aggregate_id)})

    assert first is InboxOutcome.PROCESSED
    assert duplicate is InboxOutcome.DUPLICATE
    with pytest.raises(InboxEventConflictError):
        await consume({"order_id": "mutated"})
    assert repository.rollbacks == 1


async def test_celery_publisher_uses_stable_task_id_and_domain_event_queue() -> None:
    app = RecordingCeleryApp()
    outbox_event = event("publish")

    await CeleryEventPublisher(app).publish(outbox_event)

    assert len(app.calls) == 1
    call = app.calls[0]
    assert call["name"] == "orderflow.events.consume"
    assert call["task_id"] == str(outbox_event.id)
    assert call["queue"] == "domain-events"
    kwargs = cast(dict[str, Any], call["kwargs"])
    assert kwargs["event_id"] == str(outbox_event.id)
