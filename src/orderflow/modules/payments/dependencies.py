from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.core.config import Settings
from orderflow.modules.auth.dependencies import get_database_session
from orderflow.modules.catalog.repository import CatalogRepository
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.repository import InventoryRepository
from orderflow.modules.inventory.service import InventoryService
from orderflow.modules.orders.repository import OrderRepository
from orderflow.modules.payments.provider import MockPaymentProvider
from orderflow.modules.payments.repository import PaymentRepository
from orderflow.modules.payments.service import PaymentService


def get_payment_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> PaymentService:
    settings = cast(Settings, request.app.state.settings)
    catalog = CatalogService(CatalogRepository(session))
    inventory = InventoryService(InventoryRepository(session), catalog)
    provider = MockPaymentProvider(
        webhook_secret=settings.payment_webhook_secret.get_secret_value(),
        session_ttl_minutes=settings.payment_session_ttl_minutes,
    )
    return PaymentService(
        PaymentRepository(session),
        OrderRepository(session),
        inventory,
        provider,
        webhook_tolerance_seconds=settings.payment_webhook_tolerance_seconds,
    )
