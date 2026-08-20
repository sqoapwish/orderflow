"""Create idempotent local data for demonstrating the OrderFlow interface."""

import asyncio
import os
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.core.config import Environment, Settings
from orderflow.infrastructure.database import Database
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.auth.security import PasswordService
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.catalog.repository import CatalogRepository
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.models import StockBalance, Warehouse
from orderflow.modules.inventory.repository import InventoryRepository
from orderflow.modules.inventory.service import InventoryService


@dataclass(frozen=True, slots=True)
class DemoProduct:
    name: str
    slug: str
    sku: str
    description: str
    price_minor: int
    quantity: int


DEMO_PRODUCTS = (
    DemoProduct(
        name="Ежедневник Focus",
        slug="focus-planner",
        sku="DEMO-PLANNER",
        description="Недатированный ежедневник для спокойного планирования задач.",
        price_minor=149_000,
        quantity=32,
    ),
    DemoProduct(
        name="Клавиатура AirType",
        slug="airtype-keyboard",
        sku="DEMO-KEYBOARD",
        description="Компактная беспроводная клавиатура для домашнего офиса.",
        price_minor=699_000,
        quantity=18,
    ),
    DemoProduct(
        name="Лампа Orbit",
        slug="orbit-lamp",
        sku="DEMO-LAMP",
        description="Настольный светильник: мягкий регулируемый свет.",
        price_minor=429_000,
        quantity=9,
    ),
    DemoProduct(
        name="Рюкзак Atlas",
        slug="atlas-backpack",
        sku="DEMO-BACKPACK",
        description="Городской рюкзак, защищённое отделение для ноутбука.",
        price_minor=589_000,
        quantity=14,
    ),
)


async def seed_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    role: UserRole,
    passwords: PasswordService,
) -> User:
    user = await session.scalar(select(User).where(User.email == email))
    password_hash = passwords.hash(password)
    if user is None:
        user = User(email=email, password_hash=password_hash, role=role)
        session.add(user)
    else:
        user.password_hash = password_hash
        user.role = role
        user.is_active = True
    await session.commit()
    return user


async def seed() -> None:
    settings = Settings()
    if settings.environment not in {Environment.LOCAL, Environment.TEST}:
        raise RuntimeError("Demo data can only be seeded in local or test environments")

    database = Database(settings)
    passwords = PasswordService()
    customer_password = os.getenv("ORDERFLOW_DEMO_CUSTOMER_PASSWORD", "Customer-demo-2026")
    manager_password = os.getenv("ORDERFLOW_DEMO_MANAGER_PASSWORD", "Manager-demo-2026")
    admin_password = os.getenv("ORDERFLOW_DEMO_ADMIN_PASSWORD", "Admin-demo-2026")

    try:
        async with database.session_factory() as session:
            await seed_user(
                session,
                email="customer@orderflow.local",
                password=customer_password,
                role=UserRole.CUSTOMER,
                passwords=passwords,
            )
            manager = await seed_user(
                session,
                email="manager@orderflow.local",
                password=manager_password,
                role=UserRole.MANAGER,
                passwords=passwords,
            )
            await seed_user(
                session,
                email="admin@orderflow.local",
                password=admin_password,
                role=UserRole.ADMIN,
                passwords=passwords,
            )

            catalog = CatalogService(CatalogRepository(session))
            category = await session.scalar(
                select(Category).where(Category.slug == "demo-workspace")
            )
            if category is None:
                category = await catalog.create_category(
                    name="Рабочее пространство",
                    slug="demo-workspace",
                    parent_id=None,
                    is_active=True,
                )
            elif not category.is_active:
                category.is_active = True
                await session.commit()

            inventory = InventoryService(
                InventoryRepository(session),
                catalog,
            )
            warehouse = await session.scalar(select(Warehouse).where(Warehouse.code == "DEMO-MSK"))
            if warehouse is None:
                warehouse = await inventory.create_warehouse(
                    name="Демо-склад Москва",
                    code="DEMO-MSK",
                    location="Москва",
                    is_active=True,
                )
            elif not warehouse.is_active:
                warehouse.is_active = True
                await session.commit()

            for item in DEMO_PRODUCTS:
                product = await session.scalar(select(Product).where(Product.sku == item.sku))
                if product is None:
                    product = await catalog.create_product(
                        category_id=category.id,
                        name=item.name,
                        slug=item.slug,
                        sku=item.sku,
                        description=item.description,
                        price_minor=item.price_minor,
                        currency="RUB",
                        image_url=None,
                        is_active=True,
                    )
                elif not product.is_active:
                    product.is_active = True
                    await session.commit()

                balance = await session.scalar(
                    select(StockBalance).where(
                        StockBalance.warehouse_id == warehouse.id,
                        StockBalance.product_id == product.id,
                    )
                )
                if balance is None or balance.available == 0:
                    await inventory.receive_stock(
                        warehouse_id=warehouse.id,
                        product_id=product.id,
                        quantity=item.quantity,
                        reason="Local interface demo seed",
                        actor_id=manager.id,
                    )
    finally:
        await database.close()

    print("OrderFlow demo data is ready")
    print(f"customer@orderflow.local / {customer_password}")
    print(f"manager@orderflow.local / {manager_password}")
    print(f"admin@orderflow.local / {admin_password}")


if __name__ == "__main__":
    asyncio.run(seed())
