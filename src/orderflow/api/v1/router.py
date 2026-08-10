from fastapi import APIRouter

from orderflow.api.v1.routes.health import router as health_router

router = APIRouter()
router.include_router(health_router, prefix="/health", tags=["Health"])
