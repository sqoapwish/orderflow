from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    correlation_id: str | None


class ErrorResponse(BaseModel):
    error: ErrorBody
