from httpx import ASGITransport, AsyncClient

from ac_platform.http.app import app


async def test_liveness_returns_release_identity() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live", headers={"x-request-id": "test-request"})

    assert response.status_code == 200
    assert response.json()["status"] == "alive"
    assert response.headers["x-request-id"] == "test-request"
    assert response.headers["x-ac-release-id"]
