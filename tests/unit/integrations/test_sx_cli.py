"""sx.py, served at /developers/sx.py: the command line and MCP server (no network)."""

from __future__ import annotations

import hashlib
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
        "move_stage",
        "list_my_changes",
        "undo_change",
        "import_leads",
        "get_lead_import",
        "list_reports",
        "get_report",
        "get_transcript",
        "analysis_time",
        "list_tasks",
        "complete_task",
        "snooze_task",
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


def test_a_stage_move_from_the_command_line_and_the_mcp_tool() -> None:
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    fake = Fake({("POST", "/leads/l1/stage"): (200, {"change_id": "c3", "status": "applied"})})
    move = ["stage", "l1", "interested", "--reason", "Asked for the brochure"]
    assert sx.main([*move, "--request-id", "req-cli-0003"], env, fake) == 0
    assert json.loads(fake.seen[0][3]) == {
        "step": "interested",
        "reason": "Asked for the brochure",
        "request_id": "req-cli-0003",
        "preview": False,
    }
    called = sx.handle(
        client(fake),
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "move_stage",
                "arguments": {
                    "lead_id": "l1",
                    "step": "follow_up",
                    "reason": "Call after Diwali",
                    "next_action_at": "2026-11-20T10:00:00+05:30",
                    "request_id": "req-mcp-0003",
                },
            },
        },
    )
    assert "isError" not in called["result"]
    assert json.loads(called["result"]["content"][0]["text"])["status"] == "applied"
    sent = json.loads(fake.seen[1][3])
    assert sent["step"] == "follow_up" and sent["next_action_at"].startswith("2026-11-20")
    assert "reason_code" not in sent and "expected_revision" not in sent


def test_analysis_time_from_the_command_line_and_the_mcp_tool() -> None:
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    fake = Fake(
        {
            ("GET", "/analysis-time"): (200, {"left_seconds": 5400}),
            ("GET", "/analysis-time/team"): (200, {"left_seconds": 5400, "people": []}),
        }
    )
    assert sx.main(["minutes"], env, fake) == 0
    assert sx.main(["minutes", "--team"], env, fake) == 0
    assert [seen[1].split("/v1/api", 1)[1] for seen in fake.seen] == [
        "/analysis-time",
        "/analysis-time/team",
    ]
    called = sx.handle(
        client(fake),
        {
            "id": 1,
            "method": "tools/call",
            "params": {"name": "analysis_time", "arguments": {"team": True}},
        },
    )
    assert json.loads(called["result"]["content"][0]["text"])["people"] == []


def test_tasks_done_and_snooze_from_the_command_line_and_the_mcp_tools() -> None:
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    fake = Fake(
        {
            ("GET", "/tasks"): (200, {"tasks": [], "counts": {"today": 0}}),
            ("POST", "/tasks/t1/done"): (200, {"change_id": "c4", "status": "applied"}),
            ("POST", "/tasks/t1/snooze"): (200, {"change_id": "c5", "status": "applied"}),
        }
    )
    assert sx.main(["tasks", "--view", "overdue"], env, fake) == 0
    assert fake.seen[0][1].endswith("/tasks?view=overdue")
    assert sx.main(["done", "t1", "--request-id", "req-cli-0005"], env, fake) == 0
    assert json.loads(fake.seen[1][3]) == {"request_id": "req-cli-0005", "preview": False}
    assert sx.main(["snooze", "t1", "tomorrow"], env, fake) == 0
    sent = json.loads(fake.seen[2][3])
    assert sent["choice"] == "tomorrow" and sent["request_id"].startswith("sx-")
    called = sx.handle(
        client(fake),
        {
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "snooze_task",
                "arguments": {"task_id": "t1", "choice": "1h", "request_id": "req-mcp-0005"},
            },
        },
    )
    assert json.loads(called["result"]["content"][0]["text"])["status"] == "applied"
    assert json.loads(fake.seen[3][3])["choice"] == "1h"


def test_sx_list_leads_takes_the_organisations_own_stage_keys() -> None:
    (tool,) = [t for t in sx.TOOLS if t["name"] == "list_leads"]
    stage = tool["inputSchema"]["properties"]["stage"]
    assert "enum" not in stage and stage["maxLength"] == 40
    assert "stages" in tool["description"]


