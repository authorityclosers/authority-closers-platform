from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from ac_platform.http.app import app
from ac_platform.kernel.errors import AuthorizationDenied


@app.get("/_test/domain-error", include_in_schema=False)
async def raise_domain_error() -> None:
    raise AuthorizationDenied("A bounded denial.")


async def test_domain_error_is_rfc7807_shaped_and_correlated() -> None:
    transport = ASGITransport(app=app)
    request_id = str(uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/_test/domain-error",
            headers={"x-request-id": request_id},
        )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "authorization_denied"
    assert response.json()["request_id"] == request_id


async def test_untrusted_request_id_is_replaced() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live", headers={"x-request-id": "bad id value"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id value"
