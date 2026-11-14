"""ac-release-notice: one live note per release; steps never reach the owner (15 Nov 2026)."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/release/ac_release_notice.py"
HOOKS = (
    ROOT / "infra/application/scripts/ac-web-bundle-after-release",
    ROOT / "infra/application/scripts/ac-play-after-release",
)
OWNER = "111"

# Real release titles from /var/log/ac-ship.log (13-14 Nov 2026).
V160 = (
    "Sales Xray v1.60: Ask Dipak learning library (10 topics, 150 questions, 12 full lessons, "
    "saved lessons, next-call missions); Reports opens on Main and All Reports with search, "
    "lead-type and date filters and saved reports; Home and Leads fixes (Leads count, New leads, "
    "Pending action, Today's list, Done today); Growth tiles balanced and tappable, hour chart in "
    "AM/PM; Didn't call with Undo; analysis time left shown in New analysis and Settings, per "
    "seller for owners; silent calls get no paid report; testers get 3 hours on approval; AI "
    "credit alert email."
)
V158 = (
    "Sales Xray v1.58: a Call band on Home so the first screen always has a call; the Reports tab "
    'opens on your reports, one name "Reports" everywhere; lead history shows the 3 newest, then '
    "See more; New analysis says why Analyse is off and which files work; long-press no longer "
    "selects the app's words; the lead page follows a call in the app; Continue Calling after "
    "Pause; Growth's Day rhythm without repeats; the report's strengths read across the card."
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("ac_release_notice", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notice = _load()


class FakeTelegram:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ok = ok

    def __call__(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, payload))
        if not self.ok:
            return {"ok": False, "description": "Bad Gateway"}
        return {"ok": True, "result": {"message_id": 500 + len(self.calls)}}

    def to(self, chat: str) -> list[tuple[str, dict[str, Any]]]:
        return [c for c in self.calls if str(c[1]["chat_id"]) == chat]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "telegram.env").write_text(
        f"TELEGRAM_BOT_TOKEN=fictional\nTELEGRAM_CHAT_ID={OWNER}\n"
    )
    monkeypatch.setenv("AC_NOTICE_TELEGRAM_ENV", str(tmp_path / "telegram.env"))
    monkeypatch.setenv("AC_NOTICE_ROUTES", str(tmp_path / "routes.json"))
    monkeypatch.setenv("AC_NOTICE_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setenv("AC_NOTICE_LOG", str(tmp_path / "ac-notify.log"))
    monkeypatch.setenv("AC_NOTICE_OWNER_NOTES", str(tmp_path / "owner-notes"))
    return tmp_path


def _log(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "ac-notify.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _bullets(text: str) -> list[str]:
    return [line[2:] for line in text.splitlines() if line.startswith("• ")]


# ------------------------------------------------------------------------------------------- steps
@pytest.mark.parametrize(
    "routes",
    [None, {}, {"dev": {"chat_id": int(OWNER), "thread_id": None, "title": "private chat"}}],
    ids=["no routes file", "no dev route", "dev route is the owner's own chat"],
)
def test_a_step_never_reaches_the_owner(env: Path, routes: dict[str, Any] | None) -> None:
    if routes is not None:
        (env / "routes.json").write_text(json.dumps(routes))
    tg = FakeTelegram()
    for text in (
        "Cut v1.60.0 stopped: the hold recipe failed",
        "Ship v1.60.0 stopped: release PR #614 failed checks: validate-python-gates",
        "Shipping v1.60.0 from the workbench at bb8b506. Opening the release PR; CI takes 20 min.",
        "v1.60.0 merged to main as c159b08. Building images (about 20 minutes), then staging.",
    ):
        assert notice.main(["step", text], send=tg) == 0
    assert tg.calls == []
    rows = _log(env)
    assert len(rows) == 4 and {r["to"] for r in rows} == {"log"}
    assert rows[0]["text"] == "Cut v1.60.0 stopped: the hold recipe failed"


def test_a_step_goes_to_a_dev_group_when_one_is_set_up(env: Path) -> None:
    (env / "routes.json").write_text(
        json.dumps({"dev": {"chat_id": -100777, "thread_id": 9, "title": "AC dev"}})
    )
    tg = FakeTelegram()
    assert notice.main(["step", "Ship v1.60.0 stopped: merge of #613 failed"], send=tg) == 0
    assert tg.to(OWNER) == []
    ((method, payload),) = tg.calls
    assert (
        method == "sendMessage"
        and payload["chat_id"] == "-100777"
        and payload["message_thread_id"] == 9
    )
    assert _log(env)[-1]["to"] == "dev"


# --------------------------------------------------------------------------------------- live note
def test_the_live_note_is_one_plain_message_with_at_most_five_bullets_and_the_link(
    env: Path,
) -> None:
    tg = FakeTelegram()
    assert notice.main(["live", "--version", "v1.60.0", "--title", V160], send=tg) == 0
    ((method, payload),) = tg.calls
    assert method == "sendMessage" and payload["chat_id"] == OWNER and "reply_markup" not in payload
    text = payload["text"]
    assert text.splitlines()[0] == "✅ <b>Sales X-Ray v1.60 is live</b>"
    bullets = _bullets(text)
    assert 3 <= len(bullets) <= 5
    assert bullets[0].startswith("Ask Dipak learning library")
    assert bullets[-1].startswith("Also: Didn't call with Undo")
    assert "Open it: https://salesxray.authorityclosers.com" in text
    assert notice.PHONES_LINE not in text
    for word in ("canary", "staging", "merged", "Sales Xray v1.60:", "PR", "CI"):
        assert word not in text


def test_a_short_title_gives_one_bullet_per_item(env: Path) -> None:
    tg = FakeTelegram()
    title = "Sales Xray v1.61: a faster Leads list; Undo on Won; clearer call reports"
    assert notice.main(["live", "--version", "v1.61.0", "--title", title], send=tg) == 0
    assert _bullets(tg.calls[0][1]["text"]) == [
        "A faster Leads list",
        "Undo on Won",
        "Clearer call reports",
    ]


def test_engineering_items_are_left_out_of_the_live_note(env: Path) -> None:
    tg = FakeTelegram()
    title = (
        "Sales Xray v1.62: Leads loads twice as fast; CI shards rebalanced; refactor of the store"
    )
    assert notice.main(["live", "--version", "v1.62.0", "--title", title], send=tg) == 0
    assert _bullets(tg.calls[0][1]["text"]) == ["Leads loads twice as fast"]
    assert _log(env)[-1]["left_out"] == ["CI shards rebalanced", "refactor of the store"]


@pytest.mark.parametrize("title", [V160, V158])
def test_real_titles_never_give_more_than_five_bullets(env: Path, title: str) -> None:
    bullets, _ = notice.bullets_from_title(title)
    assert 3 <= len(bullets) <= 5
    assert all(len(b) <= notice.BULLET_CHARS for b in bullets)


def test_a_hand_written_owner_note_wins_over_the_title(env: Path) -> None:
    (env / "owner-notes").mkdir()
    (env / "owner-notes" / "v1.60.0.txt").write_text(
        "- Ask Dipak now teaches: 12 lessons and 150 questions\n"
        "- Reports has search and saved reports\n"
        "- Home and Leads counts are right\n"
    )
    tg = FakeTelegram()
    assert notice.main(["live", "--version", "v1.60.0", "--title", V160], send=tg) == 0
    assert _bullets(tg.calls[0][1]["text"]) == [
        "Ask Dipak now teaches: 12 lessons and 150 questions",
        "Reports has search and saved reports",
        "Home and Leads counts are right",
    ]


def test_the_live_note_goes_out_once_per_version(env: Path) -> None:
    tg = FakeTelegram()
    for _ in range(3):
        assert notice.main(["live", "--version", "v1.60.0", "--title", V160], send=tg) == 0
    assert len(tg.calls) == 1


def test_a_live_note_telegram_refused_is_sent_on_the_next_try(env: Path) -> None:
    down = FakeTelegram(ok=False)
    assert notice.main(["live", "--version", "v1.60.0", "--title", V160], send=down) == 1
    assert _log(env)[-1]["ok"] is False
    up = FakeTelegram()
    assert notice.main(["live", "--version", "v1.60.0", "--title", V160], send=up) == 0
    assert len(up.calls) == 1


# -------------------------------------------------------------------------------- phones, in place
def test_the_phones_line_edits_the_live_note_in_place(env: Path) -> None:
    tg = FakeTelegram()
    notice.main(["live", "--version", "v1.60.0", "--title", V160], send=tg)
    first_id = 501
    assert notice.main(["phones", "--version", "v1.60.0"], send=tg) == 0
    assert notice.main(["phones", "--version", "v1.60.0"], send=tg) == 0
    assert [c[0] for c in tg.calls] == ["sendMessage", "editMessageText"]
    edit = tg.calls[1][1]
    assert edit["chat_id"] == OWNER and edit["message_id"] == first_id
    assert edit["text"] == tg.calls[0][1]["text"] + "\n" + notice.PHONES_LINE


def test_phones_before_the_live_note_waits_and_joins_it(env: Path) -> None:
    tg = FakeTelegram()
    assert notice.main(["phones", "--version", "v1.60.0"], send=tg) == 0
    assert tg.calls == []
    notice.main(["live", "--version", "v1.60.0", "--title", V160], send=tg)
    ((method, payload),) = tg.calls
    assert method == "sendMessage" and payload["text"].endswith(notice.PHONES_LINE)
    assert notice.main(["phones", "--version", "v1.60.0"], send=tg) == 0
    assert len(tg.calls) == 1


# --------------------------------------------------------------------------- blocked and incidents
@pytest.mark.parametrize(
    "what",
    [
        "the hold recipe failed",
        "release PR #614 failed checks: validate-python-gates",
        "staging canary failed for 14c9625",
        "migrations did not rehearse",
    ],
)
def test_a_blocked_notice_in_jargon_is_refused(env: Path, what: str) -> None:
    tg = FakeTelegram()
    code = notice.main(
        [
            "blocked",
            "--version",
            "v1.60.0",
            "--what",
            what,
            "--who",
            "The release team",
            "--next",
            "By 10:00 IST",
        ],
        send=tg,
    )
    assert code == 2 and tg.calls == []
    assert _log(env)[-1]["to"] == "refused"


def test_a_plain_blocked_notice_reaches_the_owner_once(env: Path) -> None:
    tg = FakeTelegram()
    argv = [
        "blocked",
        "--version",
        "v1.60.0",
        "--what",
        "A safety check on the new version keeps failing, so it is not on your phone yet.",
        "--who",
        "The release team is fixing it now.",
        "--next",
        "You'll get the live note when it's out, or an update by 10:00 IST.",
    ]
    assert notice.main(argv, send=tg) == 0
    assert notice.main(argv, send=tg) == 0
    ((method, payload),) = tg.calls
    assert method == "sendMessage" and payload["chat_id"] == OWNER
    lines = payload["text"].splitlines()
    assert lines[0] == "⚠️ <b>Sales X-Ray v1.60 has not gone out yet</b>"
    assert lines[2].startswith("What's wrong: ") and lines[3].startswith("Who is fixing it: ")
    assert lines[4].startswith("You'll hear next: ")


def test_an_incident_needs_all_three_answers(env: Path) -> None:
    tg = FakeTelegram()
    with pytest.raises(SystemExit):
        notice.main(["incident", "--what", "Sign-in is failing for everyone"], send=tg)
    assert tg.calls == []


def test_plain_numbers_and_feature_names_are_not_jargon() -> None:
    assert notice.jargon_in("Rs 10000000 of calls", "API keys for developers") == ["API"]
    assert notice.ENGINEERING.search("API keys for developers") is None
    assert notice.ENGINEERING.search("deadline 20261115") is None
    assert notice.ENGINEERING.search("built from c159b08") is not None


# --------------------------------------------------------------------------------------- the hooks
def test_the_tool_is_an_executable_python_script() -> None:
    assert SCRIPT.read_text().startswith("#!/usr/bin/env python3\n")
    assert SCRIPT.stat().st_mode & stat.S_IXUSR or os.name == "nt"


@pytest.mark.parametrize("hook", HOOKS, ids=lambda p: p.name)
def test_release_hooks_never_call_the_owner_notifier_directly(hook: Path) -> None:
    text = hook.read_text()
    assert "ac-notify-owner" not in text
    assert ":-/usr/local/sbin/ac-release-notice}" in text
    assert '"$NOTIFY" step "$*"' in text
