from orderflow.core.errors import ApplicationError


class InvalidAnalyticsPeriodError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_analytics_period",
            message="Analytics period start must not be after its end",
        )


class AnalyticsPeriodTooLargeError(ApplicationError):
    def __init__(self, maximum_days: int) -> None:
        super().__init__(
            code="analytics_period_too_large",
            message=f"Analytics period must not exceed {maximum_days} days",
        )
