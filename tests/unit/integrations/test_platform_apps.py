"""Platform apps without a database: self-registration rules, first-party apps, the
MCP tool list and the discovery documents."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ac_platform.integrations import first_party, mcp_http, oauth, scopes
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.oauth_http import server_metadata

ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 10, 20, tzinfo=UTC)


class NoDatabase:
    def execute(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("refused metadata must never reach the database")


@pytest.mark.parametrize(
    ("metadata", "code"),
    [
        (None, "invalid_client_metadata"),
        ({"redirect_uris": ["https://a.example/cb"]}, "invalid_client_metadata"),
        ({"client_name": "Sales X-Ray", "redirect_uris": ["https://a.example/cb"]}, None),
        ({"client_name": "SalesXray tools", "redirect_uris": ["https://a.example/cb"]}, None),
        ({"client_name": "Authority Closers", "redirect_uris": ["https://a.example/cb"]}, None),
        (
            {
                "client_name": "Host",
                "redirect_uris": ["https://a.example/cb"],
                "token_endpoint_auth_method": "private_key_jwt",
            },
            None,
        ),
        (
            {
                "client_name": "Host",
                "redirect_uris": ["https://a.example/cb"],
                "grant_types": ["client_credentials"],
            },
            None,
        ),
        (
            {
                "client_name": "Host",
                "redirect_uris": ["https://a.example/cb"],
                "response_types": [],
            },
            None,
        ),
        ({"client_name": "Host", "redirect_uris": "https://a.example/cb"}, "invalid_redirect_uri"),
    ],
)
def test_self_registration_refuses_bad_or_borrowed_metadata(
    metadata: object, code: str | None
) -> None:
    with pytest.raises(IntegrationError) as refused:
        oauth.register_dynamic(NoDatabase(), metadata, now=NOW)
    assert refused.value.code == (code or "invalid_client_metadata")


def test_only_the_real_first_party_host_gets_the_checked_mark() -> None:
    pulse = first_party.verified(
        "Pulse",
        ["https://pulse-dev.estateautopilots.com/api/v0/sales-xray/callback"],
        "development",
    )
    assert pulse is not None and pulse.maker == "Estate Autopilots"
    assert first_party.verified("pulse", ["https://pulse.estateautopilots.com/cb"], "production")
    # The production app's address is not checked on dev, nor any other host or name.
    assert (
        first_party.verified("Pulse", ["https://pulse.estateautopilots.com/cb"], "development")
        is None
    )
    assert first_party.verified("Pulse", ["https://pulse.example.org/cb"], "production") is None
    assert (
        first_party.verified(
            "Pulse",
            ["https://pulse.estateautopilots.com/cb", "https://elsewhere.example/cb"],
            "production",
        )
        is None
    )
    assert (
        first_party.verified("Other", ["https://pulse.estateautopilots.com/cb"], "production")
        is None
    )
    assert first_party.verified("Pulse", [], "production") is None


def test_mcp_tools_follow_the_connection_scopes() -> None:
    every = {tool["name"] for tool in mcp_http.listed(frozenset(scopes.SCOPES))}
    assert every == {
        "whoami",
        "list_calls",
        "get_call",
        "call_facts",
        "list_leads",
        "get_lead",
        "add_lead",
    }
    reading = {tool["name"] for tool in mcp_http.listed(frozenset({"calls:read"}))}
    assert reading == {"whoami", "list_calls", "get_call"}
    for tool in mcp_http.listed(frozenset(scopes.SCOPES)):
        assert "scope" not in tool and tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is (tool["name"] != "add_lead")


def test_server_metadata_describes_connect() -> None:
    meta = server_metadata("https://salesxray.example.test")
    assert meta["issuer"] == "https://salesxray.example.test"
    assert meta["authorization_endpoint"] == "https://salesxray.example.test/connect"
    assert meta["registration_endpoint"] == "https://salesxray.example.test/v1/oauth/register"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["scopes_supported"] == list(scopes.SCOPES)


def test_the_web_discovery_documents_list_the_same_scopes() -> None:
    source = (ROOT / "apps/sales-xray-web/app/oauth-discovery.ts").read_text(encoding="utf-8")
    block = source.split("export const SCOPES = [", 1)[1].split("]", 1)[0]
    listed = [item.strip().strip('",') for item in block.split("\n") if item.strip()]
    assert listed == list(scopes.SCOPES)
