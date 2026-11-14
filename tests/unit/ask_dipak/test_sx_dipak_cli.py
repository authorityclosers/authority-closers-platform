"""sx dipak: Ask Dipak from the command line (no network): each command calls its
/v1/api/ask-dipak route with the key, and a refusal comes back as a clear error."""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "sx_cli_dipak", ROOT / "apps/sales-xray-web/public/developers/sx.py"
)
assert _spec is not None and _spec.loader is not None
sx: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sx)

TOKEN = "sxa_" + "b" * 40
BASE = "https://salesxray.example.test/v1/api"


class Fake:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status, self.body, self.seen = status, body or {"ok": True}, []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        data = json.loads(request.data) if request.data else None
        self.seen.append((request.get_method(), request.full_url.split("/v1/api", 1)[1], data))
        return self.status, json.dumps(self.body).encode()


def run(argv: list[str], fake: Fake) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = sx.main(argv, {"SX_API_KEY": TOKEN, "SX_API_BASE": BASE}, fake)
    return code, out.getvalue()


@pytest.mark.parametrize(
    ("argv", "method", "path", "body"),
    [
        (["dipak", "search", "price", "high"], "GET", "/ask-dipak/lessons?q=price+high", None),
        (["dipak", "search"], "GET", "/ask-dipak/lessons", None),
        (["dipak", "lesson", "PB03"], "GET", "/ask-dipak/lessons/PB03", None),
        (
            ["dipak", "improve", "--skills", "closing_decision_management"],
            "GET",
            "/ask-dipak/how-to-improve?skills=closing_decision_management",
            None,
        ),
        (["dipak", "missions"], "GET", "/ask-dipak/missions", None),
        (["dipak", "team"], "GET", "/ask-dipak/team", None),
        (["dipak", "calls"], "GET", "/ask-dipak/calls", None),
        (["dipak", "save", "PB03"], "PUT", "/ask-dipak/saved/PB03", {"on": True}),
        (["dipak", "tick", "PB03", "--off"], "PUT", "/ask-dipak/ticked/PB03", {"on": False}),
        (["dipak", "active", "NEW-035"], "PUT", "/ask-dipak/active/NEW-035", {"on": True}),
        (
            ["dipak", "answer", "c1", "PB03", "yes"],
            "PUT",
            "/ask-dipak/calls/c1/check",
            {"answers": [{"question_id": "PB03", "done": True}]},
        ),
    ],
)
def test_each_command_calls_its_route(argv: list[str], method: str, path: str, body: Any) -> None:
    fake = Fake(body={"questions": []})
    code, out = run(argv, fake)
    assert code == 0 and json.loads(out) == {"questions": []}
    assert fake.seen == [(method, path, body)]


def test_a_refusal_is_a_clear_error() -> None:
    fake = Fake(403, {"error": {"code": "person_only", "message": "Connect as yourself."}})
    errors = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(errors):
        code = sx.main(["dipak", "missions"], {"SX_API_KEY": TOKEN, "SX_API_BASE": BASE}, fake)
    assert code == 1
    assert json.loads(errors.getvalue())["error"]["code"] == "person_only"
