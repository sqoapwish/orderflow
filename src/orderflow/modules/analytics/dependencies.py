from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.modules.analytics.cache import RedisAnalyticsCache
from orderflow.modules.analytics.repository import AnalyticsRepository
from orderflow.modules.analytics.service import AnalyticsService
from orderflow.modules.auth.dependencies import get_database_session


def get_analytics_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AnalyticsService:
    resources = cast(InfrastructureResources, request.app.state.resources)
    settings = cast(Settings, request.app.state.settings)
    return AnalyticsService(
        AnalyticsRepository(session),
        RedisAnalyticsCache(resources.redis),
        cache_ttl_seconds=settings.analytics_cache_ttl_seconds,
    )
