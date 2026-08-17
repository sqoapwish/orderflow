from datetime import UTC, datetime

from sqlalchemy import func, select

from orderflow.core.metrics import OutboxMetricsSnapshot
from orderflow.infrastructure.database import Database
from orderflow.modules.outbox.domain import OutboxStatus
from orderflow.modules.outbox.models import OutboxEvent


class DatabaseOutboxMetricsProvider:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def snapshot(self) -> OutboxMetricsSnapshot:
        async with self._database.session_factory() as session:
            status_rows = (
                await session.execute(
                    select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)
                )
            ).all()
            counts = {
                status if isinstance(status, OutboxStatus) else OutboxStatus(status): int(count)
                for status, count in status_rows
            }
            delivery_attempts = int(
                (await session.scalar(select(func.coalesce(func.sum(OutboxEvent.attempts), 0))))
                or 0
            )
            oldest_pending = await session.scalar(
                select(func.min(OutboxEvent.created_at)).where(
                    OutboxEvent.status == OutboxStatus.PENDING
                )
            )
        oldest_age = 0.0
        if oldest_pending is not None:
            oldest_age = max((datetime.now(UTC) - oldest_pending).total_seconds(), 0.0)
        return OutboxMetricsSnapshot(
            pending=counts.get(OutboxStatus.PENDING, 0),
            published=counts.get(OutboxStatus.PUBLISHED, 0),
            dead_letter=counts.get(OutboxStatus.DEAD_LETTER, 0),
            delivery_attempts=delivery_attempts,
            oldest_pending_age_seconds=oldest_age,
        )
