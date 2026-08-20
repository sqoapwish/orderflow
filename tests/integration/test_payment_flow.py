import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select, update

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.main import create_app
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.inventory.models import StockBalance
from orderflow.modules.orders.domain import OrderStatus
from orderflow.modules.orders.models import Order
from orderflow.modules.outbox.domain import OutboxEventType, OutboxStatus
from orderflow.modules.outbox.models import OutboxEvent
from orderflow.modules.payments.domain import PaymentStatus
from orderflow.modules.payments.models import Payment, PaymentRefund, PaymentWebhookEvent
from orderflow.modules.payments.provider import MockPaymentProvider

pytestmark = pytest.mark.integration


async def create_order(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    product_id: str,
    warehouse_id: str,
    quantity: int,
    key: str,
) -> dict[str, object]:
    cart = await client.post(
        "/api/v1/cart/items",
        headers=headers,
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": quantity,
        },
    )
    assert cart.status_code == 201, cart.text
    checkout = await client.post(
        "/api/v1/orders/checkout",
        headers={**headers, "Idempotency-Key": key},
    )
    assert checkout.status_code == 201, checkout.text
    return cast(dict[str, object], checkout.json())


async def create_session(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    order_id: object,
    key: str,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/payments/sessions",
        headers={**headers, "Idempotency-Key": key},
        json={"order_id": order_id},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def signed_webhook(
    provider: MockPaymentProvider,
    *,
    event_id: str,
    event_type: str,
    payment: dict[str, object],
    timestamp: int | None = None,
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(
        {
            "event_id": event_id,
            "type": event_type,
            "provider_payment_id": payment["provider_payment_id"],
            "amount_minor": payment["amount_minor"],
            "currency": payment["currency"],
        },
        separators=(",", ":"),
    ).encode()
    resolved_timestamp = timestamp or int(datetime.now(UTC).timestamp())
    return body, {
        "Content-Type": "application/json",
        "X-Payment-Timestamp": str(resolved_timestamp),
        "X-Payment-Signature": provider.sign_webhook(
            timestamp=resolved_timestamp,
            body=body,
        ),
    }


async def post_webhook(
    client: AsyncClient,
    body: bytes,
    headers: dict[str, str],
) -> Response:
    return await client.post(
        "/api/v1/payments/webhooks/mock",
        content=body,
        headers=headers,
    )


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_payment_lifecycle_is_atomic_and_idempotent_with_postgresql() -> None:
    settings = Settings(_env_file=None)
    app = create_app(settings)
    provider = MockPaymentProvider(
        webhook_secret=settings.payment_webhook_secret.get_secret_value(),
        session_ttl_minutes=settings.payment_session_ttl_minutes,
    )
    suffix = uuid4().hex[:10]

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        registrations = []
        for marker in ("manager", "paid", "failed", "cancelled"):
            response = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"payment-{marker}-{suffix}@example.com",
                    "password": "Integration-password-42",
                },
            )
            assert response.status_code == 201, response.text
            registrations.append(response.json())
        manager, paid_customer, failed_customer, cancelled_customer = registrations

        resources = cast(InfrastructureResources, app.state.resources)
        async for session in resources.database.session():
            await session.execute(
                update(User)
                .where(User.id == UUID(manager["user"]["id"]))
                .values(role=UserRole.MANAGER)
            )
            await session.commit()
            break

        manager_headers = {"Authorization": f"Bearer {manager['tokens']['access_token']}"}
        paid_headers = {"Authorization": f"Bearer {paid_customer['tokens']['access_token']}"}
        failed_headers = {"Authorization": f"Bearer {failed_customer['tokens']['access_token']}"}
        cancelled_headers = {
            "Authorization": f"Bearer {cancelled_customer['tokens']['access_token']}"
        }
        category = await client.post(
            "/api/v1/catalog/categories",
            headers=manager_headers,
            json={"name": f"Payments {suffix}", "slug": f"payments-{suffix}"},
        )
        product = await client.post(
            "/api/v1/catalog/products",
            headers=manager_headers,
            json={
                "category_id": category.json()["id"],
                "name": f"Payment product {suffix}",
                "slug": f"payment-product-{suffix}",
                "sku": f"PAYMENT-{suffix}",
                "price_minor": 10_000,
            },
        )
        warehouse = await client.post(
            "/api/v1/inventory/warehouses",
            headers=manager_headers,
            json={"name": f"Payments {suffix}", "code": f"PAY-{suffix.upper()}"},
        )
        assert category.status_code == 201, category.text
        assert product.status_code == 201, product.text
        assert warehouse.status_code == 201, warehouse.text
        product_id = product.json()["id"]
        warehouse_id = warehouse.json()["id"]
        receipt = await client.post(
            "/api/v1/inventory/stock/receipts",
            headers=manager_headers,
            json={
                "warehouse_id": warehouse_id,
                "product_id": product_id,
                "quantity": 5,
            },
        )
        assert receipt.status_code == 201, receipt.text

        availability = await client.get(f"/api/v1/inventory/availability/{product_id}")
        assert availability.status_code == 200, availability.text
        assert availability.json() == {
            "items": [
                {
                    "warehouse_id": warehouse_id,
                    "warehouse_name": f"Payments {suffix}",
                    "warehouse_code": f"PAY-{suffix.upper()}",
                    "available": 5,
                }
            ],
            "total": 1,
        }

        paid_order = await create_order(
            client,
            paid_headers,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=2,
            key=f"paid-order-{suffix}",
        )
        paid_payment = await create_session(
            client,
            paid_headers,
            order_id=paid_order["id"],
            key=f"paid-session-{suffix}",
        )
        success_body, success_headers = signed_webhook(
            provider,
            event_id=f"evt-success-{suffix}",
            event_type="payment.succeeded",
            payment=paid_payment,
        )
        first_webhook, replay_webhook = await asyncio.gather(
            post_webhook(client, success_body, success_headers),
            post_webhook(client, success_body, success_headers),
        )
        assert first_webhook.status_code == 200, first_webhook.text
        assert replay_webhook.status_code == 200, replay_webhook.text
        assert {first_webhook.json()["status"], replay_webhook.json()["status"]} == {
            "processed",
            "duplicate",
        }

        failed_order = await create_order(
            client,
            failed_headers,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=1,
            key=f"failed-order-{suffix}",
        )
        failed_payment = await create_session(
            client,
            failed_headers,
            order_id=failed_order["id"],
            key=f"failed-session-{suffix}",
        )
        failed_body, failed_webhook_headers = signed_webhook(
            provider,
            event_id=f"evt-failed-{suffix}",
            event_type="payment.failed",
            payment=failed_payment,
        )
        failed_webhook = await post_webhook(client, failed_body, failed_webhook_headers)
        assert failed_webhook.status_code == 200, failed_webhook.text
        assert failed_webhook.json()["status"] == "processed"

        cancelled_order = await create_order(
            client,
            cancelled_headers,
            product_id=product_id,
            warehouse_id=warehouse_id,
            quantity=1,
            key=f"cancelled-order-{suffix}",
        )
        await create_session(
            client,
            cancelled_headers,
            order_id=cancelled_order["id"],
            key=f"cancelled-session-{suffix}",
        )
        cancelled = await client.post(
            f"/api/v1/orders/{cancelled_order['id']}/cancel",
            headers=cancelled_headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

        refund_headers = {**manager_headers, "Idempotency-Key": f"refund-{suffix}"}
        refund = await client.post(
            f"/api/v1/payments/{paid_payment['id']}/refunds",
            headers=refund_headers,
        )
        refund_replay = await client.post(
            f"/api/v1/payments/{paid_payment['id']}/refunds",
            headers=refund_headers,
        )
        assert refund.status_code == 201, refund.text
        assert refund_replay.status_code == 200, refund_replay.text
        assert refund.json()["status"] == "refunded"

        stale_body, stale_headers = signed_webhook(
            provider,
            event_id=f"evt-stale-{suffix}",
            event_type="payment.failed",
            payment=paid_payment,
            timestamp=int(datetime.now(UTC).timestamp()) - 301,
        )
        stale = await post_webhook(client, stale_body, stale_headers)
        assert stale.status_code == 401
        assert stale.json()["error"]["code"] == "stale_webhook"

        stock = await client.get(
            "/api/v1/inventory/stock",
            headers=manager_headers,
            params={"warehouse_id": warehouse_id, "product_id": product_id},
        )
        assert stock.status_code == 200, stock.text
        assert stock.json()["items"][0]["on_hand"] == 3
        assert stock.json()["items"][0]["reserved"] == 0

        today = datetime.now(UTC).date().isoformat()
        await resources.redis.delete(
            f"orderflow:analytics:v1:sales:{today}:{today}",
            f"orderflow:analytics:v1:top-products:{today}:{today}:100",
        )
        sales = await client.get(
            "/api/v1/analytics/sales",
            headers=manager_headers,
            params={"date_from": today, "date_to": today},
        )
        top_products = await client.get(
            "/api/v1/analytics/products/top",
            headers=manager_headers,
            params={"date_from": today, "date_to": today, "limit": 100},
        )
        low_stock = await client.get(
            "/api/v1/analytics/inventory/low-stock",
            headers=manager_headers,
            params={
                "threshold": 3,
                "warehouse_id": warehouse_id,
                "page_size": 100,
            },
        )
        assert sales.status_code == 200, sales.text
        rub_sales = next(row for row in sales.json()["currencies"] if row["currency"] == "RUB")
        assert rub_sales["gross_revenue_minor"] >= 20_000
        assert rub_sales["refunded_amount_minor"] >= 20_000
        assert rub_sales["failed_payments"] >= 1
        assert top_products.status_code == 200, top_products.text
        scenario_product = next(
            row for row in top_products.json()["items"] if row["product_id"] == product_id
        )
        assert scenario_product["paid_quantity"] >= 2
        assert low_stock.status_code == 200, low_stock.text
        scenario_stock = next(
            row for row in low_stock.json()["items"] if row["product_id"] == product_id
        )
        assert scenario_stock["available"] == 3

        assert (
            await client.get(f"/api/v1/orders/{paid_order['id']}", headers=paid_headers)
        ).json()["status"] == "refunded"
        assert (
            await client.get(f"/api/v1/orders/{failed_order['id']}", headers=failed_headers)
        ).json()["status"] == "payment_failed"

        async for session in resources.database.session():
            balance = await session.scalar(
                select(StockBalance).where(
                    StockBalance.warehouse_id == UUID(warehouse_id),
                    StockBalance.product_id == UUID(product_id),
                )
            )
            assert balance is not None
            assert (balance.on_hand, balance.reserved) == (3, 0)
            scenario_payment_ids = [
                UUID(str(paid_payment["id"])),
                UUID(str(failed_payment["id"])),
            ]
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PaymentWebhookEvent)
                    .where(PaymentWebhookEvent.payment_id.in_(scenario_payment_ids))
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PaymentRefund)
                    .where(PaymentRefund.payment_id == UUID(str(paid_payment["id"])))
                )
                == 1
            )
            paid_row = await session.get(Payment, UUID(str(paid_payment["id"])))
            paid_order_row = await session.get(Order, UUID(str(paid_order["id"])))
            assert paid_row is not None and paid_row.status is PaymentStatus.REFUNDED
            assert paid_order_row is not None and paid_order_row.status is OrderStatus.REFUNDED
            scenario_aggregate_ids = [
                UUID(str(paid_order["id"])),
                UUID(str(failed_order["id"])),
                UUID(str(cancelled_order["id"])),
                UUID(str(paid_payment["id"])),
                UUID(str(failed_payment["id"])),
            ]
            outbox_events = list(
                (
                    await session.scalars(
                        select(OutboxEvent).where(
                            OutboxEvent.aggregate_id.in_(scenario_aggregate_ids)
                        )
                    )
                ).all()
            )
            assert Counter(event.event_type for event in outbox_events) == Counter(
                {
                    OutboxEventType.ORDER_CREATED: 3,
                    OutboxEventType.ORDER_CANCELLED: 1,
                    OutboxEventType.PAYMENT_SUCCEEDED: 1,
                    OutboxEventType.PAYMENT_FAILED: 1,
                    OutboxEventType.PAYMENT_REFUNDED: 1,
                }
            )
            assert all(event.status is OutboxStatus.PENDING for event in outbox_events)
            break
