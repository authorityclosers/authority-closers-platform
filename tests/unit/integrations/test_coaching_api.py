"""Coaching by API, MCP and CLI (API, MCP and CLI gaps, 15 Nov 2026, gap 11), without a
database: the three tools need reports:read and nothing else; a person's own Coaching refuses an
organisation key; the team's refuses anyone who isn't an owner, admin or organisation key; and
each sx command calls its route. The reads are covered by
tests/database/test_integrations_coaching_postgresql.py."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.integrations import coaching_api, mcp_http
from ac_platform.integrations.api_http import ApiError

COACHING = {"my_coaching", "call_coaching", "team_coaching"}

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "sx_cli_coaching", ROOT / "apps/sales-xray-web/public/developers/sx.py"
)
assert _spec is not None and _spec.loader is not None
sx: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)


def test_coaching_tools_need_reports_read_only() -> None:
    def listed(granted: set[str]) -> set[str]:
        return {tool["name"] for tool in mcp_http.listed(frozenset(granted))} & COACHING

    assert listed({"reports:read"}) == COACHING
    for other in ("calls:read", "coaching:read", "coaching:write", "leads:read"):
        assert listed({other}) == set(), other


def reader(*granted: str, reach: str = "person", role: str | None = "member") -> Any:
    def require(scope: str) -> None:
        if scope not in granted:
            raise ApiError(403, "scope_missing", f"This key does not have {scope}.")

    return SimpleNamespace(
        caller=SimpleNamespace(reach=reach, role=role, personal_workspace=role is None),
        key=SimpleNamespace(tenant_id=uuid4(), acting_person_id=uuid4()),
        session=object(),  # never reached: these refusals come first
        require=require,
    )


def refusal(who: Any, name: str, args: dict[str, Any] | None = None) -> str:
    with pytest.raises(ApiError) as caught:
        asyncio.run(mcp_http.run_tool(who, name, args or {}))
    return caught.value.code


@pytest.mark.parametrize("name", sorted(COACHING))
def test_each_coaching_tool_needs_reports_read(name: str) -> None:
    args = {"call_id": str(uuid4())}
    assert refusal(reader("calls:read"), name, args) == "scope_missing"


def test_an_organisation_key_has_no_coaching_of_its_own() -> None:
    key = reader("reports:read", reach="organisation", role="owner")
    assert refusal(key, "my_coaching") == "person_only"
    assert refusal(key, "call_coaching", {"call_id": str(uuid4())}) == "person_only"


@pytest.mark.parametrize("role", ["member", "manager", "viewer", None])
def test_the_team_s_coaching_is_for_owners_admins_and_organisation_keys(role: str | None) -> None:
    assert refusal(reader("reports:read", role=role), "team_coaching") == "team_only"


def test_call_coaching_checks_its_call_id() -> None:
    assert refusal(reader("reports:read"), "call_coaching", {"call_id": "x"}) == "argument"


class Fake:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        self.seen.append(request.full_url.split("/v1/api", 1)[1])
        return 200, b'{"ok": true}'


@pytest.mark.parametrize(
    ("argv", "path"),
    [
        (["coaching"], "/coaching"),
        (["coaching", "--team"], "/coaching/team"),
        (["coaching", "--call", "c1"], "/coaching/calls/c1"),
    ],
)
def test_each_coaching_command_calls_its_route(argv: list[str], path: str) -> None:
    fake, out = Fake(), io.StringIO()
    env = {"SX_API_KEY": "sxa_" + "d" * 40, "SX_API_BASE": "https://x.example.test/v1/api"}
    with redirect_stdout(out):
        assert sx.main(argv, env, fake) == 0
    assert fake.seen == [path] and json.loads(out.getvalue()) == {"ok": True}


def test_coaching_names_stay_clear_of_the_ask_dipak_and_report_tools() -> None:
    names = [tool["name"] for tool in mcp_http.TOOLS]
    assert len(names) == len(set(names))
    assert set(names) >= coaching_api.NAMES
