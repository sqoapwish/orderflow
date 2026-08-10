import pytest
from pydantic import ValidationError

from orderflow.core.config import Environment, Settings


def test_settings_have_safe_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORDERFLOW_ENVIRONMENT", raising=False)

    settings = Settings(_env_file=None)

    assert settings.environment is Environment.LOCAL
    assert settings.debug is False
    assert settings.api_v1_prefix == "/api/v1"


def test_settings_read_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORDERFLOW_APP_NAME", "OrderFlow Test")
    monkeypatch.setenv("ORDERFLOW_LOG_LEVEL", "warning")

    settings = Settings(_env_file=None)

    assert settings.app_name == "OrderFlow Test"
    assert settings.log_level == "WARNING"


def test_settings_reject_debug_in_production() -> None:
    with pytest.raises(ValidationError, match="Debug mode must be disabled"):
        Settings(_env_file=None, environment=Environment.PRODUCTION, debug=True)


def test_settings_reject_invalid_api_prefix() -> None:
    with pytest.raises(ValidationError, match="must start"):
        Settings(_env_file=None, api_v1_prefix="api/v2")


def test_settings_reject_short_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(_env_file=None, jwt_secret="short-secret")


def test_settings_reject_default_jwt_secret_in_production() -> None:
    with pytest.raises(ValidationError, match="must not be used in production"):
        Settings(_env_file=None, environment=Environment.PRODUCTION)
