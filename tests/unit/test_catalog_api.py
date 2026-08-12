from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.auth.dependencies import get_auth_service
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.service import AuthService
from orderflow.modules.catalog.dependencies import get_catalog_service
from orderflow.modules.catalog.service import CatalogService
from orderflow.schemas.health import ComponentHealth
from tests.fakes import build_auth_service, build_catalog_service


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class CatalogApiContext:
    client: AsyncClient
    auth_service: AuthService
    catalog_service: CatalogService
    manager_headers: dict[str, str]
    customer_headers: dict[str, str]


@pytest.fixture
async def catalog_api(test_settings: Settings) -> AsyncIterator[CatalogApiContext]:
    auth_service, _, _, _ = build_auth_service(test_settings)
    catalog_service, _ = build_catalog_service()
    manager = await auth_service.register("manager@example.com", "Strong-password-42")
    manager.user.role = UserRole.MANAGER
    customer = await auth_service.register("customer@example.com", "Strong-password-42")
    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_catalog_service] = lambda: catalog_service

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield CatalogApiContext(
            client=client,
            auth_service=auth_service,
            catalog_service=catalog_service,
            manager_headers={
                "Authorization": f"Bearer {manager.tokens.access_token}",
            },
            customer_headers={
                "Authorization": f"Bearer {customer.tokens.access_token}",
            },
        )


async def test_manager_can_build_search_and_archive_catalog(
    catalog_api: CatalogApiContext,
) -> None:
    category_response = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.manager_headers,
        json={"name": "Laptops", "slug": "laptops"},
    )
    assert category_response.status_code == 201
    category = category_response.json()

    product_response = await catalog_api.client.post(
        "/api/v1/catalog/products",
        headers=catalog_api.manager_headers,
        json={
            "category_id": category["id"],
            "name": "Laptop Pro",
            "slug": "laptop-pro",
            "sku": "laptop-pro.16",
            "description": "Professional laptop",
            "price_minor": 199900,
            "currency": "rub",
            "image_url": "https://example.com/laptop.jpg",
        },
    )
    assert product_response.status_code == 201
    product = product_response.json()
    assert product["sku"] == "LAPTOP-PRO.16"
    assert product["currency"] == "RUB"

    list_response = await catalog_api.client.get(
        "/api/v1/catalog/products",
        params={
            "search": "pro.16",
            "category_id": category["id"],
            "min_price_minor": 100000,
            "max_price_minor": 250000,
            "sort_by": "price",
            "sort_direction": "asc",
            "page": 1,
            "page_size": 10,
        },
    )
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["total_pages"] == 1
    assert list_response.json()["items"][0]["id"] == product["id"]

    detail_response = await catalog_api.client.get("/api/v1/catalog/products/laptop-pro")
    assert detail_response.status_code == 200

    update_response = await catalog_api.client.patch(
        f"/api/v1/catalog/products/id/{product['id']}",
        headers=catalog_api.manager_headers,
        json={
            "category_id": category["id"],
            "name": "Laptop Pro 2026",
            "slug": "laptop-pro-2026",
            "sku": "new-sku",
            "description": None,
            "price_minor": 179900,
            "currency": "usd",
            "image_url": None,
            "is_active": True,
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["price_minor"] == 179900
    assert updated["sku"] == "NEW-SKU"
    assert updated["currency"] == "USD"
    assert updated["description"] is None
    assert updated["image_url"] is None

    archive_response = await catalog_api.client.delete(
        f"/api/v1/catalog/products/id/{product['id']}",
        headers=catalog_api.manager_headers,
    )
    assert archive_response.status_code == 204
    assert (await catalog_api.client.get("/api/v1/catalog/products")).json()["total"] == 0
    assert (
        await catalog_api.client.get("/api/v1/catalog/products/laptop-pro-2026")
    ).status_code == 404


async def test_public_category_endpoints_hide_archived_records(
    catalog_api: CatalogApiContext,
) -> None:
    created_response = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.manager_headers,
        json={"name": "Laptops", "slug": "laptops"},
    )
    category = created_response.json()

    list_response = await catalog_api.client.get("/api/v1/catalog/categories")
    detail_response = await catalog_api.client.get("/api/v1/catalog/categories/laptops")
    update_response = await catalog_api.client.patch(
        f"/api/v1/catalog/categories/id/{category['id']}",
        headers=catalog_api.manager_headers,
        json={"name": "Portable computers", "parent_id": None},
    )

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Portable computers"

    archive_response = await catalog_api.client.delete(
        f"/api/v1/catalog/categories/id/{category['id']}",
        headers=catalog_api.manager_headers,
    )
    assert archive_response.status_code == 204
    assert (await catalog_api.client.get("/api/v1/catalog/categories")).json()["total"] == 0
    assert (await catalog_api.client.get("/api/v1/catalog/categories/laptops")).status_code == 404


async def test_customer_and_anonymous_user_cannot_write_catalog(
    catalog_api: CatalogApiContext,
) -> None:
    payload = {"name": "Laptops", "slug": "laptops"}

    customer_response = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.customer_headers,
        json=payload,
    )
    anonymous_response = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        json=payload,
    )

    assert customer_response.status_code == 403
    assert customer_response.json()["error"]["code"] == "insufficient_role"
    assert anonymous_response.status_code == 401
    assert anonymous_response.json()["error"]["code"] == "invalid_access_token"


async def test_catalog_validation_and_conflicts_use_standard_errors(
    catalog_api: CatalogApiContext,
) -> None:
    created = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.manager_headers,
        json={"name": "Laptops", "slug": "laptops"},
    )
    category_id = created.json()["id"]

    duplicate = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.manager_headers,
        json={"name": "Other", "slug": "laptops"},
    )
    empty_patch = await catalog_api.client.patch(
        f"/api/v1/catalog/categories/id/{category_id}",
        headers=catalog_api.manager_headers,
        json={},
    )
    invalid_slug = await catalog_api.client.post(
        "/api/v1/catalog/categories",
        headers=catalog_api.manager_headers,
        json={"name": "Invalid", "slug": "Invalid Slug"},
    )
    invalid_range = await catalog_api.client.get(
        "/api/v1/catalog/products",
        params={"min_price_minor": 200, "max_price_minor": 100},
    )
    whitespace_search = await catalog_api.client.get(
        "/api/v1/catalog/products",
        params={"search": "   "},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "category_slug_conflict"
    assert empty_patch.status_code == 422
    assert empty_patch.json()["error"]["code"] == "validation_error"
    assert invalid_slug.status_code == 422
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_price_range"
    assert whitespace_search.status_code == 422
    assert whitespace_search.json()["error"]["code"] == "validation_error"


async def test_catalog_openapi_contract_marks_only_writes_as_protected(
    catalog_api: CatalogApiContext,
) -> None:
    response = await catalog_api.client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    paths = schema["paths"]
    expected_paths = {
        "/api/v1/catalog/categories",
        "/api/v1/catalog/categories/{slug}",
        "/api/v1/catalog/categories/id/{category_id}",
        "/api/v1/catalog/products",
        "/api/v1/catalog/products/{slug}",
        "/api/v1/catalog/products/id/{product_id}",
    }

    assert expected_paths <= set(paths)
    assert "security" not in paths["/api/v1/catalog/categories"]["get"]
    assert "security" not in paths["/api/v1/catalog/products"]["get"]
    assert paths["/api/v1/catalog/categories"]["post"]["security"] == [{"HTTPBearer": []}]
    assert paths["/api/v1/catalog/products/id/{product_id}"]["delete"]["security"] == [
        {"HTTPBearer": []}
    ]
