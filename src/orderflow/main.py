from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from orderflow import __version__
from orderflow.api.router import build_api_router
from orderflow.core.config import Settings
from orderflow.core.correlation import correlation_id_middleware
from orderflow.core.errors import register_error_handlers
from orderflow.core.logging import configure_logging
from orderflow.core.metrics import MetricsRegistry, OutboxMetricsProvider, build_metrics_middleware
from orderflow.infrastructure.health import InfrastructureReadinessChecker, ReadinessChecker
from orderflow.infrastructure.metrics import DatabaseOutboxMetricsProvider
from orderflow.infrastructure.resources import InfrastructureResources


def create_app(
    settings: Settings | None = None,
    readiness_checker: ReadinessChecker | None = None,
    outbox_metrics_provider: OutboxMetricsProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    configure_logging(resolved_settings.log_level)
    resources = InfrastructureResources.create(resolved_settings)
    resolved_readiness_checker = readiness_checker or InfrastructureReadinessChecker(
        resolved_settings,
        resources.database,
        resources.redis,
    )
    metrics_registry = MetricsRegistry()
    resolved_metrics_provider = outbox_metrics_provider or DatabaseOutboxMetricsProvider(
        resources.database
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger = structlog.get_logger()
        logger.info("application_started", version=__version__)
        try:
            yield
        finally:
            await resources.close()
            logger.info("application_stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=__version__,
        debug=resolved_settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.resources = resources
    app.state.readiness_checker = resolved_readiness_checker
    app.state.metrics_registry = metrics_registry
    app.state.outbox_metrics_provider = resolved_metrics_provider
    app.middleware("http")(build_metrics_middleware(metrics_registry))
    app.middleware("http")(correlation_id_middleware)
    register_error_handlers(app)
    app.include_router(build_api_router(resolved_settings))
    return app


app = create_app()
