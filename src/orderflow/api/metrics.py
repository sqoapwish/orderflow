from typing import cast

import structlog
from fastapi import APIRouter, Request, Response

from orderflow import __version__
from orderflow.core.metrics import MetricsRegistry, OutboxMetricsProvider, OutboxMetricsSnapshot

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(request: Request) -> Response:
    registry = cast(MetricsRegistry, request.app.state.metrics_registry)
    provider = cast(OutboxMetricsProvider, request.app.state.outbox_metrics_provider)
    scrape_success = True
    try:
        outbox = await provider.snapshot()
    except Exception as exc:
        scrape_success = False
        outbox = OutboxMetricsSnapshot()
        structlog.get_logger().error(
            "outbox_metrics_snapshot_failed",
            error_type=type(exc).__name__,
        )
    return Response(
        content=registry.render(
            version=__version__,
            outbox=outbox,
            outbox_scrape_success=scrape_success,
        ),
        headers={"Content-Type": PROMETHEUS_CONTENT_TYPE},
    )
