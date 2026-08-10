from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request, Response, status

from orderflow import __version__
from orderflow.core.config import Settings
from orderflow.infrastructure.health import ReadinessChecker
from orderflow.schemas.health import LivenessResponse, ReadinessResponse

router = APIRouter()


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def liveness(request: Request) -> LivenessResponse:
    settings = cast(Settings, request.app.state.settings)
    return LivenessResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
    summary="Readiness probe",
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    checker = cast(ReadinessChecker, request.app.state.readiness_checker)
    components = await checker.check()
    is_ready = all(component.status == "up" for component in components.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        checked_at=datetime.now(UTC),
        components=components,
    )
