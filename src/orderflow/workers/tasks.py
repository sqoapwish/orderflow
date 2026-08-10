from typing import Literal

from celery import shared_task


@shared_task(name="orderflow.health.ping")  # type: ignore[untyped-decorator]
def ping() -> dict[str, Literal["pong"]]:
    """A lightweight task used to verify worker registration."""
    return {"status": "pong"}
