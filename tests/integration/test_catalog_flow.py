import os
from typing import cast
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.main import create_app
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_catalog_flow_with_postgresql() -> None:
    app = create_app(Settings(_env_file=None))
    suffix = uuid4().hex[:10]

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        registered_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": f"catalog-manager-{suffix}@example.com",
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

        headers = {
            "Authorization": f"Bearer {registered['tokens']['access_token']}",
        }
        category_response = await client.post(
            "/api/v1/catalog/categories",
            headers=headers,
            json={"name": f"Laptops {suffix}", "slug": f"laptops-{suffix}"},
        )
        assert category_response.status_code == 201, category_response.text
        category = category_response.json()

        child_response = await client.post(
            "/api/v1/catalog/categories",
            headers=headers,
            json={
                "name": f"Premium {suffix}",
                "slug": f"premium-{suffix}",
                "parent_id": category["id"],
            },
        )
        assert child_response.status_code == 201, child_response.text
        child = child_response.json()
        rejected_cycle = await client.patch(
            f"/api/v1/catalog/categories/id/{category['id']}",
            headers=headers,
            json={"parent_id": child["id"]},
        )
        assert rejected_cycle.status_code == 409, rejected_cycle.text
        assert rejected_cycle.json()["error"]["code"] == "category_cycle"

        product_response = await client.post(
            "/api/v1/catalog/products",
            headers=headers,
            json={
                "category_id": category["id"],
                "name": f"Laptop Pro {suffix}",
                "slug": f"laptop-pro-{suffix}",
                "sku": f"PRO-{suffix}",
                "price_minor": 199900,
                "currency": "RUB",
            },
        )
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()

        update_response = await client.patch(
            f"/api/v1/catalog/products/id/{product['id']}",
            headers=headers,
            json={"price_minor": 189900},
        )
        assert update_response.status_code == 200, update_response.text
        assert update_response.json()["price_minor"] == 189900

        search_response = await client.get(
            "/api/v1/catalog/products",
            params={
                "search": f"PRO-{suffix}",
                "category_id": category["id"],
                "min_price_minor": 150000,
                "max_price_minor": 250000,
                "sort_by": "price",
                "sort_direction": "desc",
                "page": 1,
                "page_size": 1,
            },
        )
        assert search_response.status_code == 200, search_response.text
        assert search_response.json()["total"] == 1
        assert search_response.json()["items"][0]["id"] == product["id"]
        wildcard_response = await client.get(
            "/api/v1/catalog/products",
            params={"search": "%"},
        )
        assert wildcard_response.status_code == 200, wildcard_response.text
        assert wildcard_response.json()["total"] == 0

        archived_product = await client.delete(
            f"/api/v1/catalog/products/id/{product['id']}",
            headers=headers,
        )
        assert archived_product.status_code == 204, archived_product.text
        assert (await client.get(f"/api/v1/catalog/products/{product['slug']}")).status_code == 404

        archived_child = await client.delete(
            f"/api/v1/catalog/categories/id/{child['id']}",
            headers=headers,
        )
        assert archived_child.status_code == 204, archived_child.text

        archived_category = await client.delete(
            f"/api/v1/catalog/categories/id/{category['id']}",
            headers=headers,
        )
        assert archived_category.status_code == 204, archived_category.text
        assert (
            await client.get(f"/api/v1/catalog/categories/{category['slug']}")
        ).status_code == 404
