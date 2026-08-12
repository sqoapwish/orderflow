import asyncio
import os
from typing import cast
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import update

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.main import create_app
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User

pytestmark = pytest.mark.integration


async def post_reservation(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    reservation_key: str,
    warehouse_id: str,
    product_id: str,
    quantity: int,
) -> Response:
    return await client.post(
        "/api/v1/inventory/reservations",
        headers=headers,
        json={
            "reservation_key": reservation_key,
            "warehouse_id": warehouse_id,
            "product_id": product_id,
            "quantity": quantity,
        },
    )


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_inventory_concurrency_and_movement_history_with_postgresql() -> None:
    app = create_app(Settings(_env_file=None))
    suffix = uuid4().hex[:10]

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        registered_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"inventory-manager-{suffix}@example.com",
                "password": "Integration-password-42",
            },
        )
        assert registered_response.status_code == 201, registered_response.text
        registered = registered_response.json()
        resources = cast(InfrastructureResources, app.state.resources)
        async for session in resources.database.session():
            await session.execute(
                update(User)
                .where(User.id == UUID(registered["user"]["id"]))
                .values(role=UserRole.MANAGER)
            )
            await session.commit()
            break

        headers = {"Authorization": f"Bearer {registered['tokens']['access_token']}"}
        category_response = await client.post(
            "/api/v1/catalog/categories",
            headers=headers,
            json={"name": f"Inventory {suffix}", "slug": f"inventory-{suffix}"},
        )
        assert category_response.status_code == 201, category_response.text
        product_response = await client.post(
            "/api/v1/catalog/products",
            headers=headers,
            json={
                "category_id": category_response.json()["id"],
                "name": f"Stock product {suffix}",
                "slug": f"stock-product-{suffix}",
                "sku": f"STOCK-{suffix}",
                "price_minor": 10000,
            },
        )
        assert product_response.status_code == 201, product_response.text
        product_id = product_response.json()["id"]

        source_response = await client.post(
            "/api/v1/inventory/warehouses",
            headers=headers,
            json={"name": f"Source {suffix}", "code": f"SRC-{suffix.upper()}"},
        )
        target_response = await client.post(
            "/api/v1/inventory/warehouses",
            headers=headers,
            json={"name": f"Target {suffix}", "code": f"TARGET-{suffix.upper()}"},
        )
        assert source_response.status_code == 201, source_response.text
        assert target_response.status_code == 201, target_response.text
        source_id = source_response.json()["id"]
        target_id = target_response.json()["id"]

        receipt = await client.post(
            "/api/v1/inventory/stock/receipts",
            headers=headers,
            json={
                "warehouse_id": source_id,
                "product_id": product_id,
                "quantity": 10,
                "reason": "Integration delivery",
            },
        )
        assert receipt.status_code == 201, receipt.text

        first, second = await asyncio.gather(
            post_reservation(
                client,
                headers,
                reservation_key=f"race-{suffix}-a",
                warehouse_id=source_id,
                product_id=product_id,
                quantity=7,
            ),
            post_reservation(
                client,
                headers,
                reservation_key=f"race-{suffix}-b",
                warehouse_id=source_id,
                product_id=product_id,
                quantity=7,
            ),
        )
        assert sorted([first.status_code, second.status_code]) == [201, 409]
        winner = first if first.status_code == 201 else second
        loser = second if first.status_code == 201 else first
        assert loser.json()["error"]["code"] == "insufficient_available_stock"

        stock_after_race = await client.get(
            "/api/v1/inventory/stock",
            headers=headers,
            params={"warehouse_id": source_id, "product_id": product_id},
        )
        assert stock_after_race.status_code == 200, stock_after_race.text
        balance = stock_after_race.json()["items"][0]
        assert balance["on_hand"] == 10
        assert balance["reserved"] == 7
        assert balance["available"] == 3

        consumed = await client.post(
            f"/api/v1/inventory/reservations/{winner.json()['id']}/consume",
            headers=headers,
        )
        assert consumed.status_code == 200, consumed.text
        assert consumed.json()["status"] == "consumed"

        transferred = await client.post(
            "/api/v1/inventory/stock/transfers",
            headers=headers,
            json={
                "source_warehouse_id": source_id,
                "target_warehouse_id": target_id,
                "product_id": product_id,
                "quantity": 2,
                "reason": "Integration transfer",
            },
        )
        assert transferred.status_code == 201, transferred.text
        assert transferred.json()["source"]["on_hand"] == 1
        assert transferred.json()["target"]["on_hand"] == 2

        adjusted = await client.post(
            "/api/v1/inventory/stock/adjustments",
            headers=headers,
            json={
                "warehouse_id": target_id,
                "product_id": product_id,
                "on_hand": 3,
                "reason": "Integration count",
            },
        )
        assert adjusted.status_code == 201, adjusted.text

        same_key = f"same-key-{suffix}"
        replay_one, replay_two = await asyncio.gather(
            post_reservation(
                client,
                headers,
                reservation_key=same_key,
                warehouse_id=target_id,
                product_id=product_id,
                quantity=1,
            ),
            post_reservation(
                client,
                headers,
                reservation_key=same_key,
                warehouse_id=target_id,
                product_id=product_id,
                quantity=1,
            ),
        )
        assert replay_one.status_code == 201, replay_one.text
        assert replay_two.status_code == 201, replay_two.text
        assert replay_one.json()["id"] == replay_two.json()["id"]

        target_stock = await client.get(
            "/api/v1/inventory/stock",
            headers=headers,
            params={"warehouse_id": target_id, "product_id": product_id},
        )
        target_balance = target_stock.json()["items"][0]
        assert target_balance["on_hand"] == 3
        assert target_balance["reserved"] == 1
        assert target_balance["available"] == 2

        movements = await client.get(
            "/api/v1/inventory/movements",
            headers=headers,
            params={"product_id": product_id, "page_size": 100},
        )
        assert movements.status_code == 200, movements.text
        body = movements.json()
        assert body["total"] == 7
        movement_types = [item["movement_type"] for item in body["items"]]
        assert movement_types.count("reservation_created") == 2
        assert movement_types.count("transfer_in") == 1
        assert movement_types.count("transfer_out") == 1
