"""AC's task route into the shared Pulse runs only its fixed operations inside Authority
Closers' organisation, passes the caller's values as quoted data, and the old address
redirects with its path."""

import importlib.machinery
import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "infra" / "pulse-ac-shared"


def load(name: str, path: Path) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


route = load("pulse_ac_tasks_root", HERE / "ea" / "pulse-ac-tasks-root")
redirect = load("ac_pulse_redirect", HERE / "ac" / "ac-pulse-redirect")


def run(
    monkeypatch: pytest.MonkeyPatch, request: object
) -> tuple[int, dict, list[str]]:
    sent: list[str] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        sent.append(str(kwargs["input"]))
        rows = [
            json.dumps({"i": i, "op": "x", "r": None})
            for i in range(len(request["ops"]))
        ]  # type: ignore[index]
        return subprocess.CompletedProcess(argv, 0, "\n".join(rows) + "\n", "")

    monkeypatch.setattr(route.subprocess, "run", fake_run)
    raw = request if isinstance(request, bytes) else json.dumps(request).encode()
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(raw)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    code = route.main()
    return code, json.loads(out.getvalue()), sent


def test_unknown_operations_and_usernames_are_refused_before_any_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for bad in (
        {"ops": [{"op": "sql", "q": "select 1"}]},
        {"ops": []},
        {"ops": [{"op": "find"}] * 201},
        {"as": "x'; drop", "ops": [{"op": "people"}]},
        b"not json",
    ):
        code, answer, sent = run(monkeypatch, bad)
        assert code == 2 and "error" in answer and sent == []


def test_values_travel_only_inside_dollar_quotes_in_one_fixed_organisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evil = "x'); select pulse.task_save(null, '{}'); --"
    code, answer, sent = run(
        monkeypatch,
        {
            "as": "suyash",
            "actor": "test",
            "ops": [
                {"op": "find", "title": evil},
                {"op": "save", "fields": {"title": evil}},
            ],
        },
    )
    assert code == 0 and answer["committed"] is True
    script = sent[0]
    assert f"set_config('pulse.org_id', '{route.ORG}', true)" in script
    assert script.count("set_config('pulse.org_id'") == 1
    assert "set local role pulse_owner;" in script and script.rstrip().endswith(
        "commit;"
    )
    for line in script.splitlines():
        if evil.replace("'", "") in line.replace("'", ""):
            tag = line[line.index("$q") : line.index("$", line.index("$q") + 1) + 1]
            assert line.count(tag) == 2, (
                "the value sits between one pair of its own dollar quotes"
            )


def test_a_dry_request_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    code, answer, sent = run(monkeypatch, {"dry": True, "ops": [{"op": "people"}]})
    assert (
        code == 0
        and answer["committed"] is False
        and sent[0].rstrip().endswith("rollback;")
    )


def test_quote_never_uses_a_tag_found_in_the_text() -> None:
    for text in ("", "$q$", "plain", "$qabcdef012345$ inside"):
        q = route.quote(text)
        tag = q[: q.index("$", 1) + 1]
        assert q == tag + text + tag and tag not in text


def test_the_old_address_redirects_with_its_path() -> None:
    sent: dict[str, object] = {}

    class Probe(redirect.Redirect):
        def __init__(self) -> None:  # no socket: only the response is checked
            self.path = "/tasks/abc?x=1"

        def send_response(self, code: int, message: str | None = None) -> None:
            sent["code"] = code

        def send_header(self, key: str, value: str) -> None:
            sent[key] = value

        def end_headers(self) -> None:
            sent["ended"] = True

    Probe().do_GET()
    assert sent["code"] == 301
    assert sent["Location"] == "https://ac-pulse.estateautopilots.com/tasks/abc?x=1"


LEADERSHIP = "216caed5-2a3b-4639-9cbb-8f48c344fd5c"


def test_chat_posts_only_to_allowlisted_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    allow = tmp_path / "chat-allow"
    allow.write_text(f"# comment\n{LEADERSHIP}  # AC Leadership\n", encoding="utf-8")
    monkeypatch.setattr(route, "CHAT_ALLOW", str(allow))
    other = "00000000-0000-4000-8000-000000000000"
    code, answer, sent = run(
        monkeypatch, {"ops": [{"op": "chat", "channelId": other, "body": "x"}]}
    )
    assert code == 2 and "allowlist" in answer["error"] and sent == []
    code, answer, sent = run(
        monkeypatch, {"ops": [{"op": "chat", "channelId": LEADERSHIP, "body": " "}]}
    )
    assert code == 2 and sent == []
    code, answer, sent = run(
        monkeypatch,
        {
            "dry": True,
            "ops": [{"op": "chat", "channelId": LEADERSHIP, "body": "v0.85 is live"}],
        },
    )
    assert (
        code == 0
        and "pulse.chat_send(" in sent[0]
        and sent[0].rstrip().endswith("rollback;")
    )
