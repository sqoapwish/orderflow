from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from orderflow.modules.audit.domain import AuditActorType, AuditFilters
from orderflow.modules.audit.errors import AuditEventNotFoundError, InvalidAuditTimeRangeError
from orderflow.modules.audit.service import AuditDomainEventHandler, AuditService
from orderflow.modules.outbox.service import InboxService
from tests.fakes import FakeAuditRepository, FakeInboxRepository


async def test_domain_event_becomes_sanitized_user_audit_record() -> None:
    repository = FakeAuditRepository()
    handler = AuditDomainEventHandler(repository)
    event_id = uuid4()
    order_id = uuid4()
    actor_id = uuid4()

    await handler.handle(
        event_id=event_id,
        event_type="order.created",
        aggregate_type="order",
        aggregate_id=order_id,
        payload={
            "customer_id": str(actor_id),
            "order_number": "OF-42",
            "status": "pending_payment",
            "total_minor": 199_00,
            "currency": "RUB",
            "item_count": 2,
            "password": "must-not-be-stored",
            "access_token": "must-not-be-stored",
        },
        occurred_at="2026-08-17T12:00:00+00:00",
        correlation_id="correlation-42",
    )

    event = next(iter(repository.events.values()))
    assert event.source_event_id == event_id
    assert event.actor_type is AuditActorType.USER
    assert event.actor_id == actor_id
    assert event.actor_role == "customer"
    assert event.resource_id == order_id
    assert event.details == {
        "currency": "RUB",
        "item_count": 2,
        "order_number": "OF-42",
        "status": "pending_payment",
        "total_minor": 199_00,
    }


async def test_system_payment_event_has_no_user_identity() -> None:
    repository = FakeAuditRepository()
    payment_id = uuid4()

    await AuditDomainEventHandler(repository).handle(
        event_id=uuid4(),
        event_type="payment.failed",
        aggregate_type="payment",
        aggregate_id=payment_id,
        payload={
            "customer_id": str(uuid4()),
            "status": "failed",
            "failure_code": "declined",
            "webhook_secret": "must-not-be-stored",
        },
        occurred_at="2026-08-17T12:01:00Z",
        correlation_id=None,
    )

    event = next(iter(repository.events.values()))
    assert event.actor_type is AuditActorType.SYSTEM
    assert event.actor_id is None
    assert event.actor_role is None
    assert event.details == {"failure_code": "declined", "status": "failed"}


async def test_inbox_and_audit_are_idempotent_on_exact_redelivery() -> None:
    inbox = FakeInboxRepository()
    audit = FakeAuditRepository()
    service = InboxService(inbox, AuditDomainEventHandler(audit))
    event_id = uuid4()
    order_id = uuid4()
    payload = {"customer_id": str(uuid4()), "status": "cancelled"}

    async def consume() -> object:
        return await service.consume(
            event_id=event_id,
            event_type="order.cancelled",
            aggregate_type="order",
            aggregate_id=order_id,
            payload=payload,
            occurred_at="2026-08-17T12:02:00+00:00",
            correlation_id="correlation-43",
        )

    await consume()
    await consume()

    assert len(inbox.events) == 1
    assert len(audit.events) == 1
    assert inbox.commits == 2


async def test_audit_service_filters_pages_and_validates_time_range() -> None:
    repository = FakeAuditRepository()
    handler = AuditDomainEventHandler(repository)
    actor_id = uuid4()
    now = datetime.now(UTC)
    for index in range(3):
        await handler.handle(
            event_id=uuid4(),
            event_type="order.created",
            aggregate_type="order",
            aggregate_id=uuid4(),
            payload={"customer_id": str(actor_id), "order_number": f"OF-{index}"},
            occurred_at=(now + timedelta(seconds=index)).isoformat(),
            correlation_id=f"correlation-{index}",
        )

    service = AuditService(repository)
    page = await service.list_events(AuditFilters(page=2, page_size=2, actor_id=actor_id))

    assert page.total == 3
    assert page.total_pages == 2
    assert len(page.items) == 1
    with pytest.raises(InvalidAuditTimeRangeError):
        await service.list_events(
            AuditFilters(occurred_from=now + timedelta(seconds=1), occurred_to=now)
        )
    with pytest.raises(AuditEventNotFoundError):
        await service.get_event(uuid4())
