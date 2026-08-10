from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    status: Literal["up", "down"]
    latency_ms: float = Field(ge=0)


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checked_at: datetime
    components: dict[str, ComponentHealth]
