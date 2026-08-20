from datetime import date
from uuid import UUID

from pydantic import BaseModel


class AnalyticsPeriodResponse(BaseModel):
    date_from: date
    date_to: date


class CurrencySalesResponse(BaseModel):
    currency: str
    paid_orders: int
    gross_revenue_minor: int
    failed_payments: int
    refunded_payments: int
    refunded_amount_minor: int
    net_revenue_minor: int


class DailySalesResponse(CurrencySalesResponse):
    day: date


class SalesAnalyticsResponse(BaseModel):
    period: AnalyticsPeriodResponse
    currencies: list[CurrencySalesResponse]
    daily: list[DailySalesResponse]


class TopProductResponse(BaseModel):
    product_id: UUID
    product_name: str
    product_sku: str
    currency: str
    paid_quantity: int
    gross_revenue_minor: int
    paid_orders: int


class TopProductsResponse(BaseModel):
    period: AnalyticsPeriodResponse
    items: list[TopProductResponse]


class LowStockResponse(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    warehouse_code: str
    product_id: UUID
    product_name: str
    product_sku: str
    on_hand: int
    reserved: int
    available: int


class LowStockPageResponse(BaseModel):
    items: list[LowStockResponse]
    threshold: int
    total: int
    page: int
    page_size: int
    total_pages: int
