import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.auth.dependencies import get_auth_service
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.cart.dependencies import get_cart_service
from orderflow.modules.cart.service import CartService
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.service import InventoryService
from orderflow.modules.orders.dependencies import get_order_service
from orderflow.modules.orders.service import OrderService
from orderflow.modules.payments.dependencies import get_payment_service
from orderflow.modules.payments.provider import MockPaymentProvider
from orderflow.modules.payments.service import PaymentService
from orderflow.schemas.health import ComponentHealth
from tests.fakes import (
    FakeCartRepository,
    FakeCatalogRepository,
    FakeInventoryRepository,
    FakeOrderRepository,
    FakePaymentRepository,
    build_auth_service,
)


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class PaymentsApiContext:
    client: AsyncClient
    provider: MockPaymentProvider
    product_id: UUID
    warehouse_id: UUID
    customer_headers: dict[str, str]
    stranger_headers: dict[str, str]
    manager_headers: dict[str, str]


@pytest.fixture
async def payments_api(test_settings: Settings) -> AsyncIterator[PaymentsApiContext]:
    auth_service, _, _, _ = build_auth_service(test_settings)
    customer = await auth_service.register("pay-customer@example.com", "Strong-password-42")
    stranger = await auth_service.register("pay-stranger@example.com", "Strong-password-42")
    manager = await auth_service.register("pay-manager@example.com", "Strong-password-42")
    manager.user.role = UserRole.MANAGER

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
    inventory = InventoryService(FakeInventoryRepository(), catalog)
    warehouse = await inventory.create_warehouse(
        name="Main warehouse",
        code="MAIN",
        location=None,
        is_active=True,
    )
    await inventory.receive_stock(
        warehouse_id=warehouse.id,
        product_id=product.id,
        quantity=5,
        reason="API test delivery",
        actor_id=manager.user.id,
    )
    cart = CartService(FakeCartRepository(), catalog, inventory)
    order_repository = FakeOrderRepository()
    orders = OrderService(order_repository, cart, catalog, inventory)
    provider = MockPaymentProvider(
        webhook_secret=test_settings.payment_webhook_secret.get_secret_value(),
        session_ttl_minutes=test_settings.payment_session_ttl_minutes,
    )
    payments = PaymentService(
        FakePaymentRepository(),
        order_repository,
        inventory,
        provider,
        webhook_tolerance_seconds=test_settings.payment_webhook_tolerance_seconds,
    )

    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_cart_service] = lambda: cart
    app.dependency_overrides[get_order_service] = lambda: orders
    app.dependency_overrides[get_payment_service] = lambda: payments
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield PaymentsApiContext(
            client=client,
            provider=provider,
            product_id=product.id,
            warehouse_id=warehouse.id,
            customer_headers={"Authorization": f"Bearer {customer.tokens.access_token}"},
            stranger_headers={"Authorization": f"Bearer {stranger.tokens.access_token}"},
            manager_headers={"Authorization": f"Bearer {manager.tokens.access_token}"},
        )


async def create_order(context: PaymentsApiContext) -> dict[str, object]:
    added = await context.client.post(
        "/api/v1/cart/items",
        headers=context.customer_headers,
        json={
            "product_id": str(context.product_id),
            "warehouse_id": str(context.warehouse_id),
            "quantity": 2,
        },
    )
    assert added.status_code == 201, added.text
    checkout = await context.client.post(
        "/api/v1/orders/checkout",
        headers={**context.customer_headers, "Idempotency-Key": "api-payment-order"},
    )
    assert checkout.status_code == 201, checkout.text
    return cast(dict[str, object], checkout.json())


