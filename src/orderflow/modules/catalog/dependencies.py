from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.auth.dependencies import get_database_session
from orderflow.modules.catalog.repository import CatalogRepository
from orderflow.modules.catalog.service import CatalogService


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> CatalogService:
    return CatalogService(CatalogRepository(session))
