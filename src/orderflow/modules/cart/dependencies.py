from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.auth.dependencies import get_database_session
from orderflow.modules.cart.repository import CartRepository
from orderflow.modules.cart.service import CartService
from orderflow.modules.catalog.repository import CatalogRepository
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.repository import InventoryRepository
from orderflow.modules.inventory.service import InventoryService


def get_cart_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> CartService:
    catalog = CatalogService(CatalogRepository(session))
    inventory = InventoryService(InventoryRepository(session), catalog)
    return CartService(CartRepository(session), catalog, inventory)
