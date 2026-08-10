import re
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from uuid import uuid4

import structlog
from fastapi import Request, Response

CORRELATION_ID_HEADER = "X-Correlation-ID"
_VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _resolve_correlation_id(raw_value: str | None) -> str:
    if raw_value and _VALID_CORRELATION_ID.fullmatch(raw_value):
        return raw_value
    return str(uuid4())


async def correlation_id_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = _resolve_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
    token = _correlation_id.set(correlation_id)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    try:
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
    finally:
        structlog.contextvars.clear_contextvars()
        _correlation_id.reset(token)
