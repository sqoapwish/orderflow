from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.analytics.dependencies import get_analytics_service
from orderflow.modules.analytics.domain import CurrencySalesRow, LowStockRow, TopProductRow
from orderflow.modules.analytics.service import AnalyticsService
from orderflow.modules.auth.dependencies import get_auth_service
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.schemas.health import ComponentHealth
from tests.fakes import (
    FakeAnalyticsCache,
    FakeAnalyticsRepository,
    build_auth_service,
)


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class AnalyticsApiContext:
    client: AsyncClient
    repository: FakeAnalyticsRepository
    actor: User
    token: str
    warehouse_id: str


@pytest.fixture
async def analytics_api(test_settings: Settings) -> AsyncIterator[AnalyticsApiContext]:
    auth_service, _, _, _ = build_auth_service(test_settings)
    registration = await auth_service.register(
        "analytics-manager@example.com",
        "Strong-password-42",
    )
    registration.user.role = UserRole.MANAGER
    repository = FakeAnalyticsRepository()
    product_id = uuid4()
    warehouse_id = uuid4()
    repository.currency_sales = [
        CurrencySalesRow(
            currency="RUB",
            paid_orders=2,
            gross_revenue_minor=25_000,
            failed_payments=1,
            refunded_payments=1,
            refunded_amount_minor=5_000,
        )
    ]
    repository.top_product_rows = [
        TopProductRow(
            product_id=product_id,
            product_name="Mouse",
            product_sku="MOUSE-1",
            currency="RUB",
            paid_quantity=3,
            gross_revenue_minor=25_000,
            paid_orders=2,
        )
    ]
    repository.low_stock_rows = [
        LowStockRow(
            warehouse_id=warehouse_id,
            warehouse_name="Main",
            warehouse_code="MAIN",
            product_id=product_id,
            product_name="Mouse",
            product_sku="MOUSE-1",
            on_hand=4,
            reserved=1,
            available=3,
        )
    ]
    repository.low_stock_total = 1
    service = AnalyticsService(
        repository,
        FakeAnalyticsCache(),
        cache_ttl_seconds=30,
        today_provider=lambda: date(2026, 8, 17),
    )
    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_analytics_service] = lambda: service
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield AnalyticsApiContext(
            client=client,
            repository=repository,
            actor=registration.user,
            token=registration.tokens.access_token,
            warehouse_id=str(warehouse_id),
        )


async def test_manager_can_read_all_analytics_reports(
    analytics_api: AnalyticsApiContext,
) -> None:
    headers = {"Authorization": f"Bearer {analytics_api.token}"}
    period = {"date_from": "2026-08-01", "date_to": "2026-08-17"}

    sales = await analytics_api.client.get(
        "/api/v1/analytics/sales",
        headers=headers,
        params=period,
    )
    products = await analytics_api.client.get(
        "/api/v1/analytics/products/top",
        headers=headers,
        params={**period, "limit": 5},
    )
    stock = await analytics_api.client.get(
        "/api/v1/analytics/inventory/low-stock",
        headers=headers,
        params={"threshold": 3, "warehouse_id": analytics_api.warehouse_id},
    )

    assert sales.status_code == 200
    assert sales.json()["currencies"][0]["net_revenue_minor"] == 20_000
    assert products.status_code == 200
    assert products.json()["items"][0]["product_sku"] == "MOUSE-1"
    assert analytics_api.repository.top_product_calls[0][1] == 5
    assert stock.status_code == 200
    assert stock.json()["items"][0]["available"] == 3


async def test_customer_cannot_read_analytics(analytics_api: AnalyticsApiContext) -> None:
    analytics_api.actor.role = UserRole.CUSTOMER

    response = await analytics_api.client.get(
        "/api/v1/analytics/sales",
        headers={"Authorization": f"Bearer {analytics_api.token}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_role"


async def test_analytics_api_validates_period_and_query_limits(
    analytics_api: AnalyticsApiContext,
) -> None:
    headers = {"Authorization": f"Bearer {analytics_api.token}"}
    inverted = await analytics_api.client.get(
        "/api/v1/analytics/sales",
        headers=headers,
        params={"date_from": "2026-08-18", "date_to": "2026-08-17"},
    )
    too_many_days = await analytics_api.client.get(
        "/api/v1/analytics/sales",
        headers=headers,
        params={"date_from": "2025-08-16", "date_to": "2026-08-17"},
    )
    invalid_limit = await analytics_api.client.get(
        "/api/v1/analytics/products/top",
        headers=headers,
        params={"limit": 101},
    )

    assert inverted.status_code == 400
    assert inverted.json()["error"]["code"] == "invalid_analytics_period"
    assert too_many_days.status_code == 400
    assert too_many_days.json()["error"]["code"] == "analytics_period_too_large"
    assert invalid_limit.status_code == 422
