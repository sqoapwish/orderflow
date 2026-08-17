import os
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from orderflow.core.config import Settings
from orderflow.infrastructure.database import Database
from orderflow.modules.audit.domain import AuditActorType
from orderflow.modules.audit.models import AuditEvent
from orderflow.modules.audit.repository import AuditRepository
from orderflow.modules.audit.service import AuditDomainEventHandler
from orderflow.modules.outbox.domain import InboxOutcome
from orderflow.modules.outbox.repository import InboxRepository
from orderflow.modules.outbox.service import InboxService

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_inbox_and_immutable_audit_share_a_postgresql_transaction() -> None:
    database = Database(Settings(_env_file=None))
    event_id = uuid4()
    order_id = uuid4()
    actor_id = uuid4()
    payload = {
        "customer_id": str(actor_id),
        "order_number": "OF-INTEGRATION",
        "status": "pending_payment",
        "access_token": "must-not-be-stored",
    }
    try:
        async with database.session_factory() as session:
            consumer = InboxService(
                InboxRepository(session),
                AuditDomainEventHandler(AuditRepository(session)),
            )
            first = await consumer.consume(
                event_id=event_id,
                event_type="order.created",
                aggregate_type="order",
                aggregate_id=order_id,
                payload=payload,
                occurred_at="2026-08-17T14:00:00+00:00",
                correlation_id="audit-integration-42",
            )
            duplicate = await consumer.consume(
                event_id=event_id,
                event_type="order.created",
                aggregate_type="order",
                aggregate_id=order_id,
                payload=payload,
                occurred_at="2026-08-17T14:00:00+00:00",
                correlation_id="audit-integration-42",
            )

            events = list(
                (
                    await session.scalars(
                        select(AuditEvent).where(AuditEvent.source_event_id == event_id)
                    )
                ).all()
            )
            assert first is InboxOutcome.PROCESSED
            assert duplicate is InboxOutcome.DUPLICATE
            assert len(events) == 1
            assert events[0].actor_type is AuditActorType.USER
            assert events[0].details == {
                "order_number": "OF-INTEGRATION",
                "status": "pending_payment",
            }

            with pytest.raises(DBAPIError):
                await session.execute(
                    update(AuditEvent)
                    .where(AuditEvent.id == events[0].id)
                    .values(action="tampered")
                )
                await session.commit()
            await session.rollback()
    finally:
        await database.close()
