"""Create warehouses, stock movements, and reservations.

Revision ID: 20260812_0004
Revises: 20260812_0003
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0004"
down_revision: str | Sequence[str] | None = "20260812_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]*$'",
            name=op.f("ck_warehouses_warehouse_code_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouses")),
        sa.UniqueConstraint("code", name=op.f("uq_warehouses_code")),
    )
    op.create_index(
        "ix_warehouses_active_name",
        "warehouses",
        ["is_active", "name"],
        unique=False,
    )

    op.create_table(
        "stock_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("on_hand", sa.BigInteger(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "on_hand >= 0",
            name=op.f("ck_stock_balances_stock_on_hand_nonnegative"),
        ),
        sa.CheckConstraint(
            "reserved >= 0",
            name=op.f("ck_stock_balances_stock_reserved_nonnegative"),
        ),
        sa.CheckConstraint(
            "reserved <= on_hand",
            name=op.f("ck_stock_balances_stock_reserved_within_on_hand"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_balances_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_stock_balances_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_balances")),
        sa.UniqueConstraint(
            "warehouse_id",
            "product_id",
            name="uq_stock_balances_warehouse_product",
        ),
    )
    op.create_index(
        "ix_stock_balances_product_warehouse",
        "stock_balances",
        ["product_id", "warehouse_id"],
        unique=False,
    )

    op.create_table(
        "inventory_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reservation_key", sa.String(length=128), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "released",
                "consumed",
                name="inventory_reservation_status",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_inventory_reservations_reservation_positive_quantity"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released', 'consumed')",
            name=op.f("ck_inventory_reservations_reservation_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_inventory_reservations_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_reservations_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_inventory_reservations_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_reservations")),
        sa.UniqueConstraint(
            "reservation_key",
            name=op.f("uq_inventory_reservations_reservation_key"),
        ),
    )
    op.create_index(
        "ix_inventory_reservations_stock_status",
        "inventory_reservations",
        ["warehouse_id", "product_id", "status"],
        unique=False,
    )

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "movement_type",
            sa.Enum(
                "receipt",
                "write_off",
                "adjustment",
                "transfer_in",
                "transfer_out",
                "reservation_created",
                "reservation_released",
                "reservation_consumed",
                name="inventory_movement_type",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("delta_on_hand", sa.BigInteger(), nullable=False),
        sa.Column("delta_reserved", sa.BigInteger(), nullable=False),
        sa.Column("balance_on_hand", sa.BigInteger(), nullable=False),
        sa.Column("balance_reserved", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "movement_type IN ("
            "'receipt', 'write_off', 'adjustment', 'transfer_in', 'transfer_out', "
            "'reservation_created', 'reservation_released', 'reservation_consumed'"
            ")",
            name=op.f("ck_inventory_movements_inventory_movement_type"),
        ),
        sa.CheckConstraint(
            "delta_on_hand <> 0 OR delta_reserved <> 0",
            name=op.f("ck_inventory_movements_inventory_movement_nonzero_delta"),
        ),
        sa.CheckConstraint(
            "balance_on_hand >= 0 AND balance_reserved >= 0 "
            "AND balance_reserved <= balance_on_hand",
            name=op.f("ck_inventory_movements_inventory_movement_valid_snapshot"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_inventory_movements_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_movements_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["inventory_reservations.id"],
            name=op.f("fk_inventory_movements_reservation_id_inventory_reservations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
            name=op.f("fk_inventory_movements_warehouse_id_warehouses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_movements")),
    )
    op.create_index(
        "ix_inventory_movements_operation_id",
        "inventory_movements",
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_movements_stock_created",
        "inventory_movements",
        ["warehouse_id", "product_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_stock_created", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_operation_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_index(
        "ix_inventory_reservations_stock_status",
        table_name="inventory_reservations",
    )
    op.drop_table("inventory_reservations")
    op.drop_index("ix_stock_balances_product_warehouse", table_name="stock_balances")
    op.drop_table("stock_balances")
    op.drop_index("ix_warehouses_active_name", table_name="warehouses")
    op.drop_table("warehouses")
