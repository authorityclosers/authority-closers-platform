"""Call reports by API, MCP and CLI (API, MCP and CLI gaps, 15 Nov 2026, gap 5), without a
database: the three tools need reports:read and nothing else; who opens the team's reports is
the app's rule (owners, admins and organisation keys); tool arguments are checked before any
read; and each sx command calls its route. The reads themselves are covered by
tests/database/test_integrations_reports_postgresql.py."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.integrations import mcp_http, reports_api, scopes
from ac_platform.integrations.api_http import ApiError

REPORT_TOOLS = {"list_reports", "get_report", "get_transcript"}

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "sx_cli_reports", ROOT / "apps/sales-xray-web/public/developers/sx.py"
)
assert _spec is not None and _spec.loader is not None
sx: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)
KEY = "sxk_test_" + "c" * 40
BASE = "https://salesxray.example.test/v1/api"


def _reports_listed(granted: set[str]) -> set[str]:
    return {tool["name"] for tool in mcp_http.listed(frozenset(granted))} & REPORT_TOOLS


def test_report_tools_need_reports_read_and_add_no_scope() -> None:
    assert _reports_listed({"reports:read"}) == REPORT_TOOLS
    for other in ("calls:read", "leads:read", "coaching:read", "coaching:write"):
        assert _reports_listed({other}) == set(), other
    assert all(tool["scope"] == "reports:read" for tool in reports_api.TOOLS)
    assert "reports:read" in scopes.SCOPES  # a key can hold it, on every plan that reads


def caller(reach: str, role: str | None, personal: bool = False) -> Any:
    key = SimpleNamespace(tenant_id=uuid4(), acting_person_id=uuid4(), scopes=frozenset())
    return SimpleNamespace(
        caller=SimpleNamespace(reach=reach, role=role, personal_workspace=personal), key=key
    )


@pytest.mark.parametrize(
    ("reach", "role", "personal", "team"),
    [
        ("organisation", "owner", False, True),
        ("person", "owner", False, True),
        ("person", "admin", False, True),
        # They see the team's calls in the call list, but in the app open only their own
        # reports (organisation_call_reader is owners and admins).
        ("person", "manager", False, False),
        ("person", "viewer", False, False),
        ("person", "member", False, False),
        ("person", None, True, False),
    ],
)
def test_the_team_s_reports_are_for_owners_admins_and_organisation_keys(
    reach: str, role: str | None, personal: bool, team: bool
) -> None:
    assert reports_api._team(caller(reach, role, personal)) is team


def reader(*granted: str) -> Any:
    def require(scope: str) -> None:
        if scope not in granted:
            raise ApiError(403, "scope_missing", f"This key does not have {scope}.")

    found = caller("organisation", "owner")
    found.require = require
    found.session = object()  # never reached: these refusals come first
    return found


def refusal(name: str, args: dict[str, Any], *granted: str) -> ApiError:
    with pytest.raises(ApiError) as caught:
        asyncio.run(mcp_http.run_tool(reader(*granted), name, args))
    return caught.value


@pytest.mark.parametrize("name", sorted(REPORT_TOOLS - {"list_reports"}))
def test_a_report_tool_checks_its_call_id_and_its_scope(name: str) -> None:
    bad = refusal(name, {"call_id": "not-an-id"}, "reports:read")
    assert (bad.status, bad.code) == (422, "argument")
    missing = refusal(name, {"call_id": str(uuid4())}, "calls:read")
    assert (missing.status, missing.code) == (403, "scope_missing")


def test_list_reports_checks_its_arguments_and_its_scope() -> None:
    assert refusal("list_reports", {"saved": "yes"}, "reports:read").code == "argument"
    assert refusal("list_reports", {"before": "x"}, "reports:read").code == "argument"
    assert refusal("list_reports", {}, "calls:read").code == "scope_missing"


# ---------- sx ----------


class Fake:
    def __init__(self, status: int = 200, body: bytes = b'{"ok": true}') -> None:
        self.status, self.body, self.seen = status, body, []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        self.seen.append((request.get_method(), request.full_url.split("/v1/api", 1)[1]))
        return self.status, self.body


def run(argv: list[str], fake: Fake) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = sx.main(argv, {"SX_API_KEY": KEY, "SX_API_BASE": BASE}, fake)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.parametrize(
    ("argv", "path"),
    [
        (["reports"], "/reports"),
        (["reports", "--saved", "--before", "c0"], "/reports?saved=true&before=c0"),
        (["report", "c1"], "/calls/c1/report"),
        (["report", "c1", "--transcript"], "/calls/c1/transcript"),
    ],
)
def test_each_report_command_calls_its_route(argv: list[str], path: str) -> None:
    fake = Fake()
    code, out, _ = run(argv, fake)
    assert code == 0 and json.loads(out) == {"ok": True}
    assert fake.seen == [("GET", path)]


def test_report_docx_writes_the_word_file(tmp_path: Path) -> None:
    target = tmp_path / "call.docx"
    fake = Fake(body=b"PK\x03\x04word")
    code, out, _ = run(["report", "c1", "--docx", str(target)], fake)
    assert code == 0 and fake.seen == [("GET", "/calls/c1/report.docx")]
    assert target.read_bytes() == b"PK\x03\x04word"
    assert json.loads(out) == {"saved_to": str(target), "bytes": 8}


def test_a_refused_word_file_is_a_clear_error(tmp_path: Path) -> None:
    body = json.dumps({"error": {"code": "report_not_ready", "message": "Not yet."}}).encode()
    code, out, err = run(["report", "c1", "--docx", str(tmp_path / "x.docx")], Fake(404, body))
    assert code == 1 and out == ""
    assert json.loads(err)["error"] == {
        "status": 404,
        "code": "report_not_ready",
        "message": "Not yet.",
    }
    assert not (tmp_path / "x.docx").exists()


def test_the_stdio_mcp_server_reads_reports() -> None:
    fake = Fake(body=b'{"reports": []}')
    client = sx.Client(KEY, BASE, fake)
    answer = sx.handle(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_reports", "arguments": {"saved": True}},
        },
    )
    assert json.loads(answer["result"]["content"][0]["text"]) == {"reports": []}
    assert fake.seen == [("GET", "/reports?saved=true")]
