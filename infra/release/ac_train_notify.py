#!/usr/bin/env python3
"""Write small, redacted release-train events to the local spool."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path
from typing import Any

DEFAULT_SPOOL = Path("/var/lib/ac-release/notify")
KINDS = ("status", "alert", "review")
MAX_TEXT_BYTES = 2048
STATUS_TEXT_RE = re.compile(
    r"dev [0-9a-f]{7} · staging [0-9a-f]{7} · prod [0-9a-f]{7} · smoke (?:✅|❌)"
)
URL_CREDENTIAL_RE = re.compile(r"\bhttps?://[^\s/@:]+(?::[^\s/@]*)?@", re.IGNORECASE)
TOKEN_PATTERNS = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)


class NotifyError(ValueError):
    """Input cannot be safely written to the event spool."""


def format_status_text(dev_sha: str, staging_sha: str, prod_sha: str, smoke_ok: bool) -> str:
    """Format the short status line shared by release-train pieces."""

    values = (dev_sha, staging_sha, prod_sha)
    if any(not re.fullmatch(r"[0-9a-f]{7,40}", value) for value in values):
        raise NotifyError("status commits must be lowercase Git SHAs")
    smoke = "✅" if smoke_ok else "❌"
    return f"dev {dev_sha[:7]} · staging {staging_sha[:7]} · prod {prod_sha[:7]} · smoke {smoke}"


def _safe_text(text: str) -> str:
    if not isinstance(text, str):
        raise NotifyError("event text must be a string")
    _redaction_check({"text": text})
    raw = text.encode("utf-8")
    if len(raw) > MAX_TEXT_BYTES:
        raw = raw[:MAX_TEXT_BYTES]
        text = raw.decode("utf-8", errors="ignore")
    return text


def _redaction_check(value: Any) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if URL_CREDENTIAL_RE.search(rendered):
        raise NotifyError("refusing event with credentials in a URL")
    if any(pattern.search(rendered) for pattern in TOKEN_PATTERNS):
        raise NotifyError("refusing event with a token pattern")


def _event_timestamp(now: dt.datetime | None = None) -> tuple[str, dt.datetime]:
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.UTC)
    current = current.astimezone(dt.UTC)
    stamp = current.strftime("%Y%m%dT%H%M%S.%fZ")
    return stamp, current


def _unconsumed_key_exists(spool: Path, key: str) -> bool:
    for event_path in spool.glob("*.json"):
        try:
            event = json.loads(event_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(event, dict) and event.get("key") == key and not event.get("consumed"):
            return True
    return False


def emit(
    kind: str,
    key: str,
    text: str,
    *,
    spool: Path | str = DEFAULT_SPOOL,
    **fields: Any,
) -> Path | None:
    """Atomically write an event; return None when its key is still unconsumed."""

    if kind not in KINDS:
        raise NotifyError("kind must be status, alert or review")
    if not isinstance(key, str) or not key.strip():
        raise NotifyError("event key must be a non-empty string")
    safe_text = _safe_text(text)
    if kind == "status" and not STATUS_TEXT_RE.fullmatch(safe_text):
        raise NotifyError("status text must use the release-train status format")

    event: dict[str, Any] = {
        "version": 1,
        "kind": kind,
        "key": key,
        "text": safe_text,
        "fields": fields,
    }
    _redaction_check(event)

    spool_path = Path(spool)
    spool_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = spool_path / ".writer.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if _unconsumed_key_exists(spool_path, key):
            return None

        timestamp, current = _event_timestamp()
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        filename = f"{timestamp}-{kind}-{digest}.json"
        destination = spool_path / filename
        while destination.exists():
            current += dt.timedelta(microseconds=1)
            timestamp, _ = _event_timestamp(current)
            filename = f"{timestamp}-{kind}-{digest}.json"
            destination = spool_path / filename
        event["ts"] = current.isoformat(timespec="microseconds").replace("+00:00", "Z")
        payload = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        temporary = spool_path / f".{filename}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        temp_fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.fchmod(temp_fd, 0o600)
            with os.fdopen(temp_fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            directory_fd = os.open(spool_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            finally:
                raise
        return destination
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ac-train-notify")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("--key", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--field", action="append", default=[], metavar="K=V")
    parser.add_argument("--spool", type=Path, default=DEFAULT_SPOOL)
    args = parser.parse_args(argv)
    fields: dict[str, str] = {}
    for item in args.field:
        name, separator, value = item.partition("=")
        if not separator or not name:
            parser.error("--field must use K=V")
        fields[name] = value
    try:
        path = emit(args.kind, args.key, args.text, spool=args.spool, **fields)
    except (NotifyError, OSError) as error:
        print(f"ac-train-notify: {error}", file=sys.stderr)
        return 1
    print("deduplicated" if path is None else path)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI tests
    raise SystemExit(main())
