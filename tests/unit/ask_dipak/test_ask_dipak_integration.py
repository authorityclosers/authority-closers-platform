"""Ask Dipak over API keys, connected apps and MCP (the orchestrator, 14 Nov 2026): lessons need
no scope; coaching:read shows a person's missions and calls, and the team's to organisation
keys and team roles; coaching:write is a person's connected app's, never an organisation key's.
Each scope is checked on its own, with a stand-in reader (the database paths are covered by
tests/database/test_sales_xray_ask_dipak_coaching_postgresql.py)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.ask_dipak import coaching, integration, library, team
from ac_platform.integrations import mcp_http, scopes
from ac_platform.integrations.api_http import ApiError

LESSONS = {"ask_dipak_search", "ask_dipak_lesson", "ask_dipak_how_to_improve"}
READS = {"ask_dipak_my_missions", "ask_dipak_recent_calls", "ask_dipak_team_missions"}
WRITES = {
    "ask_dipak_save_lesson",
    "ask_dipak_tick_mission",
    "ask_dipak_set_active",
    "ask_dipak_answer_call",
}


def _ask_dipak(granted: set[str]) -> set[str]:
    return {
        tool["name"]
        for tool in mcp_http.listed(frozenset(granted))
        if tool["name"].startswith("ask_dipak_")
    }


def reader(*granted: str, reach: str = "person", role: str | None = "member") -> Any:
    def require(scope: str) -> None:
        if scope not in granted:
            raise ApiError(403, "scope_missing", f"This key does not have {scope}.")

    caller = SimpleNamespace(
        reach=reach,
        role=role,
        personal_workspace=False,
        sees_team=reach == "organisation" or role in {"owner", "admin", "manager", "viewer"},
    )
    key = SimpleNamespace(tenant_id=uuid4(), acting_person_id=uuid4(), scopes=frozenset(granted))
    return SimpleNamespace(caller=caller, key=key, session=object(), require=require)


async def refused(call: Any) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await call
    return caught.value


def test_the_coaching_scopes_mirror_the_call_scopes() -> None:
    assert "coaching:read" in scopes.SCOPES and "coaching:read" not in scopes.APP_SCOPES
    assert "coaching:write" in scopes.APP_SCOPES and "coaching:write" not in scopes.SCOPES
    with pytest.raises(scopes.ScopeError):
        scopes.validate(["coaching:write"])
    assert scopes.validate(["coaching:write", "coaching:read"], app=True) == [
        "coaching:read",
        "coaching:write",
    ]


def test_lessons_need_no_scope() -> None:
    assert _ask_dipak(set()) == LESSONS
    assert _ask_dipak({"calls:read"}) == LESSONS


def test_coaching_read_shows_the_reads_and_no_write() -> None:
    assert _ask_dipak({"coaching:read"}) == LESSONS | READS


def test_coaching_write_shows_the_writes() -> None:
    assert _ask_dipak({"coaching:write"}) == LESSONS | WRITES
    assert _ask_dipak({"coaching:read", "coaching:write"}) == LESSONS | READS | WRITES


def test_every_tool_says_what_it_does_to_the_directories() -> None:
    for tool in integration.TOOLS:
        hints = tool["annotations"]
        assert hints["readOnlyHint"] is (tool["name"] not in WRITES)
        assert hints["destructiveHint"] is False and hints["openWorldHint"] is False
        assert tool["inputSchema"]["type"] == "object" and tool["title"]
        assert tool["scope"] == (
            None
            if tool["name"] in LESSONS
            else "coaching:read"
            if tool["name"] in READS
            else "coaching:write"
        )
    assert integration.NAMES == LESSONS | READS | WRITES


async def test_lessons_read_dipaks_words_with_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The served library is the newest import (database paths: tests/database); here, the
    # bundled one.
    seen: list[Any] = []

    async def served(session: Any) -> library.Served:
        seen.append(session)
        return library.bundled()

    monkeypatch.setattr(library, "served", served)
    anyone = reader()
    found = await integration.run_tool(anyone, "ask_dipak_search", {"query": "mahanga"})
    assert found["questions"][0]["id"] == "PB03"
    lesson = await integration.run_tool(anyone, "ask_dipak_lesson", {"question_id": "PB03"})
    assert lesson["lesson"]["quick_answer"].startswith("Buyer बोले “Price बहुत ज्यादा है,”")
    # A former draft is now Dipak's own lesson, served like the rest.
    former = await integration.run_tool(anyone, "ask_dipak_lesson", {"question_id": "PB05"})
    assert former["lesson"]["lesson_ready"] is True
    assert former["lesson"]["next_call_mission"].startswith("अगली तीन price objections में")
    missing = await refused(
        integration.run_tool(anyone, "ask_dipak_lesson", {"question_id": "ZZ99"})
    )
    assert missing.status == 404
    assert seen == [anyone.session, anyone.session]
    improve = await integration.run_tool(
        anyone, "ask_dipak_how_to_improve", {"skills": ["closing_decision_management"]}
    )
    assert improve["questions"][0]["id"] == "NX02"


async def test_reads_need_coaching_read_and_a_person(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def my_growth(db: Any, *, person_id: Any, tenant_id: Any = None) -> dict[str, Any]:
        seen["person"] = person_id
        return {"active": []}

    monkeypatch.setattr(coaching, "my_growth", my_growth)
    without = await refused(integration.run_tool(reader(), "ask_dipak_my_missions", {}))
    assert (without.status, without.code) == (403, "scope_missing")
    organisation = await refused(
        integration.run_tool(
            reader("coaching:read", reach="organisation", role=None), "ask_dipak_my_missions", {}
        )
    )
    assert organisation.code == "person_only"
    seller = reader("coaching:read")
    assert await integration.run_tool(seller, "ask_dipak_my_missions", {}) == {"active": []}
    assert seen["person"] == seller.key.acting_person_id


async def test_the_team_read_is_for_organisation_keys_and_team_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def workspace_counts(db: Any, *, tenant_id: Any) -> dict[str, Any]:
        return {"people": [], "tenant": tenant_id}

    monkeypatch.setattr(team, "workspace_counts", workspace_counts)
    member = await refused(
        integration.run_tool(reader("coaching:read"), "ask_dipak_team_missions", {})
    )
    assert member.code == "team_only"
    for allowed in (
        reader("coaching:read", reach="organisation", role=None),
        reader("coaching:read", role="manager"),
    ):
        read = await integration.run_tool(allowed, "ask_dipak_team_missions", {})
        assert read["tenant"] == allowed.key.tenant_id


async def test_writes_need_coaching_write_and_never_an_organisation_key() -> None:
    plain = await refused(
        integration.run_tool(
            reader("coaching:read"), "ask_dipak_set_active", {"question_id": "PB03", "active": True}
        )
    )
    assert plain.code == "scope_missing"
    organisation = await refused(
        integration.run_tool(
            reader("coaching:write", reach="organisation", role=None),
            "ask_dipak_save_lesson",
            {"question_id": "PB03", "saved": True},
        )
    )
    assert organisation.code == "person_only"
    loose = await refused(
        integration.run_tool(
            reader("coaching:write"), "ask_dipak_tick_mission", {"question_id": "PB03"}
        )
    )
    assert (loose.status, loose.code) == (422, "argument")
    bad = await refused(
        integration.run_tool(
            reader("coaching:write"),
            "ask_dipak_answer_call",
            {"call_id": "not-a-call", "answers": [{"question_id": "PB03", "done": True}]},
        )
    )
    assert bad.code == "argument"
