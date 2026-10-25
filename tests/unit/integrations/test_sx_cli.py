"""sx.py, served at /developers/sx.py: the command line and MCP server (no network)."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "sx_cli", ROOT / "apps/sales-xray-web/public/developers/sx.py"
)
assert _spec is not None and _spec.loader is not None
sx: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)

KEY = "sxk_test_" + "a" * 40


class Fake:
    """Records each request and answers from a table of (method, path) -> (status, body)."""

    def __init__(self, answers: dict[tuple[str, str], tuple[int, Any]]) -> None:
        self.answers, self.seen = answers, []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        url = request.full_url
        path = url.split("/v1/api", 1)[1].split("?", 1)[0]
        self.seen.append((request.get_method(), url, request.headers, request.data))
        status, body = self.answers.get((request.get_method(), path), (404, {}))
        return status, json.dumps(body).encode()


def client(fake: Fake) -> Any:
    return sx.Client(KEY, "https://salesxray.example.test/v1/api", fake)


def test_the_client_sends_the_key_and_only_the_given_fields() -> None:
    fake = Fake({("GET", "/calls"): (200, {"calls": []}), ("POST", "/leads"): (201, {"id": "l1"})})
    api = client(fake)
    assert api.calls(before="c9") == {"calls": []}
    method, url, headers, _ = fake.seen[0]
    assert (method, url) == ("GET", "https://salesxray.example.test/v1/api/calls?before=c9")
    assert headers["Authorization"] == f"Bearer {KEY}"
    assert api.add_lead(name="Asha", phone=None, email="") == {"id": "l1"}
    assert json.loads(fake.seen[1][3]) == {"name": "Asha"}
    with pytest.raises(ValueError):
        sx.Client("not-a-key")
    with pytest.raises(ValueError):
        sx.Client(KEY, "http://salesxray.example.test/v1/api")


def test_api_refusals_become_clear_errors() -> None:
    fake = Fake({("GET", "/me"): (403, {"error": {"code": "scope_missing", "message": "No."}})})
    with pytest.raises(sx.ApiError) as raised:
        client(fake).me()
    assert (raised.value.status, raised.value.code) == (403, "scope_missing")


def test_the_command_line_prints_json_and_exits_by_outcome(capsys: pytest.CaptureFixture) -> None:
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    fake = Fake({("GET", "/me"): (200, {"organisation": {"id": "t1"}})})
    assert sx.main(["me"], env, fake) == 0
    assert json.loads(capsys.readouterr().out) == {"organisation": {"id": "t1"}}
    refused = Fake({("GET", "/leads"): (401, {"error": {"code": "key_invalid", "message": "x"}})})
    assert sx.main(["leads", "--stage", "open"], env, refused) == 1
    assert "key_invalid" in capsys.readouterr().err
    assert refused.seen[0][1].endswith("/leads?stage=open")
    assert sx.main(["me"], {}, fake) == 2  # no key


def test_the_mcp_server_lists_and_calls_tools() -> None:
    fake = Fake(
        {
            ("GET", "/calls/c1/facts"): (200, {"facts": [{"type": "need.primary_pain"}]}),
            ("POST", "/leads"): (403, {"error": {"code": "scope_missing", "message": "No."}}),
        }
    )
    api = client(fake)
    started = sx.handle(api, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert started["result"]["serverInfo"]["name"] == "sales-xray"
    assert sx.handle(api, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {
        t["name"] for t in sx.handle(api, {"id": 2, "method": "tools/list"})["result"]["tools"]
    }
    assert names == {
        "whoami",
        "list_calls",
        "call_facts",
        "list_leads",
        "get_lead",
        "add_lead",
        "add_note",
        "add_task",
        "list_my_changes",
        "undo_change",
    }
    facts = sx.handle(
        api,
        {
            "id": 3,
            "method": "tools/call",
            "params": {"name": "call_facts", "arguments": {"call_id": "c1"}},
        },
    )
    assert (
        json.loads(facts["result"]["content"][0]["text"])["facts"][0]["type"] == "need.primary_pain"
    )
    refused = sx.handle(
        api,
        {
            "id": 4,
            "method": "tools/call",
            "params": {"name": "add_lead", "arguments": {"name": "A"}},
        },
    )
    assert (
        refused["result"]["isError"] and "scope_missing" in refused["result"]["content"][0]["text"]
    )
    unknown = sx.handle(api, {"id": 5, "method": "tools/call", "params": {"name": "drop_db"}})
    assert unknown["error"]["code"] == -32602
    assert sx.handle(api, {"id": 6, "method": "resources/list"})["error"]["code"] == -32601

    out = io.StringIO()
    sx.serve(api, io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\nnot json\n'), out)
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert lines[0] == {"jsonrpc": "2.0", "id": 7, "result": {}}
    assert lines[1]["error"]["code"] == -32700


def test_notes_tasks_and_undo_from_the_command_line(capsys: pytest.CaptureFixture) -> None:
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    fake = Fake(
        {
            ("POST", "/leads/l1/notes"): (201, {"change_id": "c1", "status": "applied"}),
            ("POST", "/leads/l1/tasks"): (201, {"change_id": "c2", "status": "applied"}),
            ("GET", "/changes"): (200, {"changes": []}),
            ("POST", "/changes/c1/undo"): (200, {"change_id": "c1", "status": "undone"}),
        }
    )
    assert sx.main(["note", "l1", "Wants a demo", "--request-id", "req-cli-0001"], env, fake) == 0
    assert json.loads(fake.seen[0][3]) == {
        "note": "Wants a demo",
        "request_id": "req-cli-0001",
        "preview": False,
    }
    task = ["task", "l1", "--kind", "call_back", "--due", "2026-10-27T10:00:00+05:30"]
    assert sx.main(task, env, fake) == 0
    sent = json.loads(fake.seen[1][3])
    assert sent["kind"] == "call_back" and sent["due"] == "2026-10-27T10:00:00+05:30"
    assert sent["request_id"].startswith("sx-") and "title" not in sent  # one is made
    assert sx.main(["changes", "--lead", "l1"], env, fake) == 0
    assert fake.seen[2][1].endswith("/changes?lead_id=l1")
    capsys.readouterr()
    assert sx.main(["undo", "c1"], env, fake) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "undone"