async def test_payment_session_webhook_visibility_and_refund_api(
    payments_api: PaymentsApiContext,
) -> None:
    context = payments_api
    order = await create_order(context)
    session_headers = {**context.customer_headers, "Idempotency-Key": "api-session-1"}
    created = await context.client.post(
        "/api/v1/payments/sessions",
        headers=session_headers,
        json={"order_id": order["id"]},
    )
    replay = await context.client.post(
        "/api/v1/payments/sessions",
        headers=session_headers,
        json={"order_id": order["id"]},
    )
    assert created.status_code == 201, created.text
    assert replay.status_code == 200
    assert replay.json()["id"] == created.json()["id"]

    stranger_session = await context.client.post(
        "/api/v1/payments/sessions",
        headers={**context.stranger_headers, "Idempotency-Key": "stranger-session"},
        json={"order_id": order["id"]},
    )
    assert stranger_session.status_code == 404
    assert stranger_session.json()["error"]["code"] == "order_not_found"

    body = json.dumps(
        {
            "event_id": "evt-api-success",
            "type": "payment.succeeded",
            "provider_payment_id": created.json()["provider_payment_id"],
            "amount_minor": 399_800,
            "currency": "RUB",
        },
        separators=(",", ":"),
    ).encode()
    timestamp = int(datetime.now(UTC).timestamp())
    invalid = await context.client.post(
        "/api/v1/payments/webhooks/mock",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Payment-Timestamp": str(timestamp),
            "X-Payment-Signature": "sha256=invalid",
        },
    )
    signature = context.provider.sign_webhook(timestamp=timestamp, body=body)
    webhook_headers = {
        "Content-Type": "application/json",
        "X-Payment-Timestamp": str(timestamp),
        "X-Payment-Signature": signature,
    }
    processed = await context.client.post(
        "/api/v1/payments/webhooks/mock",
        content=body,
        headers=webhook_headers,
    )
    duplicate = await context.client.post(
        "/api/v1/payments/webhooks/mock",
        content=body,
        headers=webhook_headers,
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "invalid_webhook_signature"
    assert processed.status_code == 200, processed.text
    assert processed.json() == {"status": "processed"}
    assert duplicate.json() == {"status": "duplicate"}

    own_payments = await context.client.get(
        "/api/v1/payments",
        headers=context.customer_headers,
    )
    stranger_payments = await context.client.get(
        "/api/v1/payments",
        headers=context.stranger_headers,
    )
    assert own_payments.json()["total"] == 1
    assert own_payments.json()["items"][0]["status"] == "succeeded"
    assert stranger_payments.json()["total"] == 0

    customer_refund = await context.client.post(
        f"/api/v1/payments/{created.json()['id']}/refunds",
        headers={**context.customer_headers, "Idempotency-Key": "refund-denied"},
    )
    refunded = await context.client.post(
        f"/api/v1/payments/{created.json()['id']}/refunds",
        headers={**context.manager_headers, "Idempotency-Key": "refund-api-1"},
    )
    refund_replay = await context.client.post(
        f"/api/v1/payments/{created.json()['id']}/refunds",
        headers={**context.manager_headers, "Idempotency-Key": "refund-api-1"},
    )
    assert customer_refund.status_code == 403
    assert refunded.status_code == 201, refunded.text
    assert refund_replay.status_code == 200
    assert refunded.json()["status"] == "refunded"
    assert refunded.json()["refund"]["amount_minor"] == 399_800


async def test_cancel_endpoint_and_openapi_security(payments_api: PaymentsApiContext) -> None:
    context = payments_api
    order = await create_order(context)
    session = await context.client.post(
        "/api/v1/payments/sessions",
        headers={**context.customer_headers, "Idempotency-Key": "cancel-session"},
        json={"order_id": order["id"]},
    )
    assert session.status_code == 201

    stranger_cancel = await context.client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=context.stranger_headers,
    )
    cancelled = await context.client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=context.customer_headers,
    )
    cancel_replay = await context.client.post(
        f"/api/v1/orders/{order['id']}/cancel",
        headers=context.customer_headers,
    )
    assert stranger_cancel.status_code == 404
    assert cancelled.status_code == 200
    assert cancel_replay.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    openapi = (await context.client.get("/api/openapi.json")).json()
    paths = openapi["paths"]
    expected = {
        "/api/v1/payments",
        "/api/v1/payments/sessions",
        "/api/v1/payments/{payment_id}",
        "/api/v1/payments/{payment_id}/refunds",
        "/api/v1/payments/webhooks/mock",
        "/api/v1/orders/{order_id}/cancel",
    }
    assert expected <= set(paths)
    assert "security" not in paths["/api/v1/payments/webhooks/mock"]["post"]
    assert paths["/api/v1/payments"]["get"]["security"] == [{"HTTPBearer": []}]
