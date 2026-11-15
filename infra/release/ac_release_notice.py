#!/usr/bin/env python3
"""ac-release-notice: what the release pipeline may say on the owner's Telegram (15 Nov 2026).

The owner called the release messages "just misleading": in 48 hours about 70 reached him (each
release's start, merge, staging, promotion, phone build and web bundle, a three-part release card,
and "stopped" notices for steps the orchestrator was already re-running). His standing rule
(19 Oct) is three kinds only: "vX LIVE" with 3-5 plain bullets and a link, real incidents with
their fix status, and the twice-daily summary. So the release scripts speak only through this tool:

  ac-release-notice step TEXT...
      A step or a recoverable failure: the log, and the "dev" route when one is set up in another
      chat (/route dev in that group). Never the owner's chat, even when no dev route exists.
  ac-release-notice live --version vX.Y.Z (--title TEXT | --title-file FILE) [--link URL]
      The one owner message per release, when it is live on production: 3-5 plain bullets from
      the release title (or a hand-written <version>.txt in the owner-notes folder) and the link.
      Sent once per version.
  ac-release-notice phones --version vX.Y.Z
      The phone apps picked the release up: one line is added to that release's live note
      (edited in place, no new message), or joins the note when it goes out later.
  ac-release-notice blocked --version vX.Y.Z --what TEXT --who TEXT --next TEXT
  ac-release-notice incident --what TEXT --who TEXT --next TEXT
      Sent on purpose only, when a release truly cannot ship without action or production has a
      real problem: what is wrong, who is fixing it, when he hears next. Technical words are
      refused (exit 2), and the same notice is never sent twice.

Every notice is one JSON line in the log (what, where it went, whether Telegram took it), so a
later audit has evidence. Environment variables move the files (tests do): AC_NOTICE_TELEGRAM_ENV,
AC_NOTICE_ROUTES, AC_NOTICE_STATE, AC_NOTICE_LOG, AC_NOTICE_OWNER_NOTES, AC_NOTICE_API. Nothing
secret is printed or logged.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

try:  # the server is Linux; the lock guards against two hooks writing state at once
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX test hosts
    fcntl = None  # type: ignore[assignment]

PRODUCT = "Sales X-Ray"
LINK = "https://salesxray.authorityclosers.com"
PHONES_LINE = "📱 The phone app picks this up by itself; no Play Store update needed."
MAX_BULLETS = 5
BULLET_CHARS = 220

# Words that mean nothing to a seller or an owner. A title item with an engineering word is left
# out of the live note; a blocked or incident notice with any of these is refused, so the sender
# says it plainly.
_ENGINEERING = (
    r"hold\ recipe|recipe|wb-ci|ci|prs?|pull\ requests?|validate[-\w]*|pytest|tests?\ shards?|"
    r"canary|migrations?|schema|rehearsal|commits?|sha|merged?\ (?:in)?to\ main|main\ build|"
    r"workbench|flak[ey]\w*|re-?run(?:ning|s)?|workflows?|artifacts?|pipeline|lint|alembic|"
    r"docker|containers?|systemd|ac-ship|cutlist|holdlist|refactor\w*"
)
_PLAIN_ONLY = r"staging|promot(?:e|ed|ing|ion)|roll\ ?back|bundle|endpoint|api|server\ logs?"
_ID = r"|\#\d+|\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b"
ENGINEERING = re.compile(rf"(?ix)\b(?:{_ENGINEERING})\b{_ID}")
JARGON = re.compile(rf"(?ix)\b(?:{_ENGINEERING}|{_PLAIN_ONLY})\b{_ID}")


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


def telegram_env_path() -> Path:
    return _path("AC_NOTICE_TELEGRAM_ENV", "/etc/ac-notify/telegram.env")


def routes_path() -> Path:
    return _path("AC_NOTICE_ROUTES", "/etc/ac-notify/routes.json")


def state_path() -> Path:
    return _path("AC_NOTICE_STATE", "/var/lib/ac-release-notice/state.json")


def log_path() -> Path:
    return _path("AC_NOTICE_LOG", "/var/log/ac-notify.log")


def owner_notes_dir() -> Path:
    return _path("AC_NOTICE_OWNER_NOTES", "/etc/authority-closers/owner-notes")


# ---------------------------------------------------------------------------------------- telegram
def read_env() -> dict[str, str]:
    try:
        lines = telegram_env_path().read_text().splitlines()
    except OSError:
        return {}
    pairs = (
        line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#")
    )
    return {k.strip(): v.strip().strip("'\"") for k, v in pairs}


def call_telegram(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    """One Bot API call. Errors never carry the token or the URL."""
    token = read_env().get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "description": "no bot token"}
    base = os.environ.get("AC_NOTICE_API", "https://api.telegram.org")
    request = urllib.request.Request(  # noqa: S310 - fixed https host unless a test moves it
        f"{base}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            detail = str(json.load(error).get("description", ""))
        except ValueError:
            detail = ""
        return {"ok": False, "description": f"HTTP {error.code} {detail[:160]}"}
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return {"ok": False, "description": type(error).__name__}


Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


def owner_chat() -> str | None:
    chat = read_env().get("TELEGRAM_CHAT_ID", "")
    return chat or None


def dev_route() -> tuple[str, int | None] | None:
    """The dev group or topic, only when it is somewhere other than the owner's own chat."""
    try:
        routes = json.loads(routes_path().read_text())
    except (OSError, ValueError):
        return None
    route = routes.get("dev") if isinstance(routes, dict) else None
    if not isinstance(route, dict) or not route.get("chat_id"):
        return None
    if str(route["chat_id"]) == str(owner_chat() or ""):
        return None
    thread = route.get("thread_id")
    return str(route["chat_id"]), int(thread) if thread else None


