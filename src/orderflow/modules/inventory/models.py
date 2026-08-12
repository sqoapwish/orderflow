from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from orderflow.infrastructure.database import Base
from orderflow.modules.inventory.domain import InventoryMovementType, ReservationStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]*$'",
            name="warehouse_code_format",
        ),
        Index("ix_warehouses_active_name", "is_active", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="stock_on_hand_nonnegative"),
        CheckConstraint("reserved >= 0", name="stock_reserved_nonnegative"),
        CheckConstraint("reserved <= on_hand", name="stock_reserved_within_on_hand"),
        UniqueConstraint(
            "warehouse_id",
            "product_id",
            name="uq_stock_balances_warehouse_product",
        ),
        Index("ix_stock_balances_product_warehouse", "product_id", "warehouse_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    on_hand: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="reservation_positive_quantity"),
        CheckConstraint(
            "status IN ('active', 'released', 'consumed')",
            name="reservation_status",
        ),
        Index(
            "ix_inventory_reservations_stock_status",
            "warehouse_id",
            "product_id",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(
            ReservationStatus,
            name="inventory_reservation_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ReservationStatus.ACTIVE,
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ("
            "'receipt', 'write_off', 'adjustment', 'transfer_in', 'transfer_out', "
            "'reservation_created', 'reservation_released', 'reservation_consumed'"
            ")",
            name="inventory_movement_type",
        ),
        CheckConstraint(
            "delta_on_hand <> 0 OR delta_reserved <> 0",
            name="inventory_movement_nonzero_delta",
        ),
        CheckConstraint(
            "balance_on_hand >= 0 AND balance_reserved >= 0 "
            "AND balance_reserved <= balance_on_hand",
            name="inventory_movement_valid_snapshot",
        ),
        Index(
            "ix_inventory_movements_stock_created",
            "warehouse_id",
            "product_id",
            "created_at",
        ),
        Index("ix_inventory_movements_operation_id", "operation_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    operation_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_reservations.id", ondelete="RESTRICT"),
    )
    movement_type: Mapped[InventoryMovementType] = mapped_column(
        Enum(
            InventoryMovementType,
            name="inventory_movement_type",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    delta_on_hand: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delta_reserved: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_on_hand: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_reserved: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