def test_import_leads_reads_a_file_sends_idempotent_imports_and_reports_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """sx import-leads (owner, 14 Nov 2026): a CSV in, imports of --per-import rows each
    with an Idempotency-Key from the file, a busy workspace waited out, and the skipped rows
    written with why."""
    source = tmp_path / "fictional.csv"
    source.write_text(
        "Name,Phone,City,ID,Notes\n"
        "Asha Sample,+919876500001,Pune,a1,ignored\n"
        "Ravi Sample,+919876500002,,a2,\n"
        "Meera Sample,12,Nashik,a3,\n",
        encoding="utf-8",
    )
    assert sx.read_leads(str(source))[0] == {
        "name": "Asha Sample",
        "phone": "+919876500001",
        "city": "Pune",
        "external_id": "a1",
    }
    busy = {"status": 429, "left": 1}
    seen_keys: list[str] = []

    class Imports(Fake):
        def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
            path = request.full_url.split("/v1/api", 1)[1].split("?", 1)[0]
            if request.get_method() == "POST" and path == "/leads/imports":
                self.seen.append(("POST", request.full_url, request.headers, request.data))
                if busy["left"]:
                    busy["left"] -= 1
                    body = {"error": {"code": "imports_busy", "message": "Wait."}}
                    return 429, json.dumps(body).encode()
                seen_keys.append(request.headers["Idempotency-key"])
                sent = json.loads(request.data)
                answer = {
                    "id": f"imp-{len(seen_keys)}",
                    "status": "queued",
                    "total": len(sent["leads"]),
                }
                return 202, json.dumps(answer).encode()
            if "outcome=failed" in request.full_url:
                self.seen.append(("GET", request.full_url, request.headers, None))
                return 200, json.dumps({"rows": [], "next_after": None}).encode()
            return super().__call__(request)

    fake = Imports(
        {
            ("GET", "/leads/imports/imp-1"): (
                200,
                {"id": "imp-1", "status": "done", "total": 2, "created": 2, "skipped": 0},
            ),
            ("GET", "/leads/imports/imp-2"): (
                200,
                {"id": "imp-2", "status": "done", "total": 1, "created": 0, "skipped": 1},
            ),
            ("GET", "/leads/imports/imp-1/rows"): (200, {"rows": [], "next_after": None}),
            ("GET", "/leads/imports/imp-2/rows"): (
                200,
                {
                    "rows": [
                        {
                            "row": 0,
                            "external_id": "a3",
                            "outcome": "skipped",
                            "reason": "Number can't be read",
                        }
                    ],
                    "next_after": None,
                },
            ),
        }
    )
    waits: list[float] = []
    failures = tmp_path / "problems.csv"
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    code = sx.main(
        [
            "import-leads",
            str(source),
            "--side",
            "cold",
            "--per-import",
            "2",
            "--failures",
            str(failures),
        ],
        env,
        fake,
        waits.append,
    )
    assert code == 0, capsys.readouterr().err
    out = json.loads(capsys.readouterr().out)
    assert out["totals"] == {"total": 3, "created": 2, "updated": 0, "skipped": 1, "failed": 0}
    assert waits and waits[0] == 5  # the busy workspace, waited out once
    # Two imports, each keyed by the file and its part: the same file again is the same.
    assert len(seen_keys) == 2 and seen_keys[0] != seen_keys[1]
    assert all(key.startswith("sx-") and key.endswith(("-0", "-1")) for key in seen_keys)
    posted = [json.loads(item[3]) for item in fake.seen if item[0] == "POST" and item[3]]
    assert posted[-1]["side"] == "cold" and len(posted[-1]["leads"]) == 1
    assert "notes" not in posted[-1]["leads"][0]
    # The skipped row, by its line in the file (row 0 of the second import is line 3).
    assert failures.read_text(encoding="utf-8").splitlines() == [
        "row,external_id,outcome,reason",
        "3,a3,skipped,Number can't be read",
    ]


def test_upload_sends_a_sellers_call_and_waits_for_its_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """API gap 2 (15 Nov 2026): sx upload FILE --seller ... --wait opens the upload, sends
    the file with its SHA-256 and the recording statement, then follows it to its report."""
    audio = tmp_path / "call.wav"
    audio.write_bytes(b"RIFF" + bytes(60))
    fake = Fake(
        {
            ("POST", "/recordings"): (201, {"id": "u1", "state": "waiting_for_file"}),
            ("PUT", "/recordings/u1/source"): (202, {"id": "u1", "state": "queued"}),
        }
    )
    states = iter([{"state": "analysing"}, {"state": "report_ready", "call_id": "u1"}])

    def answer(request: urllib.request.Request) -> tuple[int, bytes]:
        if request.get_method() == "GET":
            fake.seen.append((request.get_method(), request.full_url, request.headers, None))
            return 200, json.dumps(next(states)).encode()
        return fake(request)

    waits: list[float] = []
    env = {"SX_API_KEY": KEY, "SX_API_BASE": "https://salesxray.example.test/v1/api"}
    command = ["upload", str(audio), "--seller", "asha@example.test", "--lead", "l1", "--wait"]
    assert sx.main(command, env, answer, waits.append) == 0, capsys.readouterr().err
    assert json.loads(capsys.readouterr().out) == {"state": "report_ready", "call_id": "u1"}
    assert waits == [5, 5]
    opened, sent = fake.seen[0], fake.seen[1]
    assert json.loads(opened[3]) == {
        "seller_email": "asha@example.test",
        "lead_id": "l1",
        "file_name": "call.wav",
    }
    assert (sent[0], sent[3]) == ("PUT", audio.read_bytes())
    assert sent[2]["Content-type"] == "application/octet-stream"
    assert sent[2]["X-source-sha256"] == hashlib.sha256(audio.read_bytes()).hexdigest()
    assert sent[2]["X-recording-consent"] == "participants-informed"
    # A person's id instead of an email; a refusal prints its code and exits 1.
    closed = Fake(
        {
            ("POST", "/recordings"): (
                403,
                {"error": {"code": "api_uploads_off", "message": "Not yet."}},
            )
        }
    )
    assert sx.main(["upload", str(audio), "--seller", "p1"], env, closed) == 1
    assert "api_uploads_off" in capsys.readouterr().err
    assert json.loads(closed.seen[0][3]) == {"seller_id": "p1", "file_name": "call.wav"}
