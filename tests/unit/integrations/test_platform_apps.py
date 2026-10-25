"""Platform apps without a database: self-registration rules, first-party apps, the
MCP tool list and the discovery documents."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ac_platform.integrations import first_party, mcp_http, oauth, scopes
from ac_platform.integrations.api_http import ApiError
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.oauth_http import (
    MCP_SCOPES,
    protected_resource_metadata,
    server_metadata,
)

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
    # A company's own address under the shared Pulse (Authority Closers, 23 Oct 2026).
    assert first_party.verified(
        "Pulse", ["https://pulse.authorityclosers.com/apps/sales-xray/callback"], "production"
    )
    assert (
        first_party.verified("Pulse", ["https://pulse.authorityclosers.com/cb"], "development")
        is None
    )
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


@pytest.mark.parametrize(
    ("uri", "allowed"),
    [
        ("https://pulse.example.test/apps/sales-xray/callback", True),
        ("http://127.0.0.1:8765/callback", True),
        ("http://localhost/callback", True),
        # A Pulse company's local rehearsal address (RFC 6761: *.localhost is loopback).
        ("http://ac-rehearsal.localhost:3203/apps/sales-xray/callback", True),
        ("http://pulse.example.test/callback", False),
        ("http://localhost.example.test/callback", False),
        ("https://user@pulse.example.test/callback", False),
        ("https://pulse.example.test/callback#part", False),
    ],
)
def test_return_addresses_are_https_or_this_computer(uri: str, allowed: bool) -> None:
    assert oauth.redirect_allowed(uri) is allowed


def test_mcp_tools_follow_the_connection_scopes() -> None:
    every = {tool["name"] for tool in mcp_http.listed(frozenset(scopes.SCOPES))}
    assert every == {
        "search",
        "fetch",
        "whoami",
        "list_calls",
        "get_call",
        "call_facts",
        "list_leads",
        "get_lead",
        "list_duplicates",
        "get_duplicate",
        "add_lead",
        "add_note",
        "add_task",
        "list_my_changes",
        "undo_change",
    }
    reading = {tool["name"] for tool in mcp_http.listed(frozenset({"calls:read"}))}
    assert reading == {"search", "fetch", "whoami", "list_calls", "get_call"}
    leads = {tool["name"] for tool in mcp_http.listed(frozenset({"leads:read"}))}
    assert leads == {
        "search",
        "fetch",
        "whoami",
        "list_leads",
        "get_lead",
        "list_duplicates",
        "get_duplicate",
    }
    assert {tool["name"] for tool in mcp_http.listed(frozenset({"webhooks:manage"}))} == {"whoami"}
    # AI writes (docs/product/ai-writes.md): each write tool needs its own scope; reading
    # leads alone shows none of them.
    notes = {tool["name"] for tool in mcp_http.listed(frozenset({"leads:notes"}))}
    assert notes == {"whoami", "add_note", "list_my_changes", "undo_change"}
    tasks = {tool["name"] for tool in mcp_http.listed(frozenset({"leads:tasks"}))}
    assert tasks == {"whoami", "add_task", "list_my_changes", "undo_change"}
    writes = {"add_lead", "add_note", "add_task", "undo_change"}
    for tool in mcp_http.listed(frozenset(scopes.SCOPES)):
        assert "scope" not in tool and tool["inputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is (tool["name"] not in writes)
        # The directories ask for every hint, true or false, never left out. Only undo
        # takes something away (a note stops showing).
        assert tool["annotations"]["destructiveHint"] is (tool["name"] == "undo_change")
        assert tool["annotations"]["openWorldHint"] is False
        if tool["name"] in writes - {"add_lead"}:
            assert tool["annotations"]["idempotentHint"] is True
            assert "request_id" in tool["inputSchema"]["properties"]
        assert tool["title"]
        # The Claude directory's tool check wants the title inside the annotations too.
        assert tool["annotations"]["title"] == tool["title"]
    # Listing never changes the shared definitions.
    assert all("title" not in tool["annotations"] for tool in mcp_http.TOOLS)


BASE = "https://salesxray.example.test"
CALL = "11111111-1111-4111-8111-111111111111"
UNTITLED = "22222222-2222-4222-8222-222222222222"
LEAD = "33333333-3333-4333-8333-333333333333"


class FakeReader:
    """Answers like ``Reader`` for one person's fictional calls and leads."""

    base = BASE

    def __init__(self, granted: set[str], *, personal: bool = False) -> None:
        self.key = SimpleNamespace(scopes=frozenset(granted))
        self.personal = personal
        self.searched: list[str | None] = []

    def _call(self, call_id: str, title: str | None, day: str) -> dict[str, Any]:
        return {
            "id": call_id,
            "title": title,
            "created_at": f"2026-10-{day}T10:00:00+00:00",
            "duration_seconds": 600,
            "has_report": title is not None,
            "open_url": f"{BASE}/analysis/calls/{call_id}",
        }

    async def calls(self, before: object) -> dict[str, Any]:
        calls = [
            self._call(CALL, "Discovery with Fictional Traders", "20"),
            self._call(UNTITLED, None, "21"),
        ]
        return {"calls": calls, "next_before": None}

    async def call(self, call_id: object) -> dict[str, Any]:
        if str(call_id) != CALL:
            raise ApiError(404, "call_missing", "That call is not here, or not yours to read.")
        return {
            **self._call(CALL, "Discovery with Fictional Traders", "20"),
            "facts": [{"key": "budget"}],
        }

    async def leads(
        self, stage: object, offset: int, limit: int, search: str | None = None
    ) -> dict[str, Any]:
        if self.personal:
            raise ApiError(
                403, "organisation_only", "Leads are kept in organisations, not Personal."
            )
        self.searched.append(search)
        row = {
            "lead_id": LEAD,
            "name": "Asha Fictional",
            "company": "Fictional Traders",
            "stage_label": "New",
        }
        found = search is not None and search.casefold() in "asha fictional fictional traders"
        return {"leads": [row] if found else [], "total": int(found), "next_offset": None}

    async def lead(self, lead_id: object) -> dict[str, Any]:
        row = {"lead_id": LEAD, "name": "Asha Fictional", "stage_label": "New"}
        return {"lead": row, "phone": "+910000000000", "email": None, "fields": [], "events": []}


