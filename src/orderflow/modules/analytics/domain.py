from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalyticsPeriod:
    date_from: date
    date_to: date
    starts_at: datetime
    ends_before: datetime


@dataclass(frozen=True, slots=True)
class CurrencySalesRow:
    currency: str
    paid_orders: int
    gross_revenue_minor: int
    failed_payments: int
    refunded_payments: int
    refunded_amount_minor: int


@dataclass(frozen=True, slots=True)
class DailySalesRow:
    day: date
    currency: str
    paid_orders: int
    gross_revenue_minor: int
    failed_payments: int
    refunded_payments: int
    refunded_amount_minor: int


@dataclass(frozen=True, slots=True)
class TopProductRow:
    product_id: UUID
    product_name: str
    product_sku: str
    currency: str
    paid_quantity: int
    gross_revenue_minor: int
    paid_orders: int


@dataclass(frozen=True, slots=True)
class LowStockRow:
    warehouse_id: UUID
    warehouse_name: str
    warehouse_code: str
    product_id: UUID
    product_name: str
    product_sku: str
    on_hand: int
    reserved: int
    available: int
