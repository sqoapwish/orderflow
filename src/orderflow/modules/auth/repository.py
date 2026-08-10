from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.modules.auth.models import RefreshSession, User


class AuthRepositoryProtocol(Protocol):
    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user_by_id(self, user_id: UUID) -> User | None: ...

    async def get_refresh_session(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None: ...

    def add_user(self, user: User) -> None: ...

    def add_refresh_session(self, session: RefreshSession) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_refresh_session(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None:
        statement = select(RefreshSession).where(RefreshSession.id == session_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add_user(self, user: User) -> None:
        self._session.add(user)

    def add_refresh_session(self, session: RefreshSession) -> None:
        self._session.add(session)

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
