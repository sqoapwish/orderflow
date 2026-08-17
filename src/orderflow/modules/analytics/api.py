from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from orderflow.modules.analytics.dependencies import get_analytics_service
from orderflow.modules.analytics.schemas import (
    LowStockPageResponse,
    SalesAnalyticsResponse,
    TopProductsResponse,
)
from orderflow.modules.analytics.service import AnalyticsService
from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User

router = APIRouter()

AnalyticsServiceDependency = Annotated[AnalyticsService, Depends(get_analytics_service)]
AnalyticsReaderDependency = Annotated[
    User,
    Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN)),
]


@router.get(
    "/sales",
    response_model=SalesAnalyticsResponse,
    summary="Get sales and payment analytics",
)
async def get_sales_analytics(
    service: AnalyticsServiceDependency,
    _: AnalyticsReaderDependency,
    date_from: date | None = None,
    date_to: date | None = None,
) -> SalesAnalyticsResponse:
    return await service.sales(date_from=date_from, date_to=date_to)


@router.get(
    "/products/top",
    response_model=TopProductsResponse,
    summary="Get top-selling products",
)
async def get_top_products(
    service: AnalyticsServiceDependency,
    _: AnalyticsReaderDependency,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> TopProductsResponse:
    return await service.top_products(
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.get(
    "/inventory/low-stock",
    response_model=LowStockPageResponse,
    summary="Get active stock balances at or below a threshold",
)
async def get_low_stock(
    service: AnalyticsServiceDependency,
    _: AnalyticsReaderDependency,
    threshold: Annotated[int, Query(ge=0, le=1_000_000_000)] = 10,
    warehouse_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LowStockPageResponse:
    return await service.low_stock(
        threshold=threshold,
        warehouse_id=warehouse_id,
        page=page,
        page_size=page_size,
    )
