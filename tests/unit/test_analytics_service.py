from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from orderflow.modules.analytics.domain import (
    CurrencySalesRow,
    DailySalesRow,
    LowStockRow,
    TopProductRow,
)
from orderflow.modules.analytics.errors import (
    AnalyticsPeriodTooLargeError,
    InvalidAnalyticsPeriodError,
)
from orderflow.modules.analytics.service import AnalyticsService
from tests.fakes import FakeAnalyticsCache, FakeAnalyticsRepository


def build_service() -> tuple[AnalyticsService, FakeAnalyticsRepository, FakeAnalyticsCache]:
    repository = FakeAnalyticsRepository()
    cache = FakeAnalyticsCache()
    service = AnalyticsService(
        repository,
        cache,
        cache_ttl_seconds=30,
        today_provider=lambda: date(2026, 8, 17),
    )
    return service, repository, cache


async def test_sales_reports_net_revenue_and_uses_cache() -> None:
    service, repository, cache = build_service()
    repository.currency_sales = [
        CurrencySalesRow(
            currency="RUB",
            paid_orders=4,
            gross_revenue_minor=50_000,
            failed_payments=2,
            refunded_payments=1,
            refunded_amount_minor=12_000,
        )
    ]
    repository.daily_sales = [
        DailySalesRow(
            day=date(2026, 8, 16),
            currency="RUB",
            paid_orders=4,
            gross_revenue_minor=50_000,
            failed_payments=2,
            refunded_payments=1,
            refunded_amount_minor=12_000,
        )
    ]

    first = await service.sales(date_from=date(2026, 8, 1), date_to=date(2026, 8, 17))
    second = await service.sales(date_from=date(2026, 8, 1), date_to=date(2026, 8, 17))

    assert first == second
    assert first.currencies[0].net_revenue_minor == 38_000
    assert first.daily[0].net_revenue_minor == 38_000
    assert len(repository.sales_periods) == 1
    assert repository.sales_periods[0].starts_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert repository.sales_periods[0].ends_before == datetime(2026, 8, 18, tzinfo=UTC)
    assert cache.set_calls[0][2] == 30


async def test_default_period_is_thirty_days_and_broken_cache_falls_back() -> None:
    service, repository, cache = build_service()
    cache.fail_reads = True
    cache.fail_writes = True

    response = await service.sales(date_from=None, date_to=None)

    assert response.period.date_from == date(2026, 7, 19)
    assert response.period.date_to == date(2026, 8, 17)
    assert len(repository.sales_periods) == 1


async def test_invalid_cached_payload_is_replaced_from_repository() -> None:
    service, repository, cache = build_service()
    cache.values["orderflow:analytics:v1:sales:2026-08-01:2026-08-17"] = "not-json"

    response = await service.sales(date_from=date(2026, 8, 1), date_to=date(2026, 8, 17))

    assert response.currencies == []
    assert len(repository.sales_periods) == 1
    assert len(cache.set_calls) == 1


async def test_period_validation_rejects_inverted_and_oversized_ranges() -> None:
    service, _, _ = build_service()

    with pytest.raises(InvalidAnalyticsPeriodError):
        await service.sales(date_from=date(2026, 8, 18), date_to=date(2026, 8, 17))
    with pytest.raises(AnalyticsPeriodTooLargeError):
        await service.sales(date_from=date(2025, 8, 16), date_to=date(2026, 8, 17))


async def test_top_products_and_low_stock_preserve_filters_and_pagination() -> None:
    service, repository, _ = build_service()
    product_id = uuid4()
    warehouse_id = uuid4()
    repository.top_product_rows = [
        TopProductRow(
            product_id=product_id,
            product_name="Keyboard",
            product_sku="KEY-1",
            currency="RUB",
            paid_quantity=7,
            gross_revenue_minor=70_000,
            paid_orders=4,
        )
    ]
    repository.low_stock_rows = [
        LowStockRow(
            warehouse_id=warehouse_id,
            warehouse_name="Main",
            warehouse_code="MAIN",
            product_id=product_id,
            product_name="Keyboard",
            product_sku="KEY-1",
            on_hand=8,
            reserved=6,
            available=2,
        )
    ]
    repository.low_stock_total = 21

    products = await service.top_products(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 17),
        limit=5,
    )
    stock = await service.low_stock(
        threshold=3,
        warehouse_id=warehouse_id,
        page=2,
        page_size=10,
    )

    assert products.items[0].paid_quantity == 7
    assert repository.top_product_calls[0][1] == 5
    assert stock.items[0].available == 2
    assert stock.total_pages == 3
    assert repository.low_stock_calls == [(3, warehouse_id, 2, 10)]
