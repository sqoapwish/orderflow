from uuid import UUID

from httpx import AsyncClient

from orderflow.core.correlation import CORRELATION_ID_HEADER


async def test_supplied_correlation_id_is_returned(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health/live",
        headers={CORRELATION_ID_HEADER: "order-checkout-42"},
    )

    assert response.headers[CORRELATION_ID_HEADER] == "order-checkout-42"


async def test_invalid_correlation_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health/live",
        headers={CORRELATION_ID_HEADER: "invalid id with spaces"},
    )

    generated_id = response.headers[CORRELATION_ID_HEADER]
    assert generated_id != "invalid id with spaces"
    assert str(UUID(generated_id)) == generated_id


async def test_not_found_uses_standard_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "http_error"
    assert body["error"]["correlation_id"] == response.headers[CORRELATION_ID_HEADER]
