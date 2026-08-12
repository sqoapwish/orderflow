from typing import cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Enum, Table

from orderflow.modules.auth.models import User
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)


def test_alembic_has_exactly_one_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20260812_0004"]


def test_user_role_check_constraint_is_explicit_and_named() -> None:
    user_table = cast(Table, User.__table__)
    constraints = {
        constraint.name: constraint
        for constraint in user_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    role_constraint = constraints["ck_users_user_role"]
    role_type = cast(Enum, user_table.c.role.type)

    assert role_constraint._type_bound is False
    assert str(role_constraint.sqltext) == "role IN ('customer', 'manager', 'admin')"
    assert role_type.create_constraint is False


def test_catalog_constraints_and_indexes_are_explicit_and_named() -> None:
    category_table = cast(Table, Category.__table__)
    product_table = cast(Table, Product.__table__)
    category_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in category_table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    product_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in product_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert category_checks == {
        "ck_categories_category_not_own_parent": "id <> parent_id",
    }
    assert product_checks == {
        "ck_products_currency_format": ("char_length(currency) = 3 AND currency = upper(currency)"),
        "ck_products_positive_price": "price_minor > 0",
    }
    assert {index.name for index in category_table.indexes} == {
        "ix_categories_active_name",
        "ix_categories_parent_id",
    }
    assert {index.name for index in product_table.indexes} == {
        "ix_products_price_minor",
        "ix_products_public_catalog",
    }


def test_inventory_constraints_and_indexes_are_explicit_and_named() -> None:
    warehouse_table = cast(Table, Warehouse.__table__)
    balance_table = cast(Table, StockBalance.__table__)
    reservation_table = cast(Table, InventoryReservation.__table__)
    movement_table = cast(Table, InventoryMovement.__table__)

    def checks(table: Table) -> dict[str, str]:
        result: dict[str, str] = {}
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint):
                assert constraint.name is not None
                result[str(constraint.name)] = str(constraint.sqltext)
        return result

    assert checks(warehouse_table) == {
        "ck_warehouses_warehouse_code_format": "code ~ '^[A-Z0-9][A-Z0-9_-]*$'",
    }
    assert checks(balance_table) == {
        "ck_stock_balances_stock_on_hand_nonnegative": "on_hand >= 0",
        "ck_stock_balances_stock_reserved_nonnegative": "reserved >= 0",
        "ck_stock_balances_stock_reserved_within_on_hand": "reserved <= on_hand",
    }
    assert checks(reservation_table) == {
        "ck_inventory_reservations_reservation_positive_quantity": "quantity > 0",
        "ck_inventory_reservations_reservation_status": (
            "status IN ('active', 'released', 'consumed')"
        ),
    }
    assert checks(movement_table) == {
        "ck_inventory_movements_inventory_movement_nonzero_delta": (
            "delta_on_hand <> 0 OR delta_reserved <> 0"
        ),
        "ck_inventory_movements_inventory_movement_type": (
            "movement_type IN ('receipt', 'write_off', 'adjustment', 'transfer_in', "
            "'transfer_out', 'reservation_created', 'reservation_released', "
            "'reservation_consumed')"
        ),
        "ck_inventory_movements_inventory_movement_valid_snapshot": (
            "balance_on_hand >= 0 AND balance_reserved >= 0 AND balance_reserved <= balance_on_hand"
        ),
    }
    assert {index.name for index in warehouse_table.indexes} == {
        "ix_warehouses_active_name",
    }
    assert {index.name for index in balance_table.indexes} == {
        "ix_stock_balances_product_warehouse",
    }
    assert {index.name for index in reservation_table.indexes} == {
        "ix_inventory_reservations_stock_status",
    }
    assert {index.name for index in movement_table.indexes} == {
        "ix_inventory_movements_operation_id",
        "ix_inventory_movements_stock_created",
    }
