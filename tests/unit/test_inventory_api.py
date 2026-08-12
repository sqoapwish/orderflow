from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.auth.dependencies import get_auth_service
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.inventory.dependencies import get_inventory_service
from orderflow.modules.inventory.service import InventoryService
from orderflow.schemas.health import ComponentHealth
from tests.fakes import build_auth_service, build_inventory_service


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class InventoryApiContext:
    client: AsyncClient
    service: InventoryService
    product_id: UUID
    manager_headers: dict[str, str]
    customer_headers: dict[str, str]


@pytest.fixture
async def inventory_api(test_settings: Settings) -> AsyncIterator[InventoryApiContext]:
    product_id = uuid4()
    auth_service, _, _, _ = build_auth_service(test_settings)
    inventory_service, _, _ = build_inventory_service(product_id)
    manager = await auth_service.register("inventory-manager@example.com", "Strong-password-42")
    manager.user.role = UserRole.MANAGER
    customer = await auth_service.register("inventory-customer@example.com", "Strong-password-42")
    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_inventory_service] = lambda: inventory_service

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield InventoryApiContext(
            client=client,
            service=inventory_service,
            product_id=product_id,
            manager_headers={"Authorization": f"Bearer {manager.tokens.access_token}"},
            customer_headers={"Authorization": f"Bearer {customer.tokens.access_token}"},
        )


