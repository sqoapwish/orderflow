from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.cart.models import Cart, CartItem


@dataclass(frozen=True, slots=True)
class CartBundle:
    cart: Cart | None
    items: list[CartItem]


class CartRepositoryProtocol(Protocol):
    async def acquire_customer_lock(self, customer_id: UUID) -> None: ...

    async def get_cart(
        self,
        customer_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartBundle: ...

    async def get_item(
        self,
        customer_id: UUID,
        item_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None: ...

    async def get_item_by_stock(
        self,
        cart_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None: ...

    async def count_items(self, cart_id: UUID) -> int: ...

    def add_cart(self, cart: Cart) -> None: ...

    def add_item(self, item: CartItem) -> None: ...

    async def delete_item(self, item: CartItem) -> None: ...

    async def clear(self, cart_id: UUID) -> None: ...

    async def touch(self, cart_id: UUID) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class CartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_customer_lock(self, customer_id: UUID) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:customer_id, 202608120005))"),
            {"customer_id": str(customer_id)},
        )

    async def get_cart(
        self,
        customer_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartBundle:
        statement = select(Cart).where(Cart.customer_id == customer_id)
        if for_update:
            statement = statement.with_for_update()
        cart = (await self._session.execute(statement)).scalar_one_or_none()
        if cart is None:
            return CartBundle(cart=None, items=[])
        items_statement = (
            select(CartItem)
            .where(CartItem.cart_id == cart.id)
            .order_by(CartItem.created_at, CartItem.id)
        )
        if for_update:
            items_statement = items_statement.with_for_update()
        items = list((await self._session.execute(items_statement)).scalars().all())
        return CartBundle(cart=cart, items=items)

    async def get_item(
        self,
        customer_id: UUID,
        item_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None:
        statement = (
            select(CartItem)
            .join(Cart, Cart.id == CartItem.cart_id)
            .where(Cart.customer_id == customer_id, CartItem.id == item_id)
        )
        if for_update:
            statement = statement.with_for_update(of=CartItem)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_item_by_stock(
        self,
        cart_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None:
        statement = select(CartItem).where(
            CartItem.cart_id == cart_id,
            CartItem.product_id == product_id,
            CartItem.warehouse_id == warehouse_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def count_items(self, cart_id: UUID) -> int:
        return int(
            (await self._session.scalar(select(func.count()).where(CartItem.cart_id == cart_id)))
            or 0
        )

    def add_cart(self, cart: Cart) -> None:
        self._session.add(cart)

    def add_item(self, item: CartItem) -> None:
        self._session.add(item)

    async def delete_item(self, item: CartItem) -> None:
        await self._session.delete(item)

    async def clear(self, cart_id: UUID) -> None:
        await self._session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))

    async def touch(self, cart_id: UUID) -> None:
        await self._session.execute(
            update(Cart).where(Cart.id == cart_id).values(updated_at=func.now())
        )

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
