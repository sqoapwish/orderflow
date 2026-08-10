import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol, cast

import aio_pika
from redis.asyncio import Redis
from sqlalchemy import text

from orderflow.core.config import Settings
from orderflow.infrastructure.database import Database
from orderflow.schemas.health import ComponentHealth

HealthProbe = Callable[[], Awaitable[None]]


class ReadinessChecker(Protocol):
    async def check(self) -> dict[str, ComponentHealth]: ...


class InfrastructureReadinessChecker:
    def __init__(self, settings: Settings, database: Database, redis: Redis) -> None:
        self._settings = settings
        self._database = database
        self._redis = redis

    async def check(self) -> dict[str, ComponentHealth]:
        names = ("postgresql", "redis", "rabbitmq")
        probes = (self._check_database, self._check_redis, self._check_rabbitmq)
        results = await asyncio.gather(
            *(self._run_probe(probe) for probe in probes),
        )
        return dict(zip(names, results, strict=True))

    async def _run_probe(self, probe: HealthProbe) -> ComponentHealth:
        started_at = perf_counter()
        try:
            async with asyncio.timeout(self._settings.health_check_timeout_seconds):
                await probe()
        except Exception:
            return ComponentHealth(
                status="down",
                latency_ms=round((perf_counter() - started_at) * 1000, 2),
            )
        return ComponentHealth(
            status="up",
            latency_ms=round((perf_counter() - started_at) * 1000, 2),
        )

    async def _check_database(self) -> None:
        async with self._database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def _check_redis(self) -> None:
        await cast(Awaitable[bool], self._redis.ping())

    async def _check_rabbitmq(self) -> None:
        connection = await aio_pika.connect(self._settings.rabbitmq_url)
        await connection.close()
