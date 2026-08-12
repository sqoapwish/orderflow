from typing import cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Enum, Table

from orderflow.modules.auth.models import User
from orderflow.modules.catalog.models import Category, Product


def test_alembic_has_exactly_one_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20260812_0003"]


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
