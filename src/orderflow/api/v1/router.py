from fastapi import APIRouter

from orderflow.api.v1.routes.health import router as health_router
from orderflow.modules.auth.api import router as auth_router

router = APIRouter()
router.include_router(health_router, prefix="/health", tags=["Health"])
router.include_router(auth_router, prefix="/auth", tags=["Auth"])
