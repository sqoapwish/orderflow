from typing import Protocol

from redis.asyncio import Redis


class AnalyticsCacheProtocol(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None: ...


class RedisAnalyticsCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        if value is None:
            return None
        return value if isinstance(value, str) else value.decode()

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)
