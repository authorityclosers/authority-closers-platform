from httpx import ASGITransport, AsyncClient

from ac_platform.http.app import app


async def test_api_emits_baseline_security_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_cors_allows_only_configured_origin_and_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.options(
            "/health/live",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-request-id",
            },
        )
        denied = await client.options(
            "/health/live",
            headers={
                "origin": "https://attacker.example",
                "access-control-request-method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


async def test_untrusted_host_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://evil.example") as client:
        response = await client.get("/health/live")

    assert response.status_code == 400
