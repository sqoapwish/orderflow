from dataclasses import dataclass

from redis.asyncio import Redis

from orderflow.core.config import Settings
from orderflow.infrastructure.database import Database


@dataclass(slots=True)
class InfrastructureResources:
    database: Database
    redis: Redis

    @classmethod
    def create(cls, settings: Settings) -> "InfrastructureResources":
        return cls(
            database=Database(settings),
            redis=Redis.from_url(settings.redis_url, decode_responses=True),
        )

    async def close(self) -> None:
        await self.redis.aclose()
        await self.database.close()
