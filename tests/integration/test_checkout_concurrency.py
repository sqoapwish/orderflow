import asyncio
import os
from typing import cast
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select, update

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.main import create_app
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.inventory.models import StockBalance

pytestmark = pytest.mark.integration


async def checkout(client: AsyncClient, headers: dict[str, str], key: str) -> Response:
    return await client.post(
        "/api/v1/orders/checkout",
        headers={**headers, "Idempotency-Key": key},
    )


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_checkout_is_idempotent_atomic_and_prevents_overselling_with_postgresql() -> None:
    app = create_app(Settings(_env_file=None))
    suffix = uuid4().hex[:10]

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        manager_registration = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"checkout-manager-{suffix}@example.com",
                "password": "Integration-password-42",
            },
        )
        first_customer = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"checkout-first-{suffix}@example.com",
                "password": "Integration-password-42",
            },
        )
        second_customer = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"checkout-second-{suffix}@example.com",
                "password": "Integration-password-42",
            },
        )
        assert manager_registration.status_code == 201, manager_registration.text
        assert first_customer.status_code == 201, first_customer.text
        assert second_customer.status_code == 201, second_customer.text
        manager = manager_registration.json()
        first = first_customer.json()
        second = second_customer.json()
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
        first_headers = {"Authorization": f"Bearer {first['tokens']['access_token']}"}
        second_headers = {"Authorization": f"Bearer {second['tokens']['access_token']}"}
        category = await client.post(
            "/api/v1/catalog/categories",
            headers=manager_headers,
            json={"name": f"Checkout {suffix}", "slug": f"checkout-{suffix}"},
        )
        product = await client.post(
            "/api/v1/catalog/products",
            headers=manager_headers,
            json={
                "category_id": category.json()["id"],
                "name": f"Checkout product {suffix}",
                "slug": f"checkout-product-{suffix}",
                "sku": f"CHECKOUT-{suffix}",
                "price_minor": 12_345,
            },
        )
        warehouse = await client.post(
            "/api/v1/inventory/warehouses",
            headers=manager_headers,
            json={"name": f"Checkout {suffix}", "code": f"CO-{suffix.upper()}"},
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
                "quantity": 3,
            },
        )
        assert receipt.status_code == 201, receipt.text

        cart_payload = {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": 2,
        }
        assert (
            await client.post("/api/v1/cart/items", headers=first_headers, json=cart_payload)
        ).status_code == 201
        assert (
            await client.post("/api/v1/cart/items", headers=second_headers, json=cart_payload)
        ).status_code == 201

        first_checkout, second_checkout = await asyncio.gather(
            checkout(client, first_headers, f"first-{suffix}"),
            checkout(client, second_headers, f"second-{suffix}"),
        )
        assert sorted([first_checkout.status_code, second_checkout.status_code]) == [201, 409]
        winner = first_checkout if first_checkout.status_code == 201 else second_checkout
        loser = second_checkout if first_checkout.status_code == 201 else first_checkout
        assert loser.json()["error"]["code"] == "insufficient_available_stock"
        assert winner.json()["total_minor"] == 24_690

        winner_headers = first_headers if first_checkout.status_code == 201 else second_headers
        winner_key = f"first-{suffix}" if first_checkout.status_code == 201 else f"second-{suffix}"
        replay_one, replay_two = await asyncio.gather(
            checkout(client, winner_headers, winner_key),
            checkout(client, winner_headers, winner_key),
        )
        assert replay_one.status_code == 200, replay_one.text
        assert replay_two.status_code == 200, replay_two.text
        assert replay_one.json()["id"] == winner.json()["id"] == replay_two.json()["id"]

        loser_headers = second_headers if first_checkout.status_code == 201 else first_headers
        assert (await client.delete("/api/v1/cart", headers=loser_headers)).status_code == 204
        atomic_products: list[dict[str, str]] = []
        for marker in ("a", "b"):
            response = await client.post(
                "/api/v1/catalog/products",
                headers=manager_headers,
                json={
                    "category_id": category.json()["id"],
                    "name": f"Atomic {marker} {suffix}",
                    "slug": f"atomic-{marker}-{suffix}",
                    "sku": f"ATOMIC-{marker.upper()}-{suffix}",
                    "price_minor": 1_000,
                },
            )
            assert response.status_code == 201, response.text
            atomic_products.append(response.json())
        atomic_products.sort(key=lambda value: UUID(value["id"]).int)
        stocked_product = atomic_products[0]
        missing_product = atomic_products[1]
        stocked_receipt = await client.post(
            "/api/v1/inventory/stock/receipts",
            headers=manager_headers,
            json={
                "warehouse_id": warehouse_id,
                "product_id": stocked_product["id"],
                "quantity": 1,
            },
        )
        assert stocked_receipt.status_code == 201, stocked_receipt.text
        for atomic_product in (stocked_product, missing_product):
            cart_response = await client.post(
                "/api/v1/cart/items",
                headers=loser_headers,
                json={
                    "product_id": atomic_product["id"],
                    "warehouse_id": warehouse_id,
                    "quantity": 1,
                },
            )
            assert cart_response.status_code == 201, cart_response.text

        atomic_failure = await checkout(client, loser_headers, f"atomic-failure-{suffix}")
        assert atomic_failure.status_code == 409, atomic_failure.text
        assert atomic_failure.json()["error"]["code"] == "insufficient_available_stock"
        preserved_cart = await client.get("/api/v1/cart", headers=loser_headers)
        assert preserved_cart.status_code == 200
        assert len(preserved_cart.json()["items"]) == 2

        async for session in resources.database.session():
            balance = await session.scalar(
                select(StockBalance).where(
                    StockBalance.warehouse_id == UUID(warehouse_id),
                    StockBalance.product_id == UUID(product_id),
                )
            )
            assert balance is not None
            assert balance.on_hand == 3
            assert balance.reserved == 2
            stocked_balance = await session.scalar(
                select(StockBalance).where(
                    StockBalance.warehouse_id == UUID(warehouse_id),
                    StockBalance.product_id == UUID(stocked_product["id"]),
                )
            )
            assert stocked_balance is not None
            assert stocked_balance.on_hand == 1
            assert stocked_balance.reserved == 0
            break
