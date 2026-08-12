from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.auth.dependencies import get_database_session
from orderflow.modules.catalog.repository import CatalogRepository
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.repository import InventoryRepository
from orderflow.modules.inventory.service import InventoryService


def get_inventory_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> InventoryService:
    return InventoryService(
        InventoryRepository(session),
        CatalogService(CatalogRepository(session)),
    )
