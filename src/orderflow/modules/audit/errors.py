from fastapi import status

from orderflow.core.errors import ApplicationError


class AuditEventNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="audit_event_not_found",
            message="Audit event was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidAuditTimeRangeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_audit_time_range",
            message="Audit time range start must not be after its end",
        )
