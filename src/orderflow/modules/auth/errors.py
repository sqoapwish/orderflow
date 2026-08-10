from fastapi import status

from orderflow.core.errors import ApplicationError

BEARER_HEADERS = {"WWW-Authenticate": "Bearer"}


class EmailAlreadyRegisteredError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="email_already_registered",
            message="A user with this email already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidCredentialsError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_credentials",
            message="Email or password is incorrect",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=BEARER_HEADERS,
        )


class InvalidAccessTokenError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_access_token",
            message="Access token is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=BEARER_HEADERS,
        )


class InvalidRefreshTokenError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_refresh_token",
            message="Refresh token is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers=BEARER_HEADERS,
        )


class InsufficientRoleError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="insufficient_role",
            message="The current user does not have permission for this action",
            status_code=status.HTTP_403_FORBIDDEN,
        )
