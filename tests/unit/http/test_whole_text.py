"""Half an emoji never reaches a route (orchestrator, 1 Nov 2026). WholeTextMiddleware sits inside
the body-size limit, as app.py composes them: a plain str field given half an emoji answers 2xx
and keeps the rest; every other body keeps its exact bytes; the size limit still refuses first.
Made-up words only."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel
from structlog.testing import capture_logs

from ac_platform.http.request_limits import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from ac_platform.http.whole_text import WholeTextMiddleware, whole_text

JSON = {"content-type": "application/json"}


class Note(BaseModel):
    words: str


def make_app() -> tuple[FastAPI, list[bytes]]:
    seen: list[bytes] = []
    app = FastAPI()

    @app.post("/v1/notes")
    async def note(command: Note) -> dict[str, str]:
        return {"saved": command.words}

    @app.post("/v1/raw")
    async def raw(request: Request) -> dict[str, int]:
        seen.append(await request.body())
        return {"bytes": len(seen[-1])}

    app.add_middleware(WholeTextMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware)
    return app, seen


def test_a_body_without_half_an_emoji_keeps_its_exact_bytes() -> None:
    app, seen = make_app()
    client = TestClient(app)
    for body in (
        # Its spacing, a whole emoji as UTF-8, an escape and 1.50 as written.
        b'{"words": "Fine \\u00e9 \xf0\x9f\x98\x80",  "n": 1.50}',
        # A whole emoji written as its escape pair.
        b'{"words":"pair \\ud83d\\ude00"}',
        # An escaped backslash before "ud83d" is not half an emoji.
        b'{"words":"a literal \\\\ud83d"}',
    ):
        answer = client.post("/v1/raw", content=body, headers=JSON)
        assert answer.status_code == 200
        assert seen[-1] == body
    assert whole_text(b'{"words":"pair \\ud83d\\ude00"}')[1] == 0


def test_half_an_emoji_in_a_plain_str_is_answered_and_saved_without_it() -> None:
    app, _ = make_app()
    client = TestClient(app)
    # As a browser sends it: JSON.stringify writes a lone surrogate as an escape.
    body = json.dumps({"words": "Stuck \ud83d on Leads \ude00"}).encode()
    with capture_logs() as logs:
        answer = client.post("/v1/notes", content=body, headers=JSON)
    assert answer.status_code == 200
    assert answer.json() == {"saved": "Stuck  on Leads "}
    (line,) = [log for log in logs if log["event"] == "json_half_characters_dropped"]
    assert (line["method"], line["path"], line["count"]) == ("POST", "/v1/notes", 2)
    # The route and the count, never the text.
    assert "Stuck" not in json.dumps(line)


def test_an_oversized_body_is_still_refused_by_the_size_limit() -> None:
    app, _ = make_app()
    client = TestClient(app)
    body = ('{"words":"\\ud83d' + "x" * MAX_REQUEST_BODY_BYTES + '"}').encode()
    assert client.post("/v1/notes", content=body, headers=JSON).status_code == 413


def test_a_body_that_is_not_json_passes_through_untouched() -> None:
    app, seen = make_app()
    client = TestClient(app)
    text = b"words=Stuck \\ud83d"
    plain = client.post("/v1/raw", content=text, headers={"content-type": "text/plain"})
    assert plain.status_code == 200 and seen[-1] == text
    # Said to be JSON but not valid: its bytes go on, and the route decides.
    broken = b'{"words": "Stuck \\ud83d"'
    assert client.post("/v1/raw", content=broken, headers=JSON).status_code == 200
    assert seen[-1] == broken
