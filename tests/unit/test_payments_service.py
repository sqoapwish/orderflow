import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from orderflow.modules.auth.domain import UserRole
from orderflow.modules.cart.service import CartService
from orderflow.modules.catalog.models import Product
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.models import Warehouse
from orderflow.modules.inventory.service import InventoryService
from orderflow.modules.orders.domain import OrderStatus
from orderflow.modules.orders.service import OrderService
from orderflow.modules.outbox.domain import OutboxEventType
from orderflow.modules.payments.domain import PaymentFilters, PaymentStatus
from orderflow.modules.payments.errors import (
    InvalidWebhookSignatureError,
    StaleWebhookError,
    WebhookEventConflictError,
)
from orderflow.modules.payments.provider import MockPaymentProvider
from orderflow.modules.payments.service import PaymentService
from tests.fakes import (
    FakeCartRepository,
    FakeCatalogRepository,
    FakeInventoryRepository,
    FakeOrderRepository,
    FakeOutboxRepository,
    FakePaymentRepository,
)

TEST_WEBHOOK_SECRET = "test-payment-webhook-secret-at-least-32-characters"


@dataclass(slots=True)
class PaymentContext:
    service: PaymentService
    provider: MockPaymentProvider
    orders: OrderService
    order_repository: FakeOrderRepository
    inventory_repository: FakeInventoryRepository
    payment_repository: FakePaymentRepository
    outbox_repository: FakeOutboxRepository
    cart: CartService
    product: Product
    warehouse: Warehouse
    customer_id: UUID


async def build_payment_context() -> PaymentContext:
    catalog_repository = FakeCatalogRepository()
    catalog = CatalogService(catalog_repository)
    category = await catalog.create_category(
        name="Laptops",
        slug="laptops",
        parent_id=None,
        is_active=True,
    )
    product = await catalog.create_product(
        category_id=category.id,
        name="Laptop Pro",
        slug="laptop-pro",
        sku="LAPTOP-PRO",
        description=None,
        price_minor=199_900,
        currency="RUB",
        image_url=None,
        is_active=True,
    )
    inventory_repository = FakeInventoryRepository()
    inventory = InventoryService(inventory_repository, catalog)
    warehouse = await inventory.create_warehouse(
        name="Main warehouse",
        code="MAIN",
        location=None,
        is_active=True,
    )
    customer_id = uuid4()
    await inventory.receive_stock(
        warehouse_id=warehouse.id,
        product_id=product.id,
        quantity=5,
        reason="Test delivery",
        actor_id=uuid4(),
    )
    cart = CartService(FakeCartRepository(), catalog, inventory)
    order_repository = FakeOrderRepository()
    outbox_repository = FakeOutboxRepository()
    orders = OrderService(order_repository, cart, catalog, inventory, outbox_repository)
    payment_repository = FakePaymentRepository()
    provider = MockPaymentProvider(
        webhook_secret=TEST_WEBHOOK_SECRET,
        session_ttl_minutes=30,
    )
    service = PaymentService(
        payment_repository,
        order_repository,
        inventory,
        provider,
        outbox_repository,
        webhook_tolerance_seconds=300,
    )
    return PaymentContext(
        service=service,
        provider=provider,
        orders=orders,
        order_repository=order_repository,
        inventory_repository=inventory_repository,
        payment_repository=payment_repository,
        outbox_repository=outbox_repository,
        cart=cart,
        product=product,
        warehouse=warehouse,
        customer_id=customer_id,
    )


async def create_order(context: PaymentContext, *, quantity: int = 2) -> UUID:
    await context.cart.add_item(
        customer_id=context.customer_id,
        product_id=context.product.id,
        warehouse_id=context.warehouse.id,
        quantity=quantity,
    )
    result = await context.orders.checkout(
        customer_id=context.customer_id,
        idempotency_key=f"order-{uuid4()}",
    )
    return result.bundle.order.id


