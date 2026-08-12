from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from orderflow.modules.orders.domain import OrderStatus
from orderflow.modules.orders.repository import OrderBundle


class OrderItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    reservation_id: UUID
    product_name: str
    product_sku: str
    unit_price_minor: int
    quantity: int
    line_total_minor: int
    currency: str
    created_at: datetime


class OrderResponse(BaseModel):
    id: UUID
    order_number: str
    customer_id: UUID
    status: OrderStatus
    total_minor: int
    currency: str
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_bundle(cls, bundle: OrderBundle) -> "OrderResponse":
        order = bundle.order
        return cls(
            id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            status=order.status,
            total_minor=order.total_minor,
            currency=order.currency,
            items=[
                OrderItemResponse(
                    id=item.id,
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    reservation_id=item.reservation_id,
                    product_name=item.product_name,
                    product_sku=item.product_sku,
                    unit_price_minor=item.unit_price_minor,
                    quantity=item.quantity,
                    line_total_minor=item.line_total_minor,
                    currency=item.currency,
                    created_at=item.created_at,
                )
                for item in bundle.items
            ],
            created_at=order.created_at,
            updated_at=order.updated_at,
        )


class OrderPageResponse(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