# ----------------------------------------------------------------------------------- state and log
@contextlib.contextmanager
def locked_state() -> Iterator[dict[str, Any]]:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a+") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            state = {}
        state.setdefault("live", {})
        state.setdefault("pending_phones", [])
        state.setdefault("sent", {})
        yield state
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False))
        tmp.chmod(0o600)
        tmp.replace(path)


def log(kind: str, to: str, ok: bool, text: str, **extra: Any) -> None:
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "to": to,
        "ok": ok,
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    row["text"] = text[:600]
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        print(json.dumps(row, ensure_ascii=False), file=sys.stderr)


# ------------------------------------------------------------------------------------- composition
def short_version(version: str) -> str:
    """v1.60.0 -> v1.60 (what the owner reads in the app); v1.60.1 stays."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        return version.strip()
    major, minor, patch = match.groups()
    return f"v{major}.{minor}" if patch == "0" else f"v{major}.{minor}.{patch}"


def split_clauses(title: str) -> list[str]:
    """The release title's '; '-separated items, ignoring semicolons inside brackets."""
    title = re.sub(
        r"^\s*sales\s*x-?ray\s+v?\d+(?:\.\d+){1,2}\s*[:\-–]\s*", "", title.strip(), flags=re.I
    )
    parts, depth, current = [], 0, []
    for char in title:
        depth += char in "([{"
        depth -= char in ")]}" and depth > 0
        if char == ";" and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [p.strip().rstrip(".").strip() for p in parts if p.strip().rstrip(".").strip()]


