from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from math import ceil
from typing import TypeVar
from uuid import UUID

import structlog
from pydantic import BaseModel

from orderflow.modules.analytics.cache import AnalyticsCacheProtocol
from orderflow.modules.analytics.domain import (
    AnalyticsPeriod,
    CurrencySalesRow,
    DailySalesRow,
    LowStockRow,
    TopProductRow,
)
from orderflow.modules.analytics.errors import (
    AnalyticsPeriodTooLargeError,
    InvalidAnalyticsPeriodError,
)
from orderflow.modules.analytics.repository import AnalyticsRepositoryProtocol
from orderflow.modules.analytics.schemas import (
    AnalyticsPeriodResponse,
    CurrencySalesResponse,
    DailySalesResponse,
    LowStockPageResponse,
    LowStockResponse,
    SalesAnalyticsResponse,
    TopProductResponse,
    TopProductsResponse,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class AnalyticsService:
    def __init__(
        self,
        repository: AnalyticsRepositoryProtocol,
        cache: AnalyticsCacheProtocol,
        *,
        cache_ttl_seconds: int,
        maximum_period_days: int = 366,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._maximum_period_days = maximum_period_days
        self._today_provider = today_provider or (lambda: datetime.now(UTC).date())
        self._logger = structlog.get_logger()

    async def sales(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
    ) -> SalesAnalyticsResponse:
        period = self._resolve_period(date_from, date_to)
        key = f"orderflow:analytics:v1:sales:{period.date_from}:{period.date_to}"

        async def load() -> SalesAnalyticsResponse:
            currencies, daily = await self._repository.sales_summary(period)
            return SalesAnalyticsResponse(
                period=self._period_response(period),
                currencies=[self._currency_response(row) for row in currencies],
                daily=[self._daily_response(row) for row in daily],
            )

        return await self._cached(key, SalesAnalyticsResponse, load)

    async def top_products(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        limit: int,
    ) -> TopProductsResponse:
        period = self._resolve_period(date_from, date_to)
        key = f"orderflow:analytics:v1:top-products:{period.date_from}:{period.date_to}:{limit}"

        async def load() -> TopProductsResponse:
            rows = await self._repository.top_products(period, limit=limit)
            return TopProductsResponse(
                period=self._period_response(period),
                items=[self._top_product_response(row) for row in rows],
            )

        return await self._cached(key, TopProductsResponse, load)

    async def low_stock(
        self,
        *,
        threshold: int,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
    ) -> LowStockPageResponse:
        warehouse_key = str(warehouse_id) if warehouse_id is not None else "all"
        key = f"orderflow:analytics:v1:low-stock:{threshold}:{warehouse_key}:{page}:{page_size}"

        async def load() -> LowStockPageResponse:
            rows, total = await self._repository.low_stock(
                threshold=threshold,
                warehouse_id=warehouse_id,
                page=page,
                page_size=page_size,
            )
            return LowStockPageResponse(
                items=[self._low_stock_response(row) for row in rows],
                threshold=threshold,
                total=total,
                page=page,
                page_size=page_size,
                total_pages=ceil(total / page_size) if total else 0,
            )

        return await self._cached(key, LowStockPageResponse, load)

    def _resolve_period(
        self,
        date_from: date | None,
        date_to: date | None,
    ) -> AnalyticsPeriod:
        resolved_to = date_to or self._today_provider()
        resolved_from = date_from or (resolved_to - timedelta(days=29))
        if resolved_from > resolved_to:
            raise InvalidAnalyticsPeriodError
        inclusive_days = (resolved_to - resolved_from).days + 1
        if inclusive_days > self._maximum_period_days:
            raise AnalyticsPeriodTooLargeError(self._maximum_period_days)
        return AnalyticsPeriod(
            date_from=resolved_from,
            date_to=resolved_to,
            starts_at=datetime.combine(resolved_from, time.min, tzinfo=UTC),
            ends_before=datetime.combine(resolved_to + timedelta(days=1), time.min, tzinfo=UTC),
        )

    async def _cached(
        self,
        key: str,
        response_type: type[ResponseT],
        loader: Callable[[], Awaitable[ResponseT]],
    ) -> ResponseT:
        cached = await self._read_cache(key)
        if cached is not None:
            try:
                return response_type.model_validate_json(cached)
            except Exception as error:
                self._logger.warning(
                    "analytics_cache_payload_invalid",
                    cache_key=key,
                    error_type=type(error).__name__,
                )
        response = await loader()
        await self._write_cache(key, response.model_dump_json())
        return response

    async def _read_cache(self, key: str) -> str | None:
        try:
            return await self._cache.get(key)
        except Exception as error:
            self._logger.warning(
                "analytics_cache_read_failed",
                cache_key=key,
                error_type=type(error).__name__,
            )
            return None

    async def _write_cache(self, key: str, value: str) -> None:
        try:
            await self._cache.set(
                key,
                value,
                ttl_seconds=self._cache_ttl_seconds,
            )
        except Exception as error:
            self._logger.warning(
                "analytics_cache_write_failed",
                cache_key=key,
                error_type=type(error).__name__,
            )

    @staticmethod
    def _period_response(period: AnalyticsPeriod) -> AnalyticsPeriodResponse:
        return AnalyticsPeriodResponse(date_from=period.date_from, date_to=period.date_to)

    @staticmethod
    def _currency_response(row: CurrencySalesRow) -> CurrencySalesResponse:
        return CurrencySalesResponse(
            currency=row.currency,
            paid_orders=row.paid_orders,
            gross_revenue_minor=row.gross_revenue_minor,
            failed_payments=row.failed_payments,
            refunded_payments=row.refunded_payments,
            refunded_amount_minor=row.refunded_amount_minor,
            net_revenue_minor=row.gross_revenue_minor - row.refunded_amount_minor,
        )

    @staticmethod
    def _daily_response(row: DailySalesRow) -> DailySalesResponse:
        return DailySalesResponse(
            day=row.day,
            currency=row.currency,
            paid_orders=row.paid_orders,
            gross_revenue_minor=row.gross_revenue_minor,
            failed_payments=row.failed_payments,
            refunded_payments=row.refunded_payments,
            refunded_amount_minor=row.refunded_amount_minor,
            net_revenue_minor=row.gross_revenue_minor - row.refunded_amount_minor,
        )

    @staticmethod
    def _top_product_response(row: TopProductRow) -> TopProductResponse:
        return TopProductResponse(
            product_id=row.product_id,
            product_name=row.product_name,
            product_sku=row.product_sku,
            currency=row.currency,
            paid_quantity=row.paid_quantity,
            gross_revenue_minor=row.gross_revenue_minor,
            paid_orders=row.paid_orders,
        )

    @staticmethod
    def _low_stock_response(row: LowStockRow) -> LowStockResponse:
        return LowStockResponse(
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse_name,
            warehouse_code=row.warehouse_code,
            product_id=row.product_id,
            product_name=row.product_name,
            product_sku=row.product_sku,
            on_hand=row.on_hand,
            reserved=row.reserved,
            available=row.available,
        )