def webhook_body(
    *,
    event_id: str,
    event_type: str,
    provider_payment_id: str,
    amount_minor: int,
    failure_code: str | None = None,
) -> bytes:
    payload: dict[str, object] = {
        "event_id": event_id,
        "type": event_type,
        "provider_payment_id": provider_payment_id,
        "amount_minor": amount_minor,
        "currency": "RUB",
    }
    if failure_code is not None:
        payload["failure_code"] = failure_code
    return json.dumps(payload, separators=(",", ":")).encode()


async def send_webhook(
    context: PaymentContext,
    *,
    body: bytes,
    timestamp: int | None = None,
) -> str:
    resolved_timestamp = timestamp or int(datetime.now(UTC).timestamp())
    signature = context.provider.sign_webhook(timestamp=resolved_timestamp, body=body)
    result = await context.service.handle_webhook(
        raw_body=body,
        timestamp=resolved_timestamp,
        signature=signature,
    )
    return result.status


async def test_session_success_webhook_duplicate_and_refund_are_idempotent() -> None:
    context = await build_payment_context()
    order_id = await create_order(context)

    created = await context.service.create_session(
        order_id=order_id,
        customer_id=context.customer_id,
        idempotency_key=" payment-session-1 ",
    )
    replay = await context.service.create_session(
        order_id=order_id,
        customer_id=context.customer_id,
        idempotency_key="payment-session-1",
    )
    assert created.created is True
    assert replay.created is False
    assert replay.bundle.payment.id == created.bundle.payment.id

    body = webhook_body(
        event_id="evt-success-1",
        event_type="payment.succeeded",
        provider_payment_id=created.bundle.payment.provider_payment_id,
        amount_minor=399_800,
    )
    assert await send_webhook(context, body=body) == "processed"
    assert await send_webhook(context, body=body) == "duplicate"
    assert created.bundle.payment.status is PaymentStatus.SUCCEEDED
    assert context.order_repository.orders[order_id].status is OrderStatus.PAID
    balance = context.inventory_repository.balances[(context.warehouse.id, context.product.id)]
    assert balance.on_hand == 3
    assert balance.reserved == 0
    assert [event.event_type for event in context.outbox_repository.events] == [
        OutboxEventType.ORDER_CREATED,
        OutboxEventType.PAYMENT_SUCCEEDED,
    ]

    late_failure = webhook_body(
        event_id="evt-late-failure-1",
        event_type="payment.failed",
        provider_payment_id=created.bundle.payment.provider_payment_id,
        amount_minor=399_800,
    )
    assert await send_webhook(context, body=late_failure) == "ignored"
    assert created.bundle.payment.status is PaymentStatus.SUCCEEDED
    assert context.order_repository.orders[order_id].status is OrderStatus.PAID

    refunded = await context.service.refund_payment(
        created.bundle.payment.id,
        actor_id=uuid4(),
        actor_role=UserRole.MANAGER,
        idempotency_key="refund-1",
    )
    refund_replay = await context.service.refund_payment(
        created.bundle.payment.id,
        actor_id=uuid4(),
        actor_role=UserRole.MANAGER,
        idempotency_key="refund-1",
    )
    assert refunded.created is True
    assert refund_replay.created is False
    assert refunded.bundle.payment.status is PaymentStatus.REFUNDED
    assert context.order_repository.orders[order_id].status is OrderStatus.REFUNDED
    assert balance.on_hand == 3
    assert balance.reserved == 0
    assert [event.event_type for event in context.outbox_repository.events] == [
        OutboxEventType.ORDER_CREATED,
        OutboxEventType.PAYMENT_SUCCEEDED,
        OutboxEventType.PAYMENT_REFUNDED,
    ]


