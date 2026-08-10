from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from orderflow.modules.auth.dependencies import get_auth_service, get_current_user
from orderflow.modules.auth.models import User
from orderflow.modules.auth.schemas import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserResponse,
)
from orderflow.modules.auth.service import AuthResult, AuthService, TokenPair

router = APIRouter()

AuthServiceDependency = Annotated[AuthService, Depends(get_auth_service)]
CurrentUserDependency = Annotated[User, Depends(get_current_user)]


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a customer account",
)
async def register(payload: RegisterRequest, service: AuthServiceDependency) -> AuthResponse:
    result = await service.register(str(payload.email), payload.password)
    return _auth_response(result)


@router.post("/login", response_model=AuthResponse, summary="Create an authenticated session")
async def login(payload: LoginRequest, service: AuthServiceDependency) -> AuthResponse:
    result = await service.login(str(payload.email), payload.password)
    return _auth_response(result)


@router.post("/refresh", response_model=TokenPairResponse, summary="Rotate a refresh token")
async def refresh(payload: RefreshRequest, service: AuthServiceDependency) -> TokenPairResponse:
    return _token_response(await service.refresh(payload.refresh_token))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current refresh session",
)
async def logout(payload: LogoutRequest, service: AuthServiceDependency) -> Response:
    await service.logout(payload.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse, summary="Get the current user")
async def get_me(user: CurrentUserDependency) -> UserResponse:
    return UserResponse.model_validate(user)


def _auth_response(result: AuthResult) -> AuthResponse:
    return AuthResponse(
        user=UserResponse.model_validate(result.user),
        tokens=_token_response(result.tokens),
    )


def _token_response(tokens: TokenPair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )
