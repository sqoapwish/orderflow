from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.errors import (
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from orderflow.modules.auth.models import RefreshSession, User
from orderflow.modules.auth.repository import AuthRepositoryProtocol
from orderflow.modules.auth.security import (
    DUMMY_PASSWORD_HASH,
    PasswordService,
    TokenDecodeError,
    TokenService,
    hash_refresh_token,
    refresh_token_matches,
)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    tokens: TokenPair


class AuthService:
    def __init__(
        self,
        repository: AuthRepositoryProtocol,
        password_service: PasswordService,
        token_service: TokenService,
    ) -> None:
        self._repository = repository
        self._passwords = password_service
        self._tokens = token_service

    async def register(self, email: str, password: str) -> AuthResult:
        if await self._repository.get_user_by_email(email) is not None:
            raise EmailAlreadyRegisteredError

        user = User(
            email=email,
            password_hash=self._passwords.hash(password),
            role=UserRole.CUSTOMER,
        )
        self._repository.add_user(user)
        try:
            await self._repository.flush()
            tokens = self._create_session(user)
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            raise EmailAlreadyRegisteredError from None
        return AuthResult(user=user, tokens=tokens)

    async def login(self, email: str, password: str) -> AuthResult:
        user = await self._repository.get_user_by_email(email)
        if user is None:
            self._passwords.verify(password, DUMMY_PASSWORD_HASH)
            raise InvalidCredentialsError

        password_is_valid = self._passwords.verify(password, user.password_hash)
        if not user.is_active or not password_is_valid:
            raise InvalidCredentialsError

        if self._passwords.needs_rehash(user.password_hash):
            user.password_hash = self._passwords.hash(password)

        tokens = self._create_session(user)
        await self._repository.commit()
        return AuthResult(user=user, tokens=tokens)

    async def refresh(self, refresh_token: str) -> TokenPair:
        try:
            claims = self._tokens.decode_refresh_token(refresh_token)
        except TokenDecodeError:
            raise InvalidRefreshTokenError from None

        session = await self._repository.get_refresh_session(claims.session_id, for_update=True)
        if session is None or session.user_id != claims.user_id:
            raise InvalidRefreshTokenError

        now = datetime.now(UTC)
        if session.revoked_at is not None or session.expires_at <= now:
            raise InvalidRefreshTokenError

        if not refresh_token_matches(refresh_token, session.token_hash):
            session.revoked_at = now
            await self._repository.commit()
            raise InvalidRefreshTokenError

        user = await self._repository.get_user_by_id(claims.user_id)
        if user is None or not user.is_active:
            session.revoked_at = now
            await self._repository.commit()
            raise InvalidRefreshTokenError

        rotated_refresh_token = self._tokens.create_refresh_token(user.id, session.id)
        session.token_hash = hash_refresh_token(rotated_refresh_token)
        session.last_used_at = now
        await self._repository.commit()
        return self._token_pair(user, rotated_refresh_token)

    async def logout(self, refresh_token: str) -> None:
        try:
            claims = self._tokens.decode_refresh_token(refresh_token)
        except TokenDecodeError:
            return

        session = await self._repository.get_refresh_session(claims.session_id, for_update=True)
        if session is None or session.user_id != claims.user_id or session.revoked_at is not None:
            return

        session.revoked_at = datetime.now(UTC)
        await self._repository.commit()

    async def authenticate_access_token(self, access_token: str) -> User:
        try:
            claims = self._tokens.decode_access_token(access_token)
        except TokenDecodeError:
            raise InvalidAccessTokenError from None

        user = await self._repository.get_user_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise InvalidAccessTokenError
        return user

    def _create_session(self, user: User) -> TokenPair:
        now = datetime.now(UTC)
        session = RefreshSession(
            id=uuid4(),
            user_id=user.id,
            token_hash="",
            expires_at=now + self._tokens.refresh_ttl,
        )
        refresh_token = self._tokens.create_refresh_token(user.id, session.id)
        session.token_hash = hash_refresh_token(refresh_token)
        self._repository.add_refresh_session(session)
        return self._token_pair(user, refresh_token)

    def _token_pair(self, user: User, refresh_token: str) -> TokenPair:
        return TokenPair(
            access_token=self._tokens.create_access_token(user.id, user.role),
            refresh_token=refresh_token,
            expires_in=self._tokens.access_ttl_seconds,
        )