async def _tool(reader: FakeReader, name: str, args: dict[str, Any]) -> dict[str, Any]:
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    answer = await mcp_http.handle(cast(Any, reader), message)
    assert answer is not None
    result: dict[str, Any] = answer["result"]
    if not result["isError"]:
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result


async def test_search_finds_calls_and_leads_in_chatgpts_shape() -> None:
    reader = FakeReader({"calls:read", "leads:read", "reports:read"})
    found = (await _tool(reader, "search", {"query": "fictional"}))["structuredContent"]
    assert found == {
        "results": [
            {
                "id": f"call:{CALL}",
                "title": "Discovery with Fictional Traders",
                "url": f"{BASE}/analysis/calls/{CALL}",
            },
            {
                "id": f"lead:{LEAD}",
                "title": "Asha Fictional · Fictional Traders · New",
                "url": f"{BASE}/leads?lead={LEAD}",
            },
        ]
    }
    # An untitled call is found by its date; a question falls back to its longest word.
    dated = (await _tool(reader, "search", {"query": "2026-10-21"}))["structuredContent"]
    assert dated["results"][0] == {
        "id": f"call:{UNTITLED}",
        "title": "Call on 2026-10-21",
        "url": f"{BASE}/analysis/calls/{UNTITLED}",
    }
    reader.searched.clear()
    asked = await _tool(reader, "search", {"query": "who is Asha"})
    assert reader.searched == ["who is Asha", "Asha"]
    assert [item["id"] for item in asked["structuredContent"]["results"]] == [f"lead:{LEAD}"]