async def create_warehouse(
    context: InventoryApiContext,
    *,
    name: str = "Main warehouse",
    code: str = "main",
) -> dict[str, object]:
    response = await context.client.post(
        "/api/v1/inventory/warehouses",
        headers=context.manager_headers,
        json={"name": name, "code": code, "location": "Moscow"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


async def test_manager_can_manage_stock_movements_and_reservations(
    inventory_api: InventoryApiContext,
) -> None:
    warehouse = await create_warehouse(inventory_api)
    warehouse_id = str(warehouse["id"])
    assert warehouse["code"] == "MAIN"

    receipt = await inventory_api.client.post(
        "/api/v1/inventory/stock/receipts",
        headers=inventory_api.manager_headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": str(inventory_api.product_id),
            "quantity": 10,
            "reason": "Supplier delivery",
        },
    )
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["balance"]["available"] == 10

    reservation = await inventory_api.client.post(
        "/api/v1/inventory/reservations",
        headers=inventory_api.manager_headers,
        json={
            "reservation_key": "order:42:item:1",
            "warehouse_id": warehouse_id,
            "product_id": str(inventory_api.product_id),
            "quantity": 6,
        },
    )
    assert reservation.status_code == 201, reservation.text
    reservation_body = reservation.json()
    assert reservation_body["status"] == "active"

    replay = await inventory_api.client.post(
        "/api/v1/inventory/reservations",
        headers=inventory_api.manager_headers,
        json={
            "reservation_key": "order:42:item:1",
            "warehouse_id": warehouse_id,
            "product_id": str(inventory_api.product_id),
            "quantity": 6,
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == reservation_body["id"]

    stock = await inventory_api.client.get(
        "/api/v1/inventory/stock",
        headers=inventory_api.manager_headers,
        params={"warehouse_id": warehouse_id, "product_id": str(inventory_api.product_id)},
    )
    assert stock.status_code == 200
    assert stock.json()["items"][0]["available"] == 4

    released = await inventory_api.client.post(
        f"/api/v1/inventory/reservations/{reservation_body['id']}/release",
        headers=inventory_api.manager_headers,
    )
    assert released.status_code == 200
    assert released.json()["status"] == "released"

    write_off = await inventory_api.client.post(
        "/api/v1/inventory/stock/write-offs",
        headers=inventory_api.manager_headers,
        json={
            "warehouse_id": warehouse_id,
            "product_id": str(inventory_api.product_id),
            "quantity": 2,
            "reason": "Damaged",
        },
    )
    assert write_off.status_code == 201
    assert write_off.json()["balance"]["on_hand"] == 8

    movements = await inventory_api.client.get(
        "/api/v1/inventory/movements",
        headers=inventory_api.manager_headers,
        params={"product_id": str(inventory_api.product_id), "page_size": 2},
    )
    assert movements.status_code == 200
    assert movements.json()["total"] == 4
    assert movements.json()["total_pages"] == 2


async def test_transfer_adjustment_and_warehouse_archive_rules(
    inventory_api: InventoryApiContext,
) -> None:
    source = await create_warehouse(inventory_api)
    target = await create_warehouse(inventory_api, name="North warehouse", code="north")
    receipt_payload = {
        "warehouse_id": source["id"],
        "product_id": str(inventory_api.product_id),
        "quantity": 5,
    }
    assert (
        await inventory_api.client.post(
            "/api/v1/inventory/stock/receipts",
            headers=inventory_api.manager_headers,
            json=receipt_payload,
        )
    ).status_code == 201

    transfer = await inventory_api.client.post(
        "/api/v1/inventory/stock/transfers",
        headers=inventory_api.manager_headers,
        json={
            "source_warehouse_id": source["id"],
            "target_warehouse_id": target["id"],
            "product_id": str(inventory_api.product_id),
            "quantity": 2,
        },
    )
    assert transfer.status_code == 201, transfer.text
    assert transfer.json()["source"]["on_hand"] == 3
    assert transfer.json()["target"]["on_hand"] == 2

    adjustment = await inventory_api.client.post(
        "/api/v1/inventory/stock/adjustments",
        headers=inventory_api.manager_headers,
        json={
            "warehouse_id": target["id"],
            "product_id": str(inventory_api.product_id),
            "on_hand": 3,
            "reason": "Cycle count",
        },
    )
    assert adjustment.status_code == 201
    assert adjustment.json()["balance"]["on_hand"] == 3

    blocked_archive = await inventory_api.client.delete(
        f"/api/v1/inventory/warehouses/{target['id']}",
        headers=inventory_api.manager_headers,
    )
    assert blocked_archive.status_code == 409
    assert blocked_archive.json()["error"]["code"] == "warehouse_not_empty"


async def test_inventory_access_validation_and_standard_errors(
    inventory_api: InventoryApiContext,
) -> None:
    payload = {"name": "Main warehouse", "code": "MAIN"}
    customer = await inventory_api.client.post(
        "/api/v1/inventory/warehouses",
        headers=inventory_api.customer_headers,
        json=payload,
    )
    anonymous = await inventory_api.client.get("/api/v1/inventory/warehouses")
    created = await inventory_api.client.post(
        "/api/v1/inventory/warehouses",
        headers=inventory_api.manager_headers,
        json=payload,
    )
    duplicate = await inventory_api.client.post(
        "/api/v1/inventory/warehouses",
        headers=inventory_api.manager_headers,
        json={"name": "Duplicate", "code": "main"},
    )
    empty_patch = await inventory_api.client.patch(
        f"/api/v1/inventory/warehouses/{created.json()['id']}",
        headers=inventory_api.manager_headers,
        json={},
    )
    invalid_transfer = await inventory_api.client.post(
        "/api/v1/inventory/stock/transfers",
        headers=inventory_api.manager_headers,
        json={
            "source_warehouse_id": created.json()["id"],
            "target_warehouse_id": created.json()["id"],
            "product_id": str(inventory_api.product_id),
            "quantity": 1,
        },
    )

    assert customer.status_code == 403
    assert customer.json()["error"]["code"] == "insufficient_role"
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "invalid_access_token"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "warehouse_code_conflict"
    assert empty_patch.status_code == 422
    assert invalid_transfer.status_code == 422
    assert invalid_transfer.json()["error"]["code"] == "validation_error"


async def test_inventory_openapi_contract_is_protected(
    inventory_api: InventoryApiContext,
) -> None:
    response = await inventory_api.client.get("/api/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    expected_paths = {
        "/api/v1/inventory/warehouses",
        "/api/v1/inventory/warehouses/{warehouse_id}",
        "/api/v1/inventory/stock",
        "/api/v1/inventory/stock/receipts",
        "/api/v1/inventory/stock/write-offs",
        "/api/v1/inventory/stock/adjustments",
        "/api/v1/inventory/stock/transfers",
        "/api/v1/inventory/movements",
        "/api/v1/inventory/reservations",
        "/api/v1/inventory/reservations/{reservation_id}",
        "/api/v1/inventory/reservations/{reservation_id}/release",
        "/api/v1/inventory/reservations/{reservation_id}/consume",
    }

    assert expected_paths <= set(paths)
    for path in expected_paths:
        for operation in paths[path].values():
            assert operation["security"] == [{"HTTPBearer": []}]
