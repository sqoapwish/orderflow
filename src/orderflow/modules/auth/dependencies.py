from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from orderflow.core.config import Settings
from orderflow.infrastructure.resources import InfrastructureResources
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.errors import InsufficientRoleError, InvalidAccessTokenError
from orderflow.modules.auth.models import User
from orderflow.modules.auth.repository import AuthRepository
from orderflow.modules.auth.security import PasswordService, TokenService
from orderflow.modules.auth.service import AuthService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    resources = cast(InfrastructureResources, request.app.state.resources)
    async for session in resources.database.session():
        yield session


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AuthService:
    settings = cast(Settings, request.app.state.settings)
    return AuthService(
        AuthRepository(session),
        PasswordService(),
        TokenService(settings),
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidAccessTokenError
    return await service.authenticate_access_token(credentials.credentials)


def require_roles(*allowed_roles: UserRole) -> Callable[[User], Awaitable[User]]:
    async def role_dependency(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if user.role not in allowed_roles:
            raise InsufficientRoleError
        return user

    return role_dependency
