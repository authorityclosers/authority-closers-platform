"""Fictional catalogue regression: Facebook may paginate an account's Pages."""

import asyncio

import httpx

from ac_platform.lead_desk.connectors import meta


def test_pages_follows_cursors_without_following_external_next_urls() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/v23.0/me/accounts"
        if request.url.params.get("after") == "next-page":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "second", "name": "Sample Page Two", "access_token": "fictional-two"}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "first", "name": "Sample Page One", "access_token": "fictional-one"}
                ],
                "paging": {
                    "next": "https://unused.example.test/not-followed",
                    "cursors": {"after": "next-page"},
                },
            },
        )

    cfg = meta.MetaConfig("fictional", "fictional", "fictional", "fictional", b"k" * 32, "v23.0")

    async def run() -> list[dict[str, str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await meta.Graph(cfg, client).pages("fictional-user-token")

    assert [page["id"] for page in asyncio.run(run())] == ["first", "second"]
    assert len(seen) == 2
    assert all(request.url.host == "graph.facebook.com" for request in seen)


def test_organisation_return_is_signed_and_uses_a_fixed_native_destination() -> None:
    from urllib.parse import unquote
    from uuid import UUID

    from ac_platform.lead_desk.connectors import app_return

    who = UUID("00000000-0000-4000-8000-000000000001")
    state = meta.make_state("fictional", tenant_id=who, person_id=who, hub_sources=True)
    assert meta.read_state("fictional", state, tenant_id=who, person_id=who)["hs"] is True
    assert "hs" not in meta.peek_state(
        "fictional", meta.make_state("fictional", tenant_id=who, person_id=who)
    )
    page = bytes(app_return.return_page("meta", result="cancelled", hub_sources=True).body).decode()
    assert "organisation" in unquote(page)
    assert "tab=leads" in unquote(page)
    # Other providers keep their existing fixed path, even with the flag.
    assert (
        "organisation"
        not in bytes(
            app_return.return_page("google", result="cancelled", hub_sources=True).body
        ).decode()
    )
