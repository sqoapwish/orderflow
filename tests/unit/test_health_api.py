from httpx import AsyncClient

from orderflow import __version__


async def test_liveness_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "OrderFlow API",
        "version": __version__,
    }


async def test_readiness_endpoint_when_all_components_are_up(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["components"]) == {"postgresql", "redis", "rabbitmq"}
    assert all(component["status"] == "up" for component in body["components"].values())
