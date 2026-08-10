from typing import cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Enum, Table

from orderflow.modules.auth.models import User


def test_alembic_has_exactly_one_head() -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["20260810_0002"]


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
