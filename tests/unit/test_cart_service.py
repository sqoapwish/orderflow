from uuid import uuid4

import pytest

from orderflow.modules.cart.errors import CartCurrencyConflictError, CartItemNotFoundError
from orderflow.modules.cart.service import CartService
from orderflow.modules.catalog.models import Product
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.models import Warehouse
from orderflow.modules.inventory.service import InventoryService
from tests.fakes import FakeCartRepository, FakeCatalogRepository, FakeInventoryRepository


async def build_cart_context() -> tuple[
    CartService,
    CatalogService,
    FakeCartRepository,
    FakeCatalogRepository,
    FakeInventoryRepository,
    Product,
    Warehouse,
]:
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
    cart_repository = FakeCartRepository()
    return (
        CartService(cart_repository, catalog, inventory),
        catalog,
        cart_repository,
        catalog_repository,
        inventory_repository,
        product,
        warehouse,
    )


async def test_cart_uses_current_prices_and_supports_all_mutations() -> None:
    service, catalog, repository, _, _, product_value, warehouse_value = await build_cart_context()
    product = product_value
    warehouse = warehouse_value
    customer_id = uuid4()

    empty = await service.get_cart(customer_id)
    assert empty.cart is None
    assert empty.items == []
    assert empty.total_minor == 0

    added = await service.add_item(
        customer_id=customer_id,
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=2,
    )
    combined = await service.add_item(
        customer_id=customer_id,
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=1,
    )
    assert added.total_minor == 399_800
    assert combined.items[0].item.quantity == 3

    await catalog.update_product(product.id, {"price_minor": 189_900})
    repriced = await service.get_cart(customer_id)
    assert repriced.items[0].product.price_minor == 189_900
    assert repriced.total_minor == 569_700

    updated = await service.update_item(
        customer_id=customer_id,
        item_id=repriced.items[0].item.id,
        quantity=1,
    )
    assert updated.total_minor == 189_900
    removed = await service.remove_item(
        customer_id=customer_id,
        item_id=updated.items[0].item.id,
    )
    assert removed.items == []

    with pytest.raises(CartItemNotFoundError):
        await service.remove_item(customer_id=customer_id, item_id=uuid4())

    await service.clear(customer_id)
    assert repository.customer_locks.count(customer_id) == 6


async def test_cart_rejects_mixed_currency_and_marks_archived_product_unavailable() -> None:
    (
        service,
        catalog,
        _,
        catalog_repository,
        _,
        product_value,
        warehouse_value,
    ) = await build_cart_context()
    product = product_value
    warehouse = warehouse_value
    category = next(iter(catalog_repository.categories.values()))
    usd_product = await catalog.create_product(
        category_id=category.id,
        name="USB adapter",
        slug="usb-adapter",
        sku="USB-ADAPTER",
        description=None,
        price_minor=2_500,
        currency="USD",
        image_url=None,
        is_active=True,
    )
    customer_id = uuid4()
    await service.add_item(
        customer_id=customer_id,
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=1,
    )

    with pytest.raises(CartCurrencyConflictError):
        await service.add_item(
            customer_id=customer_id,
            product_id=usd_product.id,
            warehouse_id=warehouse.id,
            quantity=1,
        )

    await catalog.archive_product(product.id)
    view = await service.get_cart(customer_id)
    assert view.items[0].is_available is False
