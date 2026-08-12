from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from orderflow.modules.payments.domain import PaymentFilters
from orderflow.modules.payments.models import Payment, PaymentRefund, PaymentWebhookEvent


@dataclass(frozen=True, slots=True)
class PaymentBundle:
    payment: Payment
    refund: PaymentRefund | None


class PaymentRepositoryProtocol(Protocol):
    async def acquire_session_lock(self, customer_id: UUID, key: str) -> None: ...

    async def acquire_event_lock(self, provider_event_id: str) -> None: ...

    async def acquire_refund_lock(self, payment_id: UUID) -> None: ...

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> PaymentBundle | None: ...

    async def get_by_order(
        self,
        order_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None: ...

    async def get(
        self,
        payment_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None: ...

    async def get_by_provider_id(
        self,
        provider_payment_id: str,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None: ...

    async def list_payments(
        self,
        filters: PaymentFilters,
    ) -> tuple[list[PaymentBundle], int]: ...

    async def get_event(self, provider_event_id: str) -> PaymentWebhookEvent | None: ...

    async def get_refund_by_payment(self, payment_id: UUID) -> PaymentRefund | None: ...

    def add_payment(self, payment: Payment) -> None: ...

    def add_event(self, event: PaymentWebhookEvent) -> None: ...

    def add_refund(self, refund: PaymentRefund) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_session_lock(self, customer_id: UUID, key: str) -> None:
        lock_key = f"payment-session:{customer_id}:{key}"
        await self._advisory_lock(lock_key)

    async def acquire_event_lock(self, provider_event_id: str) -> None:
        await self._advisory_lock(f"payment-event:{provider_event_id}")

    async def acquire_refund_lock(self, payment_id: UUID) -> None:
        await self._advisory_lock(f"payment-refund:{payment_id}")

    async def get_by_idempotency_key(
        self,
        customer_id: UUID,
        key: str,
    ) -> PaymentBundle | None:
        statement = select(Payment).where(
            Payment.customer_id == customer_id,
            Payment.idempotency_key == key,
        )
        payment = (await self._session.execute(statement)).scalar_one_or_none()
        return await self._bundle(payment)

    async def get_by_order(
        self,
        order_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        statement = select(Payment).where(Payment.order_id == order_id)
        if for_update:
            statement = statement.with_for_update()
        payment = (await self._session.execute(statement)).scalar_one_or_none()
        return await self._bundle(payment)

    async def get(
        self,
        payment_id: UUID,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        payment = await self._session.get(Payment, payment_id, with_for_update=for_update)
        return await self._bundle(payment)

    async def get_by_provider_id(
        self,
        provider_payment_id: str,
        *,
        for_update: bool = False,
    ) -> PaymentBundle | None:
        statement = select(Payment).where(Payment.provider_payment_id == provider_payment_id)
        if for_update:
            statement = statement.with_for_update()
        payment = (await self._session.execute(statement)).scalar_one_or_none()
        return await self._bundle(payment)

    async def list_payments(
        self,
        filters: PaymentFilters,
    ) -> tuple[list[PaymentBundle], int]:
        conditions: list[ColumnElement[bool]] = []
        if filters.customer_id is not None:
            conditions.append(Payment.customer_id == filters.customer_id)
        if filters.status is not None:
            conditions.append(Payment.status == filters.status)
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(Payment).where(*conditions)
                )
            )
            or 0
        )
        statement = (
            select(Payment)
            .where(*conditions)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        payments = list((await self._session.execute(statement)).scalars().all())
        refunds = await self._refunds_by_payment([payment.id for payment in payments])
        return [
            PaymentBundle(payment=payment, refund=refunds.get(payment.id)) for payment in payments
        ], total

    async def get_event(self, provider_event_id: str) -> PaymentWebhookEvent | None:
        statement = select(PaymentWebhookEvent).where(
            PaymentWebhookEvent.provider_event_id == provider_event_id
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_refund_by_payment(self, payment_id: UUID) -> PaymentRefund | None:
        statement = select(PaymentRefund).where(PaymentRefund.payment_id == payment_id)
        return (await self._session.execute(statement)).scalar_one_or_none()

    def add_payment(self, payment: Payment) -> None:
        self._session.add(payment)

    def add_event(self, event: PaymentWebhookEvent) -> None:
        self._session.add(event)

    def add_refund(self, refund: PaymentRefund) -> None:
        self._session.add(refund)

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def _bundle(self, payment: Payment | None) -> PaymentBundle | None:
        if payment is None:
            return None
        return PaymentBundle(
            payment=payment,
            refund=await self.get_refund_by_payment(payment.id),
        )

    async def _refunds_by_payment(
        self,
        payment_ids: list[UUID],
    ) -> dict[UUID, PaymentRefund]:
        if not payment_ids:
            return {}
        statement = select(PaymentRefund).where(PaymentRefund.payment_id.in_(payment_ids))
        refunds = list((await self._session.execute(statement)).scalars().all())
        return {refund.payment_id: refund for refund in refunds}

    async def _advisory_lock(self, lock_key: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 202608120006))"),
            {"lock_key": lock_key},
        )
