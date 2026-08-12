from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from orderflow.modules.cart.errors import (
    CartCurrencyConflictError,
    CartItemNotFoundError,
    CartLimitExceededError,
    CartWriteConflictError,
)
from orderflow.modules.cart.models import Cart, CartItem
from orderflow.modules.cart.repository import CartBundle, CartRepositoryProtocol
from orderflow.modules.catalog.errors import ProductNotFoundError
from orderflow.modules.catalog.models import Product
from orderflow.modules.catalog.service import ProductDescriptor

MAX_CART_ITEMS = 100
MAX_CART_ITEM_QUANTITY = 100_000


class CartCatalogProtocol(Protocol):
    async def describe_products(
        self,
        product_ids: list[UUID],
    ) -> dict[UUID, ProductDescriptor]: ...

    async def lock_orderable_products(self, product_ids: list[UUID]) -> dict[UUID, Product]: ...


class WarehouseAvailabilityProtocol(Protocol):
    async def require_active_warehouse(self, warehouse_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class CartViewItem:
    item: CartItem
    product: Product
    is_available: bool
    line_total_minor: int


@dataclass(frozen=True, slots=True)
class CartView:
    cart: Cart | None
    items: list[CartViewItem]
    total_minor: int | None
    currency: str | None


class CartService:
    def __init__(
        self,
        repository: CartRepositoryProtocol,
        catalog: CartCatalogProtocol,
        warehouse_availability: WarehouseAvailabilityProtocol,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._warehouse_availability = warehouse_availability

    async def get_cart(self, customer_id: UUID) -> CartView:
        return await self._build_view(await self._repository.get_cart(customer_id))

    async def add_item(
        self,
        *,
        customer_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        quantity: int,
    ) -> CartView:
        await self._repository.acquire_customer_lock(customer_id)
        product = (await self._catalog.lock_orderable_products([product_id]))[product_id]
        await self._warehouse_availability.require_active_warehouse(warehouse_id)
        bundle = await self._repository.get_cart(customer_id, for_update=True)
        cart = bundle.cart
        if cart is None:
            cart = Cart(id=uuid4(), customer_id=customer_id)
            self._repository.add_cart(cart)

        currencies = await self._currencies(bundle.items)
        if currencies and currencies != {product.currency}:
            raise CartCurrencyConflictError

        item = await self._repository.get_item_by_stock(
            cart.id,
            product_id,
            warehouse_id,
            for_update=True,
        )
        if item is None:
            if await self._repository.count_items(cart.id) >= MAX_CART_ITEMS:
                raise CartLimitExceededError
            item = CartItem(
                id=uuid4(),
                cart_id=cart.id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=quantity,
            )
            self._repository.add_item(item)
        else:
            if item.quantity + quantity > MAX_CART_ITEM_QUANTITY:
                raise CartLimitExceededError
            item.quantity += quantity
        await self._repository.touch(cart.id)
        await self._save()
        return await self.get_cart(customer_id)

    async def update_item(
        self,
        *,
        customer_id: UUID,
        item_id: UUID,
        quantity: int,
    ) -> CartView:
        await self._repository.acquire_customer_lock(customer_id)
        item = await self._repository.get_item(customer_id, item_id, for_update=True)
        if item is None:
            raise CartItemNotFoundError
        await self._catalog.lock_orderable_products([item.product_id])
        await self._warehouse_availability.require_active_warehouse(item.warehouse_id)
        item.quantity = quantity
        await self._repository.touch(item.cart_id)
        await self._save()
        return await self.get_cart(customer_id)

    async def remove_item(self, *, customer_id: UUID, item_id: UUID) -> CartView:
        await self._repository.acquire_customer_lock(customer_id)
        item = await self._repository.get_item(customer_id, item_id, for_update=True)
        if item is None:
            raise CartItemNotFoundError
        await self._repository.delete_item(item)
        await self._repository.touch(item.cart_id)
        await self._save()
        return await self.get_cart(customer_id)

    async def clear(self, customer_id: UUID) -> None:
        await self._repository.acquire_customer_lock(customer_id)
        bundle = await self._repository.get_cart(customer_id, for_update=True)
        if bundle.cart is not None:
            await self._repository.clear(bundle.cart.id)
            await self._repository.touch(bundle.cart.id)
        await self._save()

    async def lock_for_checkout(self, customer_id: UUID) -> CartBundle:
        await self._repository.acquire_customer_lock(customer_id)
        return await self._repository.get_cart(customer_id, for_update=True)

    async def clear_locked(self, cart_id: UUID) -> None:
        await self._repository.clear(cart_id)
        await self._repository.touch(cart_id)

    async def _currencies(self, items: list[CartItem]) -> set[str]:
        descriptors = await self._catalog.describe_products([item.product_id for item in items])
        if len(descriptors) != len({item.product_id for item in items}):
            raise ProductNotFoundError
        return {descriptor.product.currency for descriptor in descriptors.values()}

    async def _build_view(self, bundle: CartBundle) -> CartView:
        descriptors = await self._catalog.describe_products(
            [item.product_id for item in bundle.items]
        )
        if len(descriptors) != len({item.product_id for item in bundle.items}):
            raise ProductNotFoundError
        view_items: list[CartViewItem] = []
        for item in bundle.items:
            descriptor = descriptors[item.product_id]
            view_items.append(
                CartViewItem(
                    item=item,
                    product=descriptor.product,
                    is_available=descriptor.is_available,
                    line_total_minor=descriptor.product.price_minor * item.quantity,
                )
            )
        currencies = {item.product.currency for item in view_items}
        total_minor = (
            sum(item.line_total_minor for item in view_items) if len(currencies) <= 1 else None
        )
        return CartView(
            cart=bundle.cart,
            items=view_items,
            total_minor=total_minor,
            currency=next(iter(currencies), None) if len(currencies) <= 1 else None,
        )

    async def _save(self) -> None:
        try:
            await self._repository.flush()
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            raise CartWriteConflictError from None
