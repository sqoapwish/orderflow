from dataclasses import dataclass
from math import ceil
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from orderflow.modules.auth.domain import UserRole
from orderflow.modules.cart.errors import CartCurrencyConflictError, EmptyCartError
from orderflow.modules.cart.repository import CartBundle
from orderflow.modules.catalog.models import Product
from orderflow.modules.inventory.models import InventoryReservation
from orderflow.modules.orders.domain import OrderFilters, OrderStatus
from orderflow.modules.orders.errors import (
    InvalidIdempotencyKeyError,
    OrderNotFoundError,
    OrderTotalOverflowError,
    OrderWriteConflictError,
)
from orderflow.modules.orders.models import Order, OrderItem
from orderflow.modules.orders.repository import OrderBundle, OrderRepositoryProtocol
from orderflow.modules.outbox.domain import OutboxEventType
from orderflow.modules.outbox.repository import OutboxWriterProtocol
from orderflow.modules.outbox.service import build_outbox_event

MAX_BIGINT = 9_223_372_036_854_775_807


class CheckoutCartProtocol(Protocol):
    async def lock_for_checkout(self, customer_id: UUID) -> CartBundle: ...

    async def clear_locked(self, cart_id: UUID) -> None: ...


class CheckoutCatalogProtocol(Protocol):
    async def lock_orderable_products(self, product_ids: list[UUID]) -> dict[UUID, Product]: ...


class CheckoutInventoryProtocol(Protocol):
    async def reserve_stock(
        self,
        *,
        reservation_key: str,
        warehouse_id: UUID,
        product_id: UUID,
        quantity: int,
        actor_id: UUID,
        commit: bool = True,
    ) -> InventoryReservation: ...


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    bundle: OrderBundle
    created: bool


@dataclass(frozen=True, slots=True)
class OrderPage:
    items: list[OrderBundle]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderService:
    def __init__(
        self,
        repository: OrderRepositoryProtocol,
        cart: CheckoutCartProtocol,
        catalog: CheckoutCatalogProtocol,
        inventory: CheckoutInventoryProtocol,
        outbox: OutboxWriterProtocol,
    ) -> None:
        self._repository = repository
        self._cart = cart
        self._catalog = catalog
        self._inventory = inventory
        self._outbox = outbox

    async def checkout(self, *, customer_id: UUID, idempotency_key: str) -> CheckoutResult:
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise InvalidIdempotencyKeyError

        try:
            cart_bundle = await self._cart.lock_for_checkout(customer_id)
            await self._repository.acquire_idempotency_lock(customer_id, key)
            existing = await self._repository.get_by_idempotency_key(customer_id, key)
            if existing is not None:
                await self._repository.commit()
                return CheckoutResult(bundle=existing, created=False)
            if cart_bundle.cart is None or not cart_bundle.items:
                raise EmptyCartError

            ordered_cart_items = sorted(
                cart_bundle.items,
                key=lambda item: (item.warehouse_id.int, item.product_id.int, item.id.int),
            )
            products = await self._catalog.lock_orderable_products(
                [item.product_id for item in ordered_cart_items]
            )
            currencies = {product.currency for product in products.values()}
            if len(currencies) != 1:
                raise CartCurrencyConflictError
            currency = currencies.pop()
            total_minor = sum(
                products[item.product_id].price_minor * item.quantity for item in ordered_cart_items
            )
            if total_minor > MAX_BIGINT:
                raise OrderTotalOverflowError

            order_id = uuid4()
            order = Order(
                id=order_id,
                order_number=f"OF-{order_id.hex.upper()}",
                customer_id=customer_id,
                idempotency_key=key,
                status=OrderStatus.PENDING_PAYMENT,
                total_minor=total_minor,
                currency=currency,
            )
            self._repository.add_order(order)
            order_items: list[OrderItem] = []
            for cart_item in ordered_cart_items:
                product = products[cart_item.product_id]
                reservation = await self._inventory.reserve_stock(
                    reservation_key=f"order:{order.id}:item:{cart_item.id}",
                    warehouse_id=cart_item.warehouse_id,
                    product_id=cart_item.product_id,
                    quantity=cart_item.quantity,
                    actor_id=customer_id,
                    commit=False,
                )
                item = OrderItem(
                    id=uuid4(),
                    order_id=order.id,
                    product_id=product.id,
                    warehouse_id=cart_item.warehouse_id,
                    reservation_id=reservation.id,
                    product_name=product.name,
                    product_sku=product.sku,
                    unit_price_minor=product.price_minor,
                    quantity=cart_item.quantity,
                    line_total_minor=product.price_minor * cart_item.quantity,
                    currency=product.currency,
                )
                self._repository.add_item(item)
                order_items.append(item)

            await self._cart.clear_locked(cart_bundle.cart.id)
            self._outbox.add(
                build_outbox_event(
                    event_type=OutboxEventType.ORDER_CREATED,
                    aggregate_type="order",
                    aggregate_id=order.id,
                    deduplication_key=f"order:{order.id}:created",
                    payload={
                        "order_id": str(order.id),
                        "order_number": order.order_number,
                        "customer_id": str(order.customer_id),
                        "status": order.status.value,
                        "total_minor": order.total_minor,
                        "currency": order.currency,
                        "item_count": len(order_items),
                    },
                )
            )
            await self._repository.flush()
            await self._repository.commit()
            return CheckoutResult(
                bundle=OrderBundle(order=order, items=order_items),
                created=True,
            )
        except IntegrityError:
            await self._repository.rollback()
            raise OrderWriteConflictError from None
        except Exception:
            await self._repository.rollback()
            raise

    async def list_orders(
        self,
        filters: OrderFilters,
        *,
        requester_id: UUID,
        requester_role: UserRole,
    ) -> OrderPage:
        effective_filters = filters
        if requester_role is UserRole.CUSTOMER:
            effective_filters = OrderFilters(
                page=filters.page,
                page_size=filters.page_size,
                customer_id=requester_id,
                status=filters.status,
            )
        items, total = await self._repository.list_orders(effective_filters)
        return OrderPage(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def get_order(
        self,
        order_id: UUID,
        *,
        requester_id: UUID,
        requester_role: UserRole,
    ) -> OrderBundle:
        bundle = await self._repository.get(order_id)
        if bundle is None or (
            requester_role is UserRole.CUSTOMER and bundle.order.customer_id != requester_id
        ):
            raise OrderNotFoundError
        return bundle
