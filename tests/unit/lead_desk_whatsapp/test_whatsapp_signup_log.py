"""WhatsApp Embedded Signup: each outcome reaches the journal with Meta's own error words,
never the signup's code or state."""

from typing import Any

import pytest

from ac_platform.lead_desk.whatsapp import http as wa_http


class Recorder:
    def __init__(self) -> None:
        self.lines: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.lines.append((event, fields))


def test_a_signup_outcome_is_logged_with_meta_s_words_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(wa_http, "events", recorder)
    back = {
        "error": "access_denied",
        "error_reason": "user_denied",
        "error_code": "200",
        "error_description": "Permissions  error:\nthe business isn't verified",
        "code": "SIGNUP-CODE-1",
        "state": "SIGNED-STATE-1",
    }
    wa_http.signup_log("cancelled", back)
    wa_http.signup_log("failed", detail="Meta didn't  share\na number.")
    wa_http.signup_log("connected")
    assert recorder.lines[0] == (
        "lead_desk_whatsapp_signup",
        {
            "outcome": "cancelled",
            "error": "access_denied",
            "reason": "user_denied",
            "meta_code": "200",
            "meta_said": "Permissions error: the business isn't verified",
            "detail": None,
        },
    )
    assert "SIGNUP-CODE" not in repr(recorder.lines) and "SIGNED-STATE" not in repr(recorder.lines)
    assert recorder.lines[1][1]["detail"] == "Meta didn't share a number."
    assert recorder.lines[1][1]["error"] is None
    assert [line[1]["outcome"] for line in recorder.lines] == ["cancelled", "failed", "connected"]
