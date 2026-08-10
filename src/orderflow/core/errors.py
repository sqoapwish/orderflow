from dataclasses import dataclass

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from orderflow.core.correlation import get_correlation_id
from orderflow.schemas.errors import ErrorBody, ErrorResponse


@dataclass(slots=True)
class ApplicationError(Exception):
    code: str
    message: str
    status_code: int = status.HTTP_400_BAD_REQUEST


def _error_response(*, code: str, message: str, status_code: int) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            correlation_id=get_correlation_id(),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
    return _error_response(code=exc.code, message=exc.message, status_code=exc.status_code)


async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return _error_response(
        code="validation_error",
        message="Request data failed validation",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed"
    return _error_response(
        code="http_error",
        message=message,
        status_code=exc.status_code,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
