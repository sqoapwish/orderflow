from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Environment, Settings
from orderflow.main import create_app
from orderflow.schemas.health import ComponentHealth


class HealthyReadinessChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {
            "postgresql": ComponentHealth(status="up", latency_ms=1.1),
            "redis": ComponentHealth(status="up", latency_ms=0.7),
            "rabbitmq": ComponentHealth(status="up", latency_ms=1.4),
        }


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        database_url="postgresql+asyncpg://orderflow:orderflow@localhost:5435/orderflow_test",
        redis_url="redis://localhost:6379/15",
        rabbitmq_url="amqp://guest:guest@localhost:5672//",
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(test_settings, readiness_checker=HealthyReadinessChecker())
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client
