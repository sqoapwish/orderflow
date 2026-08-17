from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from orderflow.modules.auth.domain import UserRole
from orderflow.modules.cart.service import CartService
from orderflow.modules.catalog.models import Product
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.errors import InsufficientAvailableStockError
from orderflow.modules.inventory.models import Warehouse
from orderflow.modules.inventory.service import InventoryService
from orderflow.modules.orders.domain import OrderFilters, OrderStatus
from orderflow.modules.orders.errors import InvalidIdempotencyKeyError, OrderNotFoundError
from orderflow.modules.orders.service import OrderService
from orderflow.modules.outbox.domain import OutboxEventType
from tests.fakes import (
    FakeCartRepository,
    FakeCatalogRepository,
    FakeInventoryRepository,
    FakeOrderRepository,
    FakeOutboxRepository,
)


@dataclass(slots=True)
class OrderContext:
    service: OrderService
    cart: CartService
    catalog: CatalogService
    inventory: InventoryService
    cart_repository: FakeCartRepository
    inventory_repository: FakeInventoryRepository
    order_repository: FakeOrderRepository
    outbox_repository: FakeOutboxRepository
    product: Product
    warehouse: Warehouse
    customer_id: UUID


async def build_order_context() -> OrderContext:
    catalog_repository = FakeCatalogRepository()
    catalog = CatalogService(catalog_repository)
    category = await catalog.create_category(
        name="Laptops",
        slug="laptops",
        parent_id=None,
        is_active=True,
    )
    product = await catalog.create_product(
        category_id=category.id,
        name="Laptop Pro",
        slug="laptop-pro",
        sku="LAPTOP-PRO",
        description=None,
        price_minor=199_900,
        currency="RUB",
        image_url=None,
        is_active=True,
    )
    inventory_repository = FakeInventoryRepository()
    inventory = InventoryService(inventory_repository, catalog)
    warehouse = await inventory.create_warehouse(
        name="Main warehouse",
        code="MAIN",
        location=None,
        is_active=True,
    )
    customer_id = uuid4()
    await inventory.receive_stock(
        warehouse_id=warehouse.id,
        product_id=product.id,
        quantity=5,
        reason="Test delivery",
        actor_id=uuid4(),
    )
    cart_repository = FakeCartRepository()
    cart = CartService(cart_repository, catalog, inventory)
    order_repository = FakeOrderRepository()
    outbox_repository = FakeOutboxRepository()
    return OrderContext(
        service=OrderService(order_repository, cart, catalog, inventory, outbox_repository),
        cart=cart,
        catalog=catalog,
        inventory=inventory,
        cart_repository=cart_repository,
        inventory_repository=inventory_repository,
        order_repository=order_repository,
        outbox_repository=outbox_repository,
        product=product,
        warehouse=warehouse,
        customer_id=customer_id,
    )


async def test_checkout_is_atomic_in_shape_idempotent_and_snapshots_catalog() -> None:
    context = await build_order_context()
    await context.cart.add_item(
        customer_id=context.customer_id,
        product_id=context.product.id,
        warehouse_id=context.warehouse.id,
        quantity=2,
    )
    inventory_commits_before = context.inventory_repository.commits

    created = await context.service.checkout(
        customer_id=context.customer_id,
        idempotency_key=" checkout-42 ",
    )
    replay = await context.service.checkout(
        customer_id=context.customer_id,
        idempotency_key="checkout-42",
    )

    assert created.created is True
    assert replay.created is False
    assert replay.bundle.order.id == created.bundle.order.id
    assert created.bundle.order.status is OrderStatus.PENDING_PAYMENT
    assert created.bundle.order.total_minor == 399_800
    assert created.bundle.items[0].product_name == "Laptop Pro"
    assert created.bundle.items[0].product_sku == "LAPTOP-PRO"
    assert created.bundle.items[0].unit_price_minor == 199_900
    assert context.inventory_repository.commits == inventory_commits_before
    balance = context.inventory_repository.balances[(context.warehouse.id, context.product.id)]
    assert balance.on_hand == 5
    assert balance.reserved == 2
    assert (await context.cart.get_cart(context.customer_id)).items == []
    assert context.order_repository.idempotency_locks == [
        (context.customer_id, "checkout-42"),
        (context.customer_id, "checkout-42"),
    ]
    assert len(context.outbox_repository.events) == 1
    event = context.outbox_repository.events[0]
    assert event.event_type is OutboxEventType.ORDER_CREATED
    assert event.aggregate_id == created.bundle.order.id
    assert event.payload["total_minor"] == 399_800
    assert event.payload["item_count"] == 1

    await context.catalog.update_product(
        context.product.id,
        {"name": "Laptop Pro New", "sku": "LAPTOP-PRO-NEW", "price_minor": 250_000},
    )
    stored = await context.service.get_order(
        created.bundle.order.id,
        requester_id=context.customer_id,
        requester_role=UserRole.CUSTOMER,
    )
    assert stored.items[0].product_name == "Laptop Pro"
    assert stored.items[0].product_sku == "LAPTOP-PRO"
    assert stored.items[0].unit_price_minor == 199_900


async def test_checkout_rolls_back_on_insufficient_stock_and_validates_key() -> None:
    context = await build_order_context()
    await context.cart.add_item(
        customer_id=context.customer_id,
        product_id=context.product.id,
        warehouse_id=context.warehouse.id,
        quantity=6,
    )

    with pytest.raises(InsufficientAvailableStockError):
        await context.service.checkout(
            customer_id=context.customer_id,
            idempotency_key="insufficient-order",
        )
    assert context.order_repository.rollbacks == 1
    assert len((await context.cart.get_cart(context.customer_id)).items) == 1

    with pytest.raises(InvalidIdempotencyKeyError):
        await context.service.checkout(customer_id=context.customer_id, idempotency_key="   ")


async def test_order_visibility_is_scoped_for_customers_and_open_for_managers() -> None:
    context = await build_order_context()
    await context.cart.add_item(
        customer_id=context.customer_id,
        product_id=context.product.id,
        warehouse_id=context.warehouse.id,
        quantity=1,
    )
    checkout = await context.service.checkout(
        customer_id=context.customer_id,
        idempotency_key="visible-order",
    )
    stranger_id = uuid4()

    own_page = await context.service.list_orders(
        OrderFilters(customer_id=stranger_id),
        requester_id=context.customer_id,
        requester_role=UserRole.CUSTOMER,
    )
    stranger_page = await context.service.list_orders(
        OrderFilters(),
        requester_id=stranger_id,
        requester_role=UserRole.CUSTOMER,
    )
    manager_page = await context.service.list_orders(
        OrderFilters(customer_id=context.customer_id),
        requester_id=uuid4(),
        requester_role=UserRole.MANAGER,
    )
    assert own_page.total == 1
    assert stranger_page.total == 0
    assert manager_page.total == 1

    with pytest.raises(OrderNotFoundError):
        await context.service.get_order(
            checkout.bundle.order.id,
            requester_id=stranger_id,
            requester_role=UserRole.CUSTOMER,
        )