async def test_failed_payment_and_cancel_release_reservations() -> None:
    failed_context = await build_payment_context()
    failed_order_id = await create_order(failed_context)
    failed_payment = await failed_context.service.create_session(
        order_id=failed_order_id,
        customer_id=failed_context.customer_id,
        idempotency_key="failed-session",
    )
    failed_body = webhook_body(
        event_id="evt-failed-1",
        event_type="payment.failed",
        provider_payment_id=failed_payment.bundle.payment.provider_payment_id,
        amount_minor=399_800,
        failure_code="card_declined",
    )
    assert await send_webhook(failed_context, body=failed_body) == "processed"
    assert failed_payment.bundle.payment.status is PaymentStatus.FAILED
    assert failed_payment.bundle.payment.failure_code == "card_declined"
    assert (
        failed_context.order_repository.orders[failed_order_id].status is OrderStatus.PAYMENT_FAILED
    )
    failed_balance = failed_context.inventory_repository.balances[
        (failed_context.warehouse.id, failed_context.product.id)
    ]
    assert failed_balance.on_hand == 5
    assert failed_balance.reserved == 0
    assert [event.event_type for event in failed_context.outbox_repository.events] == [
        OutboxEventType.ORDER_CREATED,
        OutboxEventType.PAYMENT_FAILED,
    ]

    cancelled_context = await build_payment_context()
    cancelled_order_id = await create_order(cancelled_context)
    cancelled_payment = await cancelled_context.service.create_session(
        order_id=cancelled_order_id,
        customer_id=cancelled_context.customer_id,
        idempotency_key="cancelled-session",
    )
    await cancelled_context.service.cancel_order(
        cancelled_order_id,
        requester_id=cancelled_context.customer_id,
        requester_role=UserRole.CUSTOMER,
    )
    assert cancelled_payment.bundle.payment.status is PaymentStatus.CANCELLED
    assert (
        cancelled_context.order_repository.orders[cancelled_order_id].status
        is OrderStatus.CANCELLED
    )
    cancelled_balance = cancelled_context.inventory_repository.balances[
        (cancelled_context.warehouse.id, cancelled_context.product.id)
    ]
    assert cancelled_balance.on_hand == 5
    assert cancelled_balance.reserved == 0
    assert [event.event_type for event in cancelled_context.outbox_repository.events] == [
        OutboxEventType.ORDER_CREATED,
        OutboxEventType.ORDER_CANCELLED,
    ]


async def test_webhook_rejects_invalid_signature_stale_timestamp_and_event_mutation() -> None:
    context = await build_payment_context()
    order_id = await create_order(context, quantity=1)
    payment = await context.service.create_session(
        order_id=order_id,
        customer_id=context.customer_id,
        idempotency_key="secure-session",
    )
    body = webhook_body(
        event_id="evt-secure-1",
        event_type="payment.succeeded",
        provider_payment_id=payment.bundle.payment.provider_payment_id,
        amount_minor=199_900,
    )
    now = int(datetime.now(UTC).timestamp())

    with pytest.raises(InvalidWebhookSignatureError):
        await context.service.handle_webhook(
            raw_body=body,
            timestamp=now,
            signature="sha256=invalid",
        )
    with pytest.raises(StaleWebhookError):
        await send_webhook(context, body=body, timestamp=now - 301)

    assert await send_webhook(context, body=body, timestamp=now) == "processed"
    mutated_body = webhook_body(
        event_id="evt-secure-1",
        event_type="payment.failed",
        provider_payment_id=payment.bundle.payment.provider_payment_id,
        amount_minor=199_900,
    )
    with pytest.raises(WebhookEventConflictError):
        await send_webhook(context, body=mutated_body, timestamp=now)


async def test_payment_visibility_is_scoped_for_customers() -> None:
    context = await build_payment_context()
    order_id = await create_order(context, quantity=1)
    payment = await context.service.create_session(
        order_id=order_id,
        customer_id=context.customer_id,
        idempotency_key="visible-session",
    )

    own_page = await context.service.list_payments(
        PaymentFilters(customer_id=uuid4()),
        requester_id=context.customer_id,
        requester_role=UserRole.CUSTOMER,
    )
    stranger_page = await context.service.list_payments(
        PaymentFilters(),
        requester_id=uuid4(),
        requester_role=UserRole.CUSTOMER,
    )
    manager_page = await context.service.list_payments(
        PaymentFilters(customer_id=context.customer_id),
        requester_id=uuid4(),
        requester_role=UserRole.MANAGER,
    )
    assert own_page.total == 1
    assert stranger_page.total == 0
    assert manager_page.total == 1
    assert manager_page.items[0].payment.id == payment.bundle.payment.id
