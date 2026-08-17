from fastapi import APIRouter

from orderflow.api.metrics import router as metrics_router
from orderflow.api.v1.router import router as v1_router
from orderflow.core.config import Settings


def build_api_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    router.include_router(metrics_router, tags=["Observability"])
    router.include_router(v1_router, prefix=settings.api_v1_prefix)
    return router
