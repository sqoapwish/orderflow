from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from argon2 import PasswordHasher

from orderflow.core.config import Settings
from orderflow.modules.auth.models import RefreshSession, User
from orderflow.modules.auth.security import PasswordService, TokenService
from orderflow.modules.auth.service import AuthService
from orderflow.modules.cart.models import Cart, CartItem
from orderflow.modules.cart.repository import CartBundle
from orderflow.modules.catalog.domain import ProductFilters, ProductSortField, SortDirection
from orderflow.modules.catalog.errors import ProductNotFoundError
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.domain import MovementFilters, ReservationStatus, StockFilters
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)
from orderflow.modules.inventory.repository import StockKey
from orderflow.modules.inventory.service import InventoryService
from orderflow.modules.orders.domain import OrderFilters
from orderflow.modules.orders.models import Order, OrderItem
from orderflow.modules.orders.repository import OrderBundle
from orderflow.modules.outbox.domain import OutboxStatus
from orderflow.modules.outbox.models import InboxEvent, OutboxEvent
from orderflow.modules.payments.domain import PaymentFilters
from orderflow.modules.payments.models import Payment, PaymentRefund, PaymentWebhookEvent
from orderflow.modules.payments.repository import PaymentBundle


class FakeAuthRepository:
    def __init__(self) -> None:
        self.users_by_email: dict[str, User] = {}
        self.users_by_id: dict[UUID, User] = {}
        self.sessions: dict[UUID, RefreshSession] = {}
        self.commits = 0
        self.rollbacks = 0

    async def get_user_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.users_by_id.get(user_id)

    async def get_refresh_session(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None:
        return self.sessions.get(session_id)

    def add_user(self, user: User) -> None:
        now = datetime.now(UTC)
        user.id = uuid4()
        user.is_active = True
        user.created_at = now
        user.updated_at = now
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user

    def add_refresh_session(self, session: RefreshSession) -> None:
        self.sessions[session.id] = session

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_auth_service(
    settings: Settings,
) -> tuple[AuthService, FakeAuthRepository, PasswordService, TokenService]:
    repository = FakeAuthRepository()
    password_service = PasswordService(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    token_service = TokenService(settings)
    service = AuthService(repository, password_service, token_service)
    return service, repository, password_service, token_service


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.categories: dict[UUID, Category] = {}
        self.products: dict[UUID, Product] = {}
        self.commits = 0
        self.rollbacks = 0
        self.catalog_write_locks = 0

    async def acquire_catalog_write_lock(self) -> None:
        self.catalog_write_locks += 1

    async def list_public_categories(self) -> list[Category]:
        return sorted(
            (category for category in self.categories.values() if category.is_active),
            key=lambda category: category.name,
        )

    async def get_category(self, category_id: UUID) -> Category | None:
        return self.categories.get(category_id)

    async def get_public_category_by_slug(self, slug: str) -> Category | None:
        return next(
            (
                category
                for category in self.categories.values()
                if category.slug == slug and category.is_active
            ),
            None,
        )

    async def category_slug_exists(
        self,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            category.slug == slug and category.id != exclude_id
            for category in self.categories.values()
        )

    async def is_category_descendant(self, category_id: UUID, candidate_id: UUID) -> bool:
        current = self.categories.get(candidate_id)
        seen: set[UUID] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.parent_id == category_id:
                return True
            current = self.categories.get(current.parent_id) if current.parent_id else None
        return False

    async def category_has_active_dependencies(self, category_id: UUID) -> bool:
        return any(
            category.parent_id == category_id and category.is_active
            for category in self.categories.values()
        ) or any(
            product.category_id == category_id and product.is_active
            for product in self.products.values()
        )

    def add_category(self, category: Category) -> None:
        now = datetime.now(UTC)
        category.id = uuid4()
        category.created_at = now
        category.updated_at = now
        self.categories[category.id] = category

    async def get_product(self, product_id: UUID) -> Product | None:
        return self.products.get(product_id)

    async def get_products_with_category_state(
        self,
        product_ids: Iterable[UUID],
    ) -> list[tuple[Product, bool]]:
        return [
            (
                self.products[product_id],
                self.categories[self.products[product_id].category_id].is_active,
            )
            for product_id in sorted(set(product_ids), key=lambda value: value.int)
            if product_id in self.products
        ]

    async def get_public_product_by_slug(self, slug: str) -> Product | None:
        return next(
            (
                product
                for product in self.products.values()
                if product.slug == slug
                and product.is_active
                and self.categories[product.category_id].is_active
            ),
            None,
        )

    async def list_public_products(
        self,
        filters: ProductFilters,
    ) -> tuple[list[Product], int]:
        products = [
            product
            for product in self.products.values()
            if product.is_active and self.categories[product.category_id].is_active
        ]
        if filters.search:
            search = filters.search.casefold()
            products = [
                product
                for product in products
                if search in product.name.casefold() or search in product.sku.casefold()
            ]
        if filters.category_id is not None:
            products = [
                product for product in products if product.category_id == filters.category_id
            ]
        if filters.min_price_minor is not None:
            products = [
                product for product in products if product.price_minor >= filters.min_price_minor
            ]
        if filters.max_price_minor is not None:
            products = [
                product for product in products if product.price_minor <= filters.max_price_minor
            ]

        sort_key = {
            ProductSortField.CREATED_AT: lambda product: product.created_at,
            ProductSortField.NAME: lambda product: product.name,
            ProductSortField.PRICE: lambda product: product.price_minor,
        }[filters.sort_by]
        products.sort(key=lambda product: product.id)
        products.sort(
            key=sort_key,
            reverse=filters.sort_direction is SortDirection.DESC,
        )
        total = len(products)
        start = (filters.page - 1) * filters.page_size
        return products[start : start + filters.page_size], total

    async def product_slug_exists(
        self,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            product.slug == slug and product.id != exclude_id for product in self.products.values()
        )

    async def product_sku_exists(
        self,
        sku: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            product.sku == sku and product.id != exclude_id for product in self.products.values()
        )

    def add_product(self, product: Product) -> None:
        now = datetime.now(UTC)
        product.id = uuid4()
        product.created_at = now
        product.updated_at = now
        self.products[product.id] = product

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_catalog_service() -> tuple[CatalogService, FakeCatalogRepository]:
    repository = FakeCatalogRepository()
    return CatalogService(repository), repository


class FakeProductAvailability:
    def __init__(self) -> None:
        self.product_ids: set[UUID] = set()
        self.active_product_ids: set[UUID] = set()

    async def require_active_product_for_inventory(self, product_id: UUID) -> None:
        if product_id not in self.active_product_ids:
            raise ProductNotFoundError

    async def require_product_for_inventory(self, product_id: UUID) -> None:
        if product_id not in self.product_ids:
            raise ProductNotFoundError


class FakeInventoryRepository:
    def __init__(self) -> None:
        self.warehouses: dict[UUID, Warehouse] = {}
        self.balances: dict[StockKey, StockBalance] = {}
        self.movements: list[InventoryMovement] = []
        self.reservations: dict[UUID, InventoryReservation] = {}
        self.reservations_by_key: dict[str, InventoryReservation] = {}
        self.reservation_key_locks: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def list_warehouses(self) -> list[Warehouse]:
        return sorted(
            self.warehouses.values(), key=lambda warehouse: (warehouse.name, warehouse.id)
        )

    async def lock_warehouses(self, warehouse_ids: Iterable[UUID]) -> list[Warehouse]:
        ids = sorted(set(warehouse_ids), key=lambda warehouse_id: warehouse_id.int)
        return [
            self.warehouses[warehouse_id] for warehouse_id in ids if warehouse_id in self.warehouses
        ]

    async def warehouse_code_exists(
        self,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            warehouse.code == code and warehouse.id != exclude_id
            for warehouse in self.warehouses.values()
        )

    async def warehouse_has_inventory(self, warehouse_id: UUID) -> bool:
        return any(
            balance.warehouse_id == warehouse_id and (balance.on_hand != 0 or balance.reserved != 0)
            for balance in self.balances.values()
        ) or any(
            reservation.warehouse_id == warehouse_id
            and reservation.status == ReservationStatus.ACTIVE
            for reservation in self.reservations.values()
        )

    def add_warehouse(self, warehouse: Warehouse) -> None:
        now = datetime.now(UTC)
        warehouse.id = uuid4()
        warehouse.created_at = now
        warehouse.updated_at = now
        self.warehouses[warehouse.id] = warehouse

    async def lock_stock_balances(
        self,
        keys: Iterable[StockKey],
    ) -> dict[StockKey, StockBalance]:
        now = datetime.now(UTC)
        ordered_keys = sorted(set(keys), key=lambda key: (key[0].int, key[1].int))
        for key in ordered_keys:
            if key not in self.balances:
                balance = StockBalance(
                    id=uuid4(),
                    warehouse_id=key[0],
                    product_id=key[1],
                    on_hand=0,
                    reserved=0,
                    created_at=now,
                    updated_at=now,
                )
                self.balances[key] = balance
        return {key: self.balances[key] for key in ordered_keys}

    async def list_stock_balances(
        self,
        filters: StockFilters,
    ) -> tuple[list[StockBalance], int]:
        balances = list(self.balances.values())
        if filters.warehouse_id is not None:
            balances = [
                balance for balance in balances if balance.warehouse_id == filters.warehouse_id
            ]
        if filters.product_id is not None:
            balances = [balance for balance in balances if balance.product_id == filters.product_id]
        balances.sort(key=lambda balance: (balance.warehouse_id, balance.product_id))
        total = len(balances)
        start = (filters.page - 1) * filters.page_size
        return balances[start : start + filters.page_size], total

    def add_movement(self, movement: InventoryMovement) -> None:
        movement.created_at = datetime.now(UTC)
        self.movements.append(movement)

    async def list_movements(
        self,
        filters: MovementFilters,
    ) -> tuple[list[InventoryMovement], int]:
        movements = list(self.movements)
        if filters.warehouse_id is not None:
            movements = [
                movement for movement in movements if movement.warehouse_id == filters.warehouse_id
            ]
        if filters.product_id is not None:
            movements = [
                movement for movement in movements if movement.product_id == filters.product_id
            ]
        if filters.movement_type is not None:
            movements = [
                movement
                for movement in movements
                if movement.movement_type == filters.movement_type
            ]
        if filters.operation_id is not None:
            movements = [
                movement for movement in movements if movement.operation_id == filters.operation_id
            ]
        movements.sort(key=lambda movement: (movement.created_at, movement.id), reverse=True)
        total = len(movements)
        start = (filters.page - 1) * filters.page_size
        return movements[start : start + filters.page_size], total

    async def acquire_reservation_key_lock(self, reservation_key: str) -> None:
        self.reservation_key_locks.append(reservation_key)

    async def get_reservation_by_key(
        self,
        reservation_key: str,
    ) -> InventoryReservation | None:
        return self.reservations_by_key.get(reservation_key)

    async def get_reservation(
        self,
        reservation_id: UUID,
        *,
        for_update: bool = False,
    ) -> InventoryReservation | None:
        return self.reservations.get(reservation_id)

    def add_reservation(self, reservation: InventoryReservation) -> None:
        now = datetime.now(UTC)
        reservation.created_at = now
        reservation.updated_at = now
        self.reservations[reservation.id] = reservation
        self.reservations_by_key[reservation.reservation_key] = reservation

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_inventory_service(
    *product_ids: UUID,
) -> tuple[InventoryService, FakeInventoryRepository, FakeProductAvailability]:
    repository = FakeInventoryRepository()
    product_availability = FakeProductAvailability()
    product_availability.product_ids.update(product_ids)
    product_availability.active_product_ids.update(product_ids)
    return (
        InventoryService(repository, product_availability),
        repository,
        product_availability,
    )


class FakeCartRepository:
    def __init__(self) -> None:
        self.carts_by_customer: dict[UUID, Cart] = {}
        self.items: dict[UUID, CartItem] = {}
        self.customer_locks: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0

    async def acquire_customer_lock(self, customer_id: UUID) -> None:
        self.customer_locks.append(customer_id)

    async def get_cart(
        self,
        customer_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartBundle:
        cart = self.carts_by_customer.get(customer_id)
        if cart is None:
            return CartBundle(cart=None, items=[])
        items = sorted(
            (item for item in self.items.values() if item.cart_id == cart.id),
            key=lambda item: (item.created_at, item.id),
        )
        return CartBundle(cart=cart, items=items)

    async def get_item(
        self,
        customer_id: UUID,
        item_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None:
        cart = self.carts_by_customer.get(customer_id)
        item = self.items.get(item_id)
        if cart is None or item is None or item.cart_id != cart.id:
            return None
        return item

    async def get_item_by_stock(
        self,
        cart_id: UUID,
        product_id: UUID,
        warehouse_id: UUID,
        *,
        for_update: bool = False,
    ) -> CartItem | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.cart_id == cart_id
                and item.product_id == product_id
                and item.warehouse_id == warehouse_id
            ),
            None,
        )

    async def count_items(self, cart_id: UUID) -> int:
        return sum(item.cart_id == cart_id for item in self.items.values())

    def add_cart(self, cart: Cart) -> None:
        now = datetime.now(UTC)
        cart.created_at = now
        cart.updated_at = now
        self.carts_by_customer[cart.customer_id] = cart

    def add_item(self, item: CartItem) -> None:
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        self.items[item.id] = item

    async def delete_item(self, item: CartItem) -> None:
        self.items.pop(item.id, None)

    async def clear(self, cart_id: UUID) -> None:
        self.items = {
            item_id: item for item_id, item in self.items.items() if item.cart_id != cart_id
        }

    async def touch(self, cart_id: UUID) -> None:
        for cart in self.carts_by_customer.values():
            if cart.id == cart_id:
                cart.updated_at = datetime.now(UTC)
                return

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeOrderRepository:
    def __init__(self) -> None:
        self.orders: dict[UUID, Order] = {}
        self.items: dict[UUID, OrderItem] = {}
        self.idempotency_locks: list[tuple[UUID, str]] = []
        self.commits = 0
        self.rollbacks = 0

    async def acquire_idempotency_lock(self, customer_id: UUID, key: str) -> None:
        self.idempotency_locks.append((customer_id, key))

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> OrderBundle | None:
        order = next(
            (
                order
                for order in self.orders.values()
                if order.customer_id == customer_id and order.idempotency_key == key
            ),
            None,
        )
        return self._bundle(order) if order else None

    async def get(
        self,
        order_id: UUID,
        *,
        for_update: bool = False,
    ) -> OrderBundle | None:
        order = self.orders.get(order_id)
        return self._bundle(order) if order else None

    async def list_orders(
        self,
        filters: OrderFilters,
    ) -> tuple[list[OrderBundle], int]:
        orders = list(self.orders.values())
        if filters.customer_id is not None:
            orders = [order for order in orders if order.customer_id == filters.customer_id]
        if filters.status is not None:
            orders = [order for order in orders if order.status == filters.status]
        orders.sort(key=lambda order: (order.created_at, order.id), reverse=True)
        total = len(orders)
        start = (filters.page - 1) * filters.page_size
        return [self._bundle(order) for order in orders[start : start + filters.page_size]], total

    def add_order(self, order: Order) -> None:
        now = datetime.now(UTC)
        order.created_at = now
        order.updated_at = now
        self.orders[order.id] = order

    def add_item(self, item: OrderItem) -> None:
        item.created_at = datetime.now(UTC)
        self.items[item.id] = item

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def _bundle(self, order: Order) -> OrderBundle:
        items = sorted(
            (item for item in self.items.values() if item.order_id == order.id),
            key=lambda item: (item.created_at, item.id),
        )
        return OrderBundle(order=order, items=items)


class FakePaymentRepository:
    def __init__(self) -> None:
        self.payments: dict[UUID, Payment] = {}
        self.events: dict[str, PaymentWebhookEvent] = {}
        self.refunds: dict[UUID, PaymentRefund] = {}
        self.session_locks: list[tuple[UUID, str]] = []
        self.event_locks: list[str] = []
        self.refund_locks: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0

    async def acquire_session_lock(self, customer_id: UUID, key: str) -> None:
        self.session_locks.append((customer_id, key))

    async def acquire_event_lock(self, provider_event_id: str) -> None:
        self.event_locks.append(provider_event_id)

    async def acquire_refund_lock(self, payment_id: UUID) -> None:
        self.refund_locks.append(payment_id)

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> PaymentBundle | None:
        payment = next(
            (
                payment
                for payment in self.payments.values()
                if payment.customer_id == customer_id and payment.idempotency_key == key
            ),
            None,
        )
        return self._bundle(payment) if payment else None

    async def get_by_order(
        self,
        order_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        payment = next(
            (payment for payment in self.payments.values() if payment.order_id == order_id),
            None,
        )
        return self._bundle(payment) if payment else None

    async def get(
        self,
        payment_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        payment = self.payments.get(payment_id)
        return self._bundle(payment) if payment else None

    async def get_by_provider_id(
        self,
        provider_payment_id: str,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        payment = next(
            (
                payment
                for payment in self.payments.values()
                if payment.provider_payment_id == provider_payment_id
            ),
            None,
        )
        return self._bundle(payment) if payment else None

    async def list_payments(
        self,
        filters: PaymentFilters,
    ) -> tuple[list[PaymentBundle], int]:
        payments = list(self.payments.values())
        if filters.customer_id is not None:
            payments = [
                payment for payment in payments if payment.customer_id == filters.customer_id
            ]
        if filters.status is not None:
            payments = [payment for payment in payments if payment.status == filters.status]
        payments.sort(key=lambda payment: (payment.created_at, payment.id), reverse=True)
        total = len(payments)
        start = (filters.page - 1) * filters.page_size
        return [
            self._bundle(payment) for payment in payments[start : start + filters.page_size]
        ], total

    async def get_event(self, provider_event_id: str) -> PaymentWebhookEvent | None:
        return self.events.get(provider_event_id)

    async def get_refund_by_payment(self, payment_id: UUID) -> PaymentRefund | None:
        return self.refunds.get(payment_id)

    def add_payment(self, payment: Payment) -> None:
        now = datetime.now(UTC)
        payment.created_at = now
        payment.updated_at = now
        self.payments[payment.id] = payment

    def add_event(self, event: PaymentWebhookEvent) -> None:
        event.created_at = datetime.now(UTC)
        self.events[event.provider_event_id] = event

    def add_refund(self, refund: PaymentRefund) -> None:
        refund.created_at = datetime.now(UTC)
        self.refunds[refund.payment_id] = refund

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def _bundle(self, payment: Payment) -> PaymentBundle:
        return PaymentBundle(payment=payment, refund=self.refunds.get(payment.id))


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, event: OutboxEvent) -> None:
        self.events.append(event)

    async def claim_pending(self, *, now: datetime, limit: int) -> list[OutboxEvent]:
        pending = [
            event
            for event in self.events
            if event.status is OutboxStatus.PENDING and event.available_at <= now
        ]
        pending.sort(key=lambda event: (event.available_at, event.created_at, event.id))
        return pending[:limit]

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeInboxRepository:
    def __init__(self) -> None:
        self.events: dict[UUID, InboxEvent] = {}
        self.commits = 0
        self.rollbacks = 0

    async def try_add(self, event: InboxEvent) -> bool:
        if event.event_id in self.events:
            return False
        self.events[event.event_id] = event
        return True

    async def get(self, event_id: UUID) -> InboxEvent | None:
        return self.events.get(event_id)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1
