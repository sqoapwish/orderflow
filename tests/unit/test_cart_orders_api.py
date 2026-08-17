from collections.abc import AsyncIterator
from dataclasses import dataclass
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
from orderflow.schemas.health import ComponentHealth
from tests.fakes import (
    FakeCartRepository,
    FakeCatalogRepository,
    FakeInventoryRepository,
    FakeOrderRepository,
    FakeOutboxRepository,
    build_auth_service,
)


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class CartOrdersApiContext:
    client: AsyncClient
    product_id: UUID
    warehouse_id: UUID
    customer_headers: dict[str, str]
    stranger_headers: dict[str, str]
    manager_headers: dict[str, str]


@pytest.fixture
async def cart_orders_api(test_settings: Settings) -> AsyncIterator[CartOrdersApiContext]:
    auth_service, _, _, _ = build_auth_service(test_settings)
    customer = await auth_service.register("cart-customer@example.com", "Strong-password-42")
    stranger = await auth_service.register("cart-stranger@example.com", "Strong-password-42")
    manager = await auth_service.register("cart-manager@example.com", "Strong-password-42")
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
        quantity=3,
        reason="API test delivery",
        actor_id=manager.user.id,
    )
    cart = CartService(FakeCartRepository(), catalog, inventory)
    orders = OrderService(
        FakeOrderRepository(),
        cart,
        catalog,
        inventory,
        FakeOutboxRepository(),
    )

    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_cart_service] = lambda: cart
    app.dependency_overrides[get_order_service] = lambda: orders
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield CartOrdersApiContext(
            client=client,
            product_id=product.id,
            warehouse_id=warehouse.id,
            customer_headers={"Authorization": f"Bearer {customer.tokens.access_token}"},
            stranger_headers={"Authorization": f"Bearer {stranger.tokens.access_token}"},
            manager_headers={"Authorization": f"Bearer {manager.tokens.access_token}"},
        )


async def test_customer_cart_checkout_replay_and_order_visibility(
    cart_orders_api: CartOrdersApiContext,
) -> None:
    context = cart_orders_api
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
    assert added.json()["total_minor"] == 399_800
    item_id = added.json()["items"][0]["id"]

    updated = await context.client.patch(
        f"/api/v1/cart/items/{item_id}",
        headers=context.customer_headers,
        json={"quantity": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["items"][0]["quantity"] == 1

    missing_key = await context.client.post(
        "/api/v1/orders/checkout",
        headers=context.customer_headers,
    )
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "validation_error"

    checkout_headers = {**context.customer_headers, "Idempotency-Key": "api-checkout-1"}
    created = await context.client.post("/api/v1/orders/checkout", headers=checkout_headers)
    replay = await context.client.post("/api/v1/orders/checkout", headers=checkout_headers)
    assert created.status_code == 201, created.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == created.json()["id"]
    assert created.json()["items"][0]["product_sku"] == "LAPTOP-PRO"

    own_list = await context.client.get("/api/v1/orders", headers=context.customer_headers)
    stranger_detail = await context.client.get(
        f"/api/v1/orders/{created.json()['id']}",
        headers=context.stranger_headers,
    )
    manager_detail = await context.client.get(
        f"/api/v1/orders/{created.json()['id']}",
        headers=context.manager_headers,
    )
    assert own_list.status_code == 200
    assert own_list.json()["total"] == 1
    assert stranger_detail.status_code == 404
    assert stranger_detail.json()["error"]["code"] == "order_not_found"
    assert manager_detail.status_code == 200

    manager_cart = await context.client.get("/api/v1/cart", headers=context.manager_headers)
    assert manager_cart.status_code == 403


async def test_cart_and_orders_openapi_contract(cart_orders_api: CartOrdersApiContext) -> None:
    response = await cart_orders_api.client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    expected_paths = {
        "/api/v1/cart",
        "/api/v1/cart/items",
        "/api/v1/cart/items/{item_id}",
        "/api/v1/orders",
        "/api/v1/orders/checkout",
        "/api/v1/orders/{order_id}",
    }
    assert expected_paths <= set(paths)
    checkout_parameters = paths["/api/v1/orders/checkout"]["post"]["parameters"]
    assert any(parameter["name"] == "Idempotency-Key" for parameter in checkout_parameters)
    for path in expected_paths:
        for operation in paths[path].values():
            assert operation["security"] == [{"HTTPBearer": []}]
