import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from orderflow.core.config import Settings
from orderflow.modules.auth.domain import UserRole

JWT_ALGORITHM = "HS256"
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$xjMYwkdeaA10aklUG2waoQ$"
    "9ny/BqYZEyEKInVL43FNTzi1KDHYOfBPkdRJH6RgAuY"
)


class TokenDecodeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    role: UserRole


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    user_id: UUID
    session_id: UUID


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._access_ttl = timedelta(minutes=settings.jwt_access_token_ttl_minutes)
        self._refresh_ttl = timedelta(days=settings.jwt_refresh_token_ttl_days)

    @property
    def access_ttl_seconds(self) -> int:
        return int(self._access_ttl.total_seconds())

    @property
    def refresh_ttl(self) -> timedelta:
        return self._refresh_ttl

    def create_access_token(self, user_id: UUID, role: UserRole) -> str:
        now = datetime.now(UTC)
        return self._encode(
            {
                "sub": str(user_id),
                "role": role.value,
                "token_type": "access",
                "jti": str(uuid4()),
                "iat": now,
                "exp": now + self._access_ttl,
            }
        )

    def create_refresh_token(self, user_id: UUID, session_id: UUID) -> str:
        now = datetime.now(UTC)
        return self._encode(
            {
                "sub": str(user_id),
                "sid": str(session_id),
                "token_type": "refresh",
                "jti": str(uuid4()),
                "iat": now,
                "exp": now + self._refresh_ttl,
            }
        )

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        claims = self._decode(token, expected_type="access", required_claims=["role"])
        try:
            return AccessTokenClaims(
                user_id=UUID(self._string_claim(claims, "sub")),
                role=UserRole(self._string_claim(claims, "role")),
            )
        except (ValueError, TypeError) as exc:
            raise TokenDecodeError from exc

    def decode_refresh_token(self, token: str) -> RefreshTokenClaims:
        claims = self._decode(token, expected_type="refresh", required_claims=["sid"])
        try:
            return RefreshTokenClaims(
                user_id=UUID(self._string_claim(claims, "sub")),
                session_id=UUID(self._string_claim(claims, "sid")),
            )
        except (ValueError, TypeError) as exc:
            raise TokenDecodeError from exc

    def _decode(
        self,
        token: str,
        *,
        expected_type: str,
        required_claims: list[str],
    ) -> dict[str, object]:
        try:
            decoded = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "iss",
                        "aud",
                        "sub",
                        "jti",
                        "token_type",
                        *required_claims,
                    ]
                },
            )
        except jwt.InvalidTokenError as exc:
            raise TokenDecodeError from exc

        claims = cast(dict[str, object], decoded)
        if claims.get("token_type") != expected_type:
            raise TokenDecodeError
        return claims

    def _base_claims(self) -> dict[str, object]:
        return {"iss": self._issuer, "aud": self._audience}

    @staticmethod
    def _string_claim(claims: dict[str, object], name: str) -> str:
        value = claims.get(name)
        if not isinstance(value, str):
            raise TokenDecodeError
        return value

    def _encode(self, claims: dict[str, object]) -> str:
        return jwt.encode(
            {**self._base_claims(), **claims},
            self._secret,
            algorithm=JWT_ALGORITHM,
        )


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_token_matches(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_refresh_token(token), expected_hash)
