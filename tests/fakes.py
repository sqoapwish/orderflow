from datetime import UTC, datetime
from uuid import UUID, uuid4

from argon2 import PasswordHasher

from orderflow.core.config import Settings
from orderflow.modules.auth.models import RefreshSession, User
from orderflow.modules.auth.security import PasswordService, TokenService
from orderflow.modules.auth.service import AuthService


class FakeAuthRepository:
    def __init__(self) -> None:
        self.users_by_email: dict[str, User] = {}
        self.users_by_id: dict[UUID, User] = {}
        self.sessions: dict[UUID, RefreshSession] = {}
        self.commits = 0
        self.rollbacks = 0

    async def get_user_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.users_by_id.get(user_id)

    async def get_refresh_session(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None:
        return self.sessions.get(session_id)

    def add_user(self, user: User) -> None:
        now = datetime.now(UTC)
        user.id = uuid4()
        user.is_active = True
        user.created_at = now
        user.updated_at = now
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user

    def add_refresh_session(self, session: RefreshSession) -> None:
        self.sessions[session.id] = session

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_auth_service(
    settings: Settings,
) -> tuple[AuthService, FakeAuthRepository, PasswordService, TokenService]:
    repository = FakeAuthRepository()
    password_service = PasswordService(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    token_service = TokenService(settings)
    service = AuthService(repository, password_service, token_service)
    return service, repository, password_service, token_service