async def test_search_keeps_to_the_connection_and_personal_has_no_leads() -> None:
    calls_only = FakeReader({"calls:read"})
    found = (await _tool(calls_only, "search", {"query": "fictional"}))["structuredContent"]
    assert [item["id"] for item in found["results"]] == [f"call:{CALL}"]
    assert calls_only.searched == []
    personal = FakeReader({"calls:read", "leads:read"}, personal=True)
    found = (await _tool(personal, "search", {"query": "fictional"}))["structuredContent"]
    assert [item["id"] for item in found["results"]] == [f"call:{CALL}"]
    for reader, args in (
        (FakeReader({"webhooks:manage"}), {"query": "fictional"}),
        (calls_only, {"query": ""}),
        (calls_only, {"query": "x" * 201}),
    ):
        assert (await _tool(reader, "search", args))["isError"] is True


async def test_fetch_reads_one_search_result() -> None:
    reader = FakeReader({"calls:read", "leads:read", "reports:read"})
    call = (await _tool(reader, "fetch", {"id": f"call:{CALL}"}))["structuredContent"]
    assert set(call) == {"id", "title", "text", "url", "metadata"}
    assert call["id"] == f"call:{CALL}" and call["url"] == f"{BASE}/analysis/calls/{CALL}"
    assert json.loads(call["text"])["facts"] == [{"key": "budget"}]
    assert call["metadata"] == {"kind": "call", "report_ready": True}
    lead = (await _tool(reader, "fetch", {"id": f"lead:{LEAD}"}))["structuredContent"]
    assert lead["title"] == "Asha Fictional" and lead["url"] == f"{BASE}/leads?lead={LEAD}"
    assert json.loads(lead["text"])["phone"] == "+910000000000"
    assert lead["metadata"] == {"kind": "lead", "stage": "New"}
    for wrong in (f"note:{CALL}", "call:nope", CALL, f"call:{UNTITLED}"):
        assert (await _tool(reader, "fetch", {"id": wrong}))["isError"] is True


def test_server_metadata_describes_connect() -> None:
    meta = server_metadata("https://salesxray.example.test")
    assert meta["issuer"] == "https://salesxray.example.test"
    assert meta["authorization_endpoint"] == "https://salesxray.example.test/connect"
    assert meta["registration_endpoint"] == "https://salesxray.example.test/v1/oauth/register"
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["scopes_supported"] == list(scopes.SCOPES)


def test_protected_resource_metadata_names_connect_and_the_tools_scopes() -> None:
    base = "https://salesxray.example.test"
    for path in ("", "v1/mcp", "/v1/mcp/"):
        meta = protected_resource_metadata(base, path)
        assert meta is not None and meta["resource"] == f"{base}/v1/mcp"
        assert meta["authorization_servers"] == [base]
        assert meta["scopes_supported"] == list(MCP_SCOPES)
    assert protected_resource_metadata(base, "v1/api")["resource"] == f"{base}/v1/api"  # type: ignore[index]
    assert protected_resource_metadata(base, "v1/admin") is None
    assert set(MCP_SCOPES) <= set(scopes.SCOPES) and "webhooks:manage" not in MCP_SCOPES


def _ts_list(source: str, name: str) -> list[str]:
    block = source.split(f"export const {name} = [", 1)[1].split("]", 1)[0]
    return [item.strip().strip('",') for item in block.split("\n") if item.strip()]


def test_the_web_discovery_documents_list_the_same_scopes() -> None:
    source = (ROOT / "apps/sales-xray-web/app/oauth-discovery.ts").read_text(encoding="utf-8")
    assert _ts_list(source, "SCOPES") == list(scopes.SCOPES)
    assert _ts_list(source, "MCP_SCOPES") == list(MCP_SCOPES)