def plain(clause: str) -> str:
    clause = re.sub(r"\s+", " ", clause).strip()
    if len(clause) > BULLET_CHARS:
        clause = clause[: BULLET_CHARS - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return clause[:1].upper() + clause[1:]


def bullets_from_title(title: str) -> tuple[list[str], list[str]]:
    """(bullets, left-out items). At most five: four items, then 'Also: ...' for the rest."""
    kept, dropped = [], []
    for clause in split_clauses(title):
        (dropped if ENGINEERING.search(clause) else kept).append(clause)
    if not kept:
        return ["Fixes and improvements across the app"], dropped
    if len(kept) <= MAX_BULLETS:
        return [plain(c) for c in kept], dropped
    head, rest = kept[: MAX_BULLETS - 1], kept[MAX_BULLETS - 1 :]
    also, used = "Also: ", 0
    for clause in rest:
        piece = clause if used == 0 else "; " + clause
        if len(also) + len(piece) > BULLET_CHARS - 16:
            break
        also += piece
        used += 1
    if used < len(rest):
        also += f"; and {len(rest) - used} more" if used else f"{len(rest)} more fixes"
    return [plain(c) for c in head] + [also], dropped


def bullets_from_notes(version: str) -> list[str] | None:
    """A hand-written owner note (one '- ' or '• ' bullet per line) wins over the title."""
    try:
        text = (owner_notes_dir() / f"{version}.txt").read_text()
    except OSError:
        return None
    lines = [re.sub(r"^\s*(?:[-•*]\s+)", "", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return [plain(line) for line in lines[:MAX_BULLETS]] or None


def live_text(version: str, bullets: list[str], link: str, phones: bool) -> str:
    lines = [f"✅ <b>{PRODUCT} {html.escape(short_version(version))} is live</b>", ""]
    lines += [f"• {html.escape(b, quote=False)}" for b in bullets]
    lines += ["", f"Open it: {html.escape(link, quote=False)}"]
    if phones:
        lines.append(PHONES_LINE)
    return "\n".join(lines)


def jargon_in(*texts: str) -> list[str]:
    found: list[str] = []
    for text in texts:
        found += [m.group(0) for m in JARGON.finditer(text)]
    return sorted(set(found), key=str.lower)


# ---------------------------------------------------------------------------------------- commands
def cmd_step(args: argparse.Namespace, send: Transport) -> int:
    text = " ".join(args.text).strip()
    if not text:
        return 2
    route = dev_route()
    if route is None:
        log(
            "step",
            "log",
            True,
            text,
            note="no dev route outside the owner's chat; kept off his Telegram",
        )
        return 0
    chat, thread = route
    payload: dict[str, Any] = {
        "chat_id": chat,
        "text": html.escape(text, quote=False)[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread:
        payload["message_thread_id"] = thread
    result = send("sendMessage", payload)
    log(
        "step",
        "dev",
        bool(result.get("ok")),
        text,
        error=None if result.get("ok") else result.get("description"),
    )
    return 0


def cmd_live(args: argparse.Namespace, send: Transport) -> int:
    version = args.version
    title = args.title
    if args.title_file:
        try:
            title = Path(args.title_file).read_text()
        except OSError:
            title = ""
    chat = owner_chat()
    with locked_state() as state:
        if version in state["live"]:
            log("live", "none", True, f"{version}: live note already sent", version=version)
            return 0
        notes = bullets_from_notes(version)
        bullets, dropped = (notes, []) if notes else bullets_from_title(title or "")
        phones = version in state["pending_phones"]
        text = live_text(version, bullets, args.link, phones)
        if chat is None:
            log("live", "log", False, text, version=version, error="no owner chat configured")
            return 1
        result = send(
            "sendMessage",
            {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        )
        ok = bool(result.get("ok"))
        log(
            "live",
            "owner",
            ok,
            text,
            version=version,
            left_out=dropped or None,
            error=None if ok else result.get("description"),
        )
        if not ok:
            return 1
        state["live"][version] = {
            "message_id": (result.get("result") or {}).get("message_id"),
            "chat_id": chat,
            "bullets": bullets,
            "link": args.link,
            "phones": phones,
            "at": time.time(),
        }
        if phones:
            state["pending_phones"] = [v for v in state["pending_phones"] if v != version]
        # Keep the file small: the newest 30 releases are plenty for edits in place.
        for old in sorted(state["live"], key=lambda v: state["live"][v].get("at", 0))[:-30]:
            del state["live"][old]
    return 0


def cmd_phones(args: argparse.Namespace, send: Transport) -> int:
    version = args.version
    with locked_state() as state:
        note = state["live"].get(version)
        if note is None:
            if version not in state["pending_phones"]:
                state["pending_phones"] = (state["pending_phones"] + [version])[-10:]
            log(
                "phones",
                "none",
                True,
                f"{version}: no live note yet; the phones line goes into it",
                version=version,
            )
            return 0
        if note.get("phones"):
            log(
                "phones",
                "none",
                True,
                f"{version}: phones line already in the live note",
                version=version,
            )
            return 0
        text = live_text(version, note["bullets"], note.get("link") or LINK, True)
        result = send(
            "editMessageText",
            {
                "chat_id": note["chat_id"],
                "message_id": note["message_id"],
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        ok = bool(result.get("ok"))
        log(
            "phones",
            "owner-edit",
            ok,
            text,
            version=version,
            error=None if ok else result.get("description"),
        )
        if ok:
            note["phones"] = True
        return 0 if ok else 1


def _plain_notice(kind: str, headline: str, args: argparse.Namespace, send: Transport) -> int:
    fields = {"what": args.what.strip(), "who": args.who.strip(), "next": args.next.strip()}
    if not all(fields.values()):
        print("ac-release-notice: --what, --who and --next are all needed", file=sys.stderr)
        return 2
    words = jargon_in(*fields.values())
    if words:
        print(
            "ac-release-notice: say it in plain words; not for the owner: " + ", ".join(words),
            file=sys.stderr,
        )
        log(kind, "refused", False, json.dumps(fields, ensure_ascii=False), jargon=words)
        return 2
    text = "\n".join(
        [
            f"⚠️ <b>{html.escape(headline, quote=False)}</b>",
            "",
            f"What's wrong: {html.escape(fields['what'], quote=False)}",
            f"Who is fixing it: {html.escape(fields['who'], quote=False)}",
            f"You'll hear next: {html.escape(fields['next'], quote=False)}",
        ]
    )
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    chat = owner_chat()
    with locked_state() as state:
        if key in state["sent"]:
            log(
                kind,
                "none",
                True,
                "same notice already sent",
                version=getattr(args, "version", None),
            )
            return 0
        if chat is None:
            log(kind, "log", False, text, error="no owner chat configured")
            return 1
        result = send(
            "sendMessage",
            {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
        )
        ok = bool(result.get("ok"))
        log(
            kind,
            "owner",
            ok,
            text,
            version=getattr(args, "version", None),
            error=None if ok else result.get("description"),
        )
        if ok:
            state["sent"][key] = time.time()
            week = time.time() - 7 * 86400
            state["sent"] = {k: v for k, v in state["sent"].items() if v > week}
        return 0 if ok else 1


def cmd_blocked(args: argparse.Namespace, send: Transport) -> int:
    return _plain_notice(
        "blocked", f"{PRODUCT} {short_version(args.version)} has not gone out yet", args, send
    )


def cmd_incident(args: argparse.Namespace, send: Transport) -> int:
    return _plain_notice("incident", f"{PRODUCT}: something is wrong", args, send)


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="ac-release-notice", description=__doc__.split("\n\n")[0])
    sub = top.add_subparsers(dest="command", required=True)
    step = sub.add_parser("step", help="a step or recoverable failure: log and dev route only")
    step.add_argument("text", nargs="+")
    live = sub.add_parser("live", help="the release is live on production: the owner's one note")
    live.add_argument("--version", required=True)
    source = live.add_mutually_exclusive_group()
    source.add_argument("--title", default="")
    source.add_argument("--title-file")
    live.add_argument("--link", default=LINK)
    phones = sub.add_parser("phones", help="add the phones line to the release's live note")
    phones.add_argument("--version", required=True)
    for name in ("blocked", "incident"):
        notice = sub.add_parser(name, help="a plain-words notice to the owner, sent on purpose")
        if name == "blocked":
            notice.add_argument("--version", required=True)
        notice.add_argument("--what", required=True)
        notice.add_argument("--who", required=True)
        notice.add_argument("--next", required=True)
    return top


COMMANDS = {
    "step": cmd_step,
    "live": cmd_live,
    "phones": cmd_phones,
    "blocked": cmd_blocked,
    "incident": cmd_incident,
}


def main(argv: list[str] | None = None, send: Transport = call_telegram) -> int:
    args = parser().parse_args(argv)
    return COMMANDS[args.command](args, send)


if __name__ == "__main__":
    sys.exit(main())
