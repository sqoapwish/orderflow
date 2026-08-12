from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from orderflow.modules.orders.domain import OrderFilters
from orderflow.modules.orders.models import Order, OrderItem


@dataclass(frozen=True, slots=True)
class OrderBundle:
    order: Order
    items: list[OrderItem]


class OrderRepositoryProtocol(Protocol):
    async def acquire_idempotency_lock(self, customer_id: UUID, key: str) -> None: ...

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> OrderBundle | None: ...

    async def get(self, order_id: UUID) -> OrderBundle | None: ...

    async def list_orders(
        self,
        filters: OrderFilters,
    ) -> tuple[list[OrderBundle], int]: ...

    def add_order(self, order: Order) -> None: ...

    def add_item(self, item: OrderItem) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_idempotency_lock(self, customer_id: UUID, key: str) -> None:
        lock_key = f"{customer_id}:{key}"
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 202608120006))"),
            {"lock_key": lock_key},
        )

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> OrderBundle | None:
        statement = select(Order).where(
            Order.customer_id == customer_id,
            Order.idempotency_key == key,
        )
        order = (await self._session.execute(statement)).scalar_one_or_none()
        if order is None:
            return None
        items_by_order = await self._list_items([order.id])
        return OrderBundle(order=order, items=items_by_order[order.id])

    async def get(self, order_id: UUID) -> OrderBundle | None:
        order = await self._session.get(Order, order_id)
        if order is None:
            return None
        items_by_order = await self._list_items([order.id])
        return OrderBundle(order=order, items=items_by_order[order.id])

    async def list_orders(
        self,
        filters: OrderFilters,
    ) -> tuple[list[OrderBundle], int]:
        conditions: list[ColumnElement[bool]] = []
        if filters.customer_id is not None:
            conditions.append(Order.customer_id == filters.customer_id)
        if filters.status is not None:
            conditions.append(Order.status == filters.status)
        total = int(
            (await self._session.scalar(select(func.count()).select_from(Order).where(*conditions)))
            or 0
        )
        statement = (
            select(Order)
            .where(*conditions)
            .order_by(Order.created_at.desc(), Order.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        orders = list((await self._session.execute(statement)).scalars().all())
        items_by_order = await self._list_items([order.id for order in orders])
        return [OrderBundle(order=order, items=items_by_order[order.id]) for order in orders], total

    def add_order(self, order: Order) -> None:
        self._session.add(order)

    def add_item(self, item: OrderItem) -> None:
        self._session.add(item)

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def _list_items(self, order_ids: list[UUID]) -> defaultdict[UUID, list[OrderItem]]:
        grouped: defaultdict[UUID, list[OrderItem]] = defaultdict(list)
        if not order_ids:
            return grouped
        statement = (
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.created_at, OrderItem.id)
        )
        items = list((await self._session.execute(statement)).scalars().all())
        for item in items:
            grouped[item.order_id].append(item)
        return grouped
