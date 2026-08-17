import asyncio
from typing import Any, Protocol

from orderflow.modules.outbox.models import OutboxEvent


class CelerySendProtocol(Protocol):
    def send_task(
        self,
        name: str,
        *,
        kwargs: dict[str, Any],
        task_id: str,
        queue: str,
        headers: dict[str, str],
    ) -> object: ...


class CeleryEventPublisher:
    def __init__(self, app: CelerySendProtocol) -> None:
        self._app = app

    async def publish(self, event: OutboxEvent) -> None:
        correlation_id = event.correlation_id or str(event.id)
        await asyncio.to_thread(
            self._app.send_task,
            "orderflow.events.consume",
            kwargs={
                "event_id": str(event.id),
                "event_type": event.event_type.value,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "payload": event.payload,
                "occurred_at": event.created_at.isoformat(),
                "correlation_id": event.correlation_id,
            },
            task_id=str(event.id),
            queue="domain-events",
            headers={"correlation_id": correlation_id},
        )
