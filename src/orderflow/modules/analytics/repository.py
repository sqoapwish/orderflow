from datetime import date
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import BigInteger, Date, case, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.analytics.domain import (
    AnalyticsPeriod,
    CurrencySalesRow,
    DailySalesRow,
    LowStockRow,
    TopProductRow,
)
from orderflow.modules.catalog.models import Product
from orderflow.modules.inventory.models import StockBalance, Warehouse
from orderflow.modules.orders.models import OrderItem
from orderflow.modules.outbox.domain import OutboxEventType
from orderflow.modules.outbox.models import OutboxEvent
from orderflow.modules.payments.models import Payment


class AnalyticsRepositoryProtocol(Protocol):
    async def sales_summary(
        self,
        period: AnalyticsPeriod,
    ) -> tuple[list[CurrencySalesRow], list[DailySalesRow]]: ...

    async def top_products(
        self,
        period: AnalyticsPeriod,
        *,
        limit: int,
    ) -> list[TopProductRow]: ...

    async def low_stock(
        self,
        *,
        threshold: int,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[LowStockRow], int]: ...


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sales_summary(
        self,
        period: AnalyticsPeriod,
    ) -> tuple[list[CurrencySalesRow], list[DailySalesRow]]:
        currency = OutboxEvent.payload["currency"].astext.label("currency")
        amount = sql_cast(OutboxEvent.payload["amount_minor"].astext, BigInteger)
        day = sql_cast(func.timezone("UTC", OutboxEvent.created_at), Date).label("day")
        relevant_events = (
            OutboxEventType.PAYMENT_SUCCEEDED,
            OutboxEventType.PAYMENT_FAILED,
            OutboxEventType.PAYMENT_REFUNDED,
        )
        conditions = (
            OutboxEvent.event_type.in_(relevant_events),
            OutboxEvent.created_at >= period.starts_at,
            OutboxEvent.created_at < period.ends_before,
        )
        paid_orders = func.count(
            case((OutboxEvent.event_type == OutboxEventType.PAYMENT_SUCCEEDED, 1))
        )
        gross_revenue = func.coalesce(
            func.sum(
                case(
                    (OutboxEvent.event_type == OutboxEventType.PAYMENT_SUCCEEDED, amount),
                    else_=0,
                )
            ),
            0,
        )
        failed_payments = func.count(
            case((OutboxEvent.event_type == OutboxEventType.PAYMENT_FAILED, 1))
        )
        refunded_payments = func.count(
            case((OutboxEvent.event_type == OutboxEventType.PAYMENT_REFUNDED, 1))
        )
        refunded_amount = func.coalesce(
            func.sum(
                case(
                    (OutboxEvent.event_type == OutboxEventType.PAYMENT_REFUNDED, amount),
                    else_=0,
                )
            ),
            0,
        )
        aggregate_columns = (
            paid_orders.label("paid_orders"),
            gross_revenue.label("gross_revenue_minor"),
            failed_payments.label("failed_payments"),
            refunded_payments.label("refunded_payments"),
            refunded_amount.label("refunded_amount_minor"),
        )
        summary_rows = (
            await self._session.execute(
                select(currency, *aggregate_columns)
                .where(*conditions)
                .group_by(currency)
                .order_by(currency)
            )
        ).all()
        daily_rows = (
            await self._session.execute(
                select(day, currency, *aggregate_columns)
                .where(*conditions)
                .group_by(day, currency)
                .order_by(day, currency)
            )
        ).all()
        return (
            [
                CurrencySalesRow(
                    currency=str(row.currency),
                    paid_orders=int(row.paid_orders),
                    gross_revenue_minor=int(row.gross_revenue_minor),
                    failed_payments=int(row.failed_payments),
                    refunded_payments=int(row.refunded_payments),
                    refunded_amount_minor=int(row.refunded_amount_minor),
                )
                for row in summary_rows
            ],
            [
                DailySalesRow(
                    day=cast(date, row.day),
                    currency=str(row.currency),
                    paid_orders=int(row.paid_orders),
                    gross_revenue_minor=int(row.gross_revenue_minor),
                    failed_payments=int(row.failed_payments),
                    refunded_payments=int(row.refunded_payments),
                    refunded_amount_minor=int(row.refunded_amount_minor),
                )
                for row in daily_rows
            ],
        )

    async def top_products(
        self,
        period: AnalyticsPeriod,
        *,
        limit: int,
    ) -> list[TopProductRow]:
        statement = (
            select(
                OrderItem.product_id,
                OrderItem.product_name,
                OrderItem.product_sku,
                OrderItem.currency,
                func.sum(OrderItem.quantity).label("paid_quantity"),
                func.sum(OrderItem.line_total_minor).label("gross_revenue_minor"),
                func.count(func.distinct(OrderItem.order_id)).label("paid_orders"),
            )
            .join(Payment, Payment.order_id == OrderItem.order_id)
            .join(OutboxEvent, OutboxEvent.aggregate_id == Payment.id)
            .where(
                OutboxEvent.event_type == OutboxEventType.PAYMENT_SUCCEEDED,
                OutboxEvent.aggregate_type == "payment",
                OutboxEvent.created_at >= period.starts_at,
                OutboxEvent.created_at < period.ends_before,
            )
            .group_by(
                OrderItem.product_id,
                OrderItem.product_name,
                OrderItem.product_sku,
                OrderItem.currency,
            )
            .order_by(
                func.sum(OrderItem.quantity).desc(),
                func.sum(OrderItem.line_total_minor).desc(),
                OrderItem.product_id,
            )
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            TopProductRow(
                product_id=cast(UUID, row.product_id),
                product_name=str(row.product_name),
                product_sku=str(row.product_sku),
                currency=str(row.currency),
                paid_quantity=int(row.paid_quantity),
                gross_revenue_minor=int(row.gross_revenue_minor),
                paid_orders=int(row.paid_orders),
            )
            for row in rows
        ]

    async def low_stock(
        self,
        *,
        threshold: int,
        warehouse_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[LowStockRow], int]:
        available = (StockBalance.on_hand - StockBalance.reserved).label("available")
        conditions = [
            Warehouse.is_active.is_(True),
            Product.is_active.is_(True),
            available <= threshold,
        ]
        if warehouse_id is not None:
            conditions.append(StockBalance.warehouse_id == warehouse_id)
        total_statement = (
            select(func.count())
            .select_from(StockBalance)
            .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
            .join(Product, Product.id == StockBalance.product_id)
            .where(*conditions)
        )
        total = int((await self._session.scalar(total_statement)) or 0)
        statement = (
            select(
                StockBalance.warehouse_id,
                Warehouse.name.label("warehouse_name"),
                Warehouse.code.label("warehouse_code"),
                StockBalance.product_id,
                Product.name.label("product_name"),
                Product.sku.label("product_sku"),
                StockBalance.on_hand,
                StockBalance.reserved,
                available,
            )
            .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
            .join(Product, Product.id == StockBalance.product_id)
            .where(*conditions)
            .order_by(
                available,
                Product.sku,
                Warehouse.code,
                StockBalance.product_id,
                StockBalance.warehouse_id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            LowStockRow(
                warehouse_id=cast(UUID, row.warehouse_id),
                warehouse_name=str(row.warehouse_name),
                warehouse_code=str(row.warehouse_code),
                product_id=cast(UUID, row.product_id),
                product_name=str(row.product_name),
                product_sku=str(row.product_sku),
                on_hand=int(row.on_hand),
                reserved=int(row.reserved),
                available=int(row.available),
            )
            for row in rows
        ], total
