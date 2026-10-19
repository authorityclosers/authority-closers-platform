"""ac-admin.py, downloaded from Admin: the settings command line and MCP server.

Against the real registry manifest and a recording fake transport (no network).
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from ac_platform.admin_settings.registry import manifest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "ac_admin_cli", ROOT / "apps/admin-web/public/tools/ac-admin.py"
)
assert _spec is not None and _spec.loader is not None
cli: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

KEY = "ac_dev_" + "k" * 43
EXECUTION = {"control": {"paused": False, "revision": 3, "changed_at": None}}
BUDGET = {"revision": 9, "approved_cap_paise": 5_000_000, "budget": {"cap_paise": 3_000_000}}
CALL_DATA = {
    "revision": 7,
    "config": {
        "fast": {"enabled": True, "model": "m-fast", "daily_cap_inr": 150, "max_call_minutes": 60},
        "deep": {"enabled": True, "model": "m-fast", "daily_cap_inr": 300, "max_call_minutes": 60},
        "streaming": {"provider": "", "model": ""},
    },
    "models": [{"model": "m-fast", "label": "Fast"}, {"model": "m-pro", "label": "Pro"}],
}


class Fake:
    """Answers (method, path) from a table and records every request."""

    def __init__(self, answers: dict[tuple[str, str], tuple[int, Any]]) -> None:
        self.answers, self.seen = answers, []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        path = request.full_url.split("://", 1)[1].split("/", 1)[1]
        method = request.get_method()
        body = json.loads(request.data) if request.data else None  # type: ignore[arg-type]
        self.seen.append((method, "/" + path, dict(request.header_items()), body))
        status, payload = self.answers.get((method, "/" + path), (404, {"detail": "Not here"}))
        return status, json.dumps(payload).encode()


def _fake(**extra: tuple[int, Any]) -> Fake:
    answers = {
        ("GET", "/v1/admin/settings"): (200, manifest()),
        ("GET", "/v1/admin/conversation/execution"): (200, EXECUTION),
        ("GET", "/v1/admin/conversation/budget"): (200, BUDGET),
        ("GET", "/v1/admin/call-data"): (200, CALL_DATA),
        ("POST", "/v1/admin/conversation/execution"): (200, {"control": {"paused": True}}),
        ("POST", "/v1/admin/conversation/budget"): (201, {"ok": True}),
        ("PUT", "/v1/admin/call-data/settings"): (200, {"revision": 8}),
    }
    answers.update({tuple(key.split(" ", 1)): value for key, value in extra.items()})  # type: ignore[misc]
    return Fake(answers)


def _run(
    argv: list[str], fake: Fake, environ: dict[str, str] | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        argv,
        environ={"AC_ADMIN_KEY": KEY, "AC_ADMIN_BASE": "https://admin.example"}
        if environ is None
        else environ,
        transport=fake,
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def test_get_reads_the_value_its_options_and_bounds() -> None:
    fake = _fake()
    code, out, _ = _run(["settings", "get", "budget.cap_paise"], fake)
    assert code == 0
    shown = json.loads(out)
    assert (shown["value"], shown["revision"], shown["maximum"]) == (3_000_000, 9, 5_000_000)
    model = json.loads(_run(["settings", "get", "call_data.fast.model"], fake)[1])
    assert model["options"] == ["m-fast", "m-pro"]
    # The key goes only in the Authorization header.
    assert all(headers.get("Authorization") == f"Bearer {KEY}" for _, _, headers, _ in fake.seen)


def test_set_sends_the_areas_own_body_with_revision_merge_and_reason() -> None:
    fake = _fake()
    assert _run(["settings", "set", "execution.paused", "paused"], fake)[0] == 0
    method, path, headers, body = fake.seen[-1]
    assert (method, path, body) == (
        "POST",
        "/v1/admin/conversation/execution",
        {"expected_revision": 3, "paused": True},
    )
    assert headers.get("Idempotency-key")

    assert _run(["settings", "set", "call_data.deep.daily_cap_inr", "450"], fake)[0] == 0
    method, path, headers, body = fake.seen[-1]
    assert (method, path) == ("PUT", "/v1/admin/call-data/settings")
    assert "Idempotency-key" not in headers
    assert body["expected_revision"] == 7
    assert body["config"]["deep"]["daily_cap_inr"] == 450
    assert body["config"]["fast"] == CALL_DATA["config"]["fast"]

    code, _, err = _run(["settings", "set", "budget.cap_paise", "40000"], fake)
    assert code == 2 and "--reason" in err
    assert (
        _run(["settings", "set", "budget.cap_paise", "40000", "--reason", "More calls"], fake)[0]
        == 0
    )
    assert fake.seen[-1][3] == {
        "expected_revision": 9,
        "new_cap_paise": 4_000_000,
        "reason": "More calls",
    }


def test_bad_values_and_page_only_settings_are_refused_before_any_change() -> None:
    fake = _fake()
    for argv, says in (
        (["settings", "set", "call_data.fast.model", "m-huge"], "Choose one of"),
        (["settings", "set", "call_data.fast.daily_cap_inr", "6000"], "Between 0 and 5000"),
        (["settings", "set", "budget.cap_paise", "60000", "--reason", "x"], "Between 0 and 50000"),
        (["settings", "set", "budget.ceiling_paise", "1"], "owner"),
        (["settings", "set", "nope", "1"], "No setting"),
    ):
        code, _, err = _run(argv, fake)
        assert code == 2 and says in err, (argv, err)
    assert not [seen for seen in fake.seen if seen[0] != "GET"]


def test_admin_refusals_are_shown_and_never_carry_the_key() -> None:
    fake = _fake(
        **{
            "POST /v1/admin/conversation/execution": (
                403,
                {"detail": "This key does not hold settings:write."},
            )
        }
    )
    code, out, err = _run(["settings", "set", "execution.paused", "true"], fake)
    assert code == 1 and "settings:write" in err
    assert KEY not in out + err


def test_the_key_never_comes_from_an_argument_and_must_be_set() -> None:
    fake = _fake()
    code, _, err = _run(["settings", "get", KEY], fake)
    assert code == 2 and "Never pass the key" in err and KEY not in err
    assert fake.seen == []
    code, _, err = _run(["settings", "list"], fake, environ={})
    assert code == 2 and "AC_ADMIN_KEY" in err
    code, _, err = _run(
        ["settings", "list"], fake, environ={"AC_ADMIN_KEY": KEY, "AC_ADMIN_BASE": "http://evil"}
    )
    assert code == 2 and "https" in err


def test_list_shows_every_setting_and_whether_it_changes_here() -> None:
    code, out, _ = _run(["settings", "list"], _fake())
    rows = {row["id"]: row for row in json.loads(out)}
    assert code == 0
    assert rows["execution.paused"]["value"] is False
    assert rows["budget.ceiling_paise"]["changes_here"] is False
    assert rows["call_data.fast.enabled"]["changes_here"] is True
    # A read Admin refused shows no value rather than failing the list.
    assert rows["analysis.report_detail"]["value"] is None


def test_mcp_lists_tools_and_changes_a_setting() -> None:
    client = cli.Client(KEY, "https://admin.example", _fake())
    assert (
        cli.handle(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"][
            "serverInfo"
        ]["name"]
        == "ac-admin"
    )
    tools = cli.handle(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [tool["name"] for tool in tools["result"]["tools"]] == [
        "list_settings",
        "get_setting",
        "set_setting",
    ]
    changed = cli.handle(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "set_setting",
                "arguments": {"id": "execution.paused", "value": "false"},
            },
        },
    )
    assert "isError" not in changed["result"]
    refused = cli.handle(
        client,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "set_setting",
                "arguments": {"id": "budget.ceiling_paise", "value": "1"},
            },
        },
    )
    assert refused["result"]["isError"] is True
    stream = io.StringIO()
    cli.serve(client, io.StringIO('{"jsonrpc":"2.0","id":5,"method":"ping"}\nnot json\n'), stream)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[0]["result"] == {} and lines[1]["error"]["code"] == -32700
    assert cli.handle(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    with pytest.raises(cli.UsageError):
        cli.Client("sxk_live_x", "https://admin.example", _fake())
