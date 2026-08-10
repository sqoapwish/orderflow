from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.schemas.health import ComponentHealth


class DegradedReadinessChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {
            "postgresql": ComponentHealth(status="up", latency_ms=1.0),
            "redis": ComponentHealth(status="down", latency_ms=2000.0),
            "rabbitmq": ComponentHealth(status="up", latency_ms=1.2),
        }


async def test_readiness_returns_503_when_component_is_down() -> None:
    settings = Settings(_env_file=None)
    app = create_app(settings, readiness_checker=DegradedReadinessChecker())

    async with (
        LifespanManager(app),
        AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["components"]["redis"]["status"] == "down"
