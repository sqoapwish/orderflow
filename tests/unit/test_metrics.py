from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.core.metrics import MetricsRegistry, OutboxMetricsSnapshot
from orderflow.main import create_app
from orderflow.schemas.health import ComponentHealth


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


class FixedOutboxMetricsProvider:
    async def snapshot(self) -> OutboxMetricsSnapshot:
        return OutboxMetricsSnapshot(
            pending=2,
            published=7,
            dead_letter=1,
            delivery_attempts=4,
            oldest_pending_age_seconds=12.5,
        )


class BrokenOutboxMetricsProvider:
    async def snapshot(self) -> OutboxMetricsSnapshot:
        raise ConnectionError


@pytest.fixture
async def metrics_client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(
        test_settings,
        readiness_checker=HealthyChecker(),
        outbox_metrics_provider=FixedOutboxMetricsProvider(),
    )
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_metrics_endpoint_exposes_http_and_persistent_outbox_metrics(
    metrics_client: AsyncClient,
) -> None:
    health = await metrics_client.get("/api/v1/health/live")
    missing = await metrics_client.get("/missing")
    metrics = await metrics_client.get("/metrics")

    assert health.status_code == 200
    assert missing.status_code == 404
    assert metrics.status_code == 200
    assert metrics.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    body = metrics.text
    assert 'orderflow_build_info{version="1.0.0"} 1' in body
    assert (
        'orderflow_http_requests_total{method="GET",route="/api/v1/health/live",status="200"} 1'
        in body
    )
    assert 'orderflow_http_requests_total{method="GET",route="unmatched",status="404"} 1' in body
    assert 'orderflow_outbox_events{status="pending"} 2' in body
    assert 'orderflow_outbox_events{status="dead_letter"} 1' in body
    assert "orderflow_outbox_delivery_attempts_total 4" in body
    assert "orderflow_outbox_oldest_pending_age_seconds 12.500" in body


async def test_metrics_endpoint_stays_available_when_outbox_snapshot_fails(
    test_settings: Settings,
) -> None:
    app = create_app(
        test_settings,
        readiness_checker=HealthyChecker(),
        outbox_metrics_provider=BrokenOutboxMetricsProvider(),
    )
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "orderflow_outbox_metrics_scrape_success 0" in response.text


def test_registry_escapes_prometheus_labels() -> None:
    registry = MetricsRegistry()
    registry.request_started()
    registry.request_finished(
        method="GET",
        route='/quoted"route\\path',
        status_code=200,
        duration_seconds=0.02,
    )

    rendered = registry.render(
        version='0.8.0"dev',
        outbox=OutboxMetricsSnapshot(),
        outbox_scrape_success=True,
    )

    assert 'version="0.8.0\\"dev"' in rendered
    assert 'route="/quoted\\"route\\\\path"' in rendered
