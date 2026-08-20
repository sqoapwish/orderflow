from typing import cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Enum, Table

from orderflow.modules.audit.models import AuditEvent
from orderflow.modules.auth.models import User
from orderflow.modules.cart.models import Cart, CartItem
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)
from orderflow.modules.orders.models import Order, OrderItem
from orderflow.modules.outbox.models import InboxEvent, OutboxEvent
from orderflow.modules.payments.models import Payment, PaymentRefund, PaymentWebhookEvent


def test_alembic_has_exactly_one_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20260817_0009"]


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


def test_cart_and_order_constraints_and_indexes_are_explicit_and_named() -> None:
    cart_table = cast(Table, Cart.__table__)
    cart_item_table = cast(Table, CartItem.__table__)
    order_table = cast(Table, Order.__table__)
    order_item_table = cast(Table, OrderItem.__table__)

    def checks(table: Table) -> dict[str, str]:
        return {
            str(constraint.name): str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }

    assert checks(cart_table) == {}
    assert checks(cart_item_table) == {
        "ck_cart_items_cart_item_positive_quantity": "quantity > 0",
    }
    assert checks(order_table) == {
        "ck_orders_order_currency_format": (
            "char_length(currency) = 3 AND currency = upper(currency)"
        ),
        "ck_orders_order_positive_total": "total_minor > 0",
        "ck_orders_order_status": (
            "status IN ('pending_payment', 'paid', 'payment_failed', 'cancelled', 'refunded')"
        ),
    }
    assert checks(order_item_table) == {
        "ck_order_items_order_item_currency_format": (
            "char_length(currency) = 3 AND currency = upper(currency)"
        ),
        "ck_order_items_order_item_positive_line_total": "line_total_minor > 0",
        "ck_order_items_order_item_positive_quantity": "quantity > 0",
        "ck_order_items_order_item_positive_unit_price": "unit_price_minor > 0",
        "ck_order_items_order_item_total_matches": (
            "line_total_minor = unit_price_minor * quantity"
        ),
    }
    assert {index.name for index in cart_item_table.indexes} == {
        "ix_cart_items_cart_created",
    }
    assert {index.name for index in order_table.indexes} == {
        "ix_orders_customer_created",
        "ix_orders_status_created",
    }
    assert {index.name for index in order_item_table.indexes} == {
        "ix_order_items_order_created",
    }


def test_payment_constraints_and_indexes_are_explicit_and_named() -> None:
    payment_table = cast(Table, Payment.__table__)
    event_table = cast(Table, PaymentWebhookEvent.__table__)
    refund_table = cast(Table, PaymentRefund.__table__)

    def checks(table: Table) -> dict[str, str]:
        return {
            str(constraint.name): str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }

    assert checks(payment_table) == {
        "ck_payments_payment_currency_format": (
            "char_length(currency) = 3 AND currency = upper(currency)"
        ),
        "ck_payments_payment_positive_amount": "amount_minor > 0",
        "ck_payments_payment_provider": "provider = 'mock'",
        "ck_payments_payment_status": (
            "status IN ('pending', 'succeeded', 'failed', 'cancelled', 'refunded')"
        ),
    }
    assert checks(event_table) == {
        "ck_payment_webhook_events_payment_webhook_event_type": (
            "event_type IN ('payment.succeeded', 'payment.failed')"
        ),
        "ck_payment_webhook_events_payment_webhook_outcome": (
            "outcome IN ('processed', 'ignored')"
        ),
    }
    assert checks(refund_table) == {
        "ck_payment_refunds_payment_refund_currency_format": (
            "char_length(currency) = 3 AND currency = upper(currency)"
        ),
        "ck_payment_refunds_payment_refund_positive_amount": "amount_minor > 0",
        "ck_payment_refunds_payment_refund_status": "status IN ('succeeded')",
    }
    assert {index.name for index in payment_table.indexes} == {
        "ix_payments_customer_created",
        "ix_payments_status_created",
    }
    assert {index.name for index in event_table.indexes} == {
        "ix_payment_webhook_events_payment_created",
    }
    assert {index.name for index in refund_table.indexes} == set()


def test_outbox_constraints_and_indexes_are_explicit_and_named() -> None:
    outbox_table = cast(Table, OutboxEvent.__table__)
    inbox_table = cast(Table, InboxEvent.__table__)
    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in outbox_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert checks == {
        "ck_outbox_events_outbox_attempts_nonnegative": "attempts >= 0",
        "ck_outbox_events_outbox_event_type": (
            "event_type IN ('order.created', 'order.cancelled', 'payment.succeeded', "
            "'payment.failed', 'payment.refunded')"
        ),
        "ck_outbox_events_outbox_status": ("status IN ('pending', 'published', 'dead_letter')"),
    }
    assert {index.name for index in outbox_table.indexes} == {
        "ix_outbox_events_aggregate",
        "ix_outbox_events_analytics",
        "ix_outbox_events_dispatch",
    }
    assert {index.name for index in inbox_table.indexes} == set()


def test_audit_constraints_and_indexes_are_explicit_and_named() -> None:
    audit_table = cast(Table, AuditEvent.__table__)
    checks = {
        str(constraint.name): str(constraint.sqltext)
        for constraint in audit_table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert checks == {
        "ck_audit_events_audit_actor_identity": (
            "(actor_type = 'system' AND actor_id IS NULL) "
            "OR (actor_type = 'user' AND actor_id IS NOT NULL)"
        ),
        "ck_audit_events_audit_actor_role": (
            "actor_role IS NULL OR actor_role IN ('customer', 'manager', 'admin')"
        ),
        "ck_audit_events_audit_actor_type": "actor_type IN ('user', 'system')",
    }
    assert {index.name for index in audit_table.indexes} == {
        "ix_audit_events_action_occurred",
        "ix_audit_events_actor_occurred",
        "ix_audit_events_correlation_id",
        "ix_audit_events_resource_occurred",
    }
