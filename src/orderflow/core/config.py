from enum import StrEnum
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_JWT_SECRET = "local-development-jwt-secret-change-me"


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ORDERFLOW_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "OrderFlow API"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://orderflow:orderflow@localhost:5435/orderflow"
    database_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1, le=50)
    database_max_overflow: int = Field(default=20, ge=0, le=100)

    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672//"
    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    jwt_secret: SecretStr = SecretStr(LOCAL_JWT_SECRET)
    jwt_issuer: str = "orderflow"
    jwt_audience: str = "orderflow-api"
    jwt_access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    jwt_refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API prefix must start with '/'")
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Unsupported log level")
        return normalized

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.environment is Environment.PRODUCTION and self.debug:
            raise ValueError("Debug mode must be disabled in production")
        if (
            self.environment is Environment.PRODUCTION
            and self.jwt_secret.get_secret_value() == LOCAL_JWT_SECRET
        ):
            raise ValueError("Default JWT secret must not be used in production")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT secret must contain at least 32 characters")
        return self
