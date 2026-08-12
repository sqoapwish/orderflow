from fastapi import APIRouter

from orderflow.api.v1.routes.health import router as health_router
from orderflow.modules.auth.api import router as auth_router
from orderflow.modules.catalog.api import router as catalog_router
from orderflow.modules.inventory.api import router as inventory_router

router = APIRouter()
router.include_router(health_router, prefix="/health", tags=["Health"])
router.include_router(auth_router, prefix="/auth", tags=["Auth"])
router.include_router(catalog_router, prefix="/catalog", tags=["Catalog"])
router.include_router(inventory_router, prefix="/inventory", tags=["Inventory"])
