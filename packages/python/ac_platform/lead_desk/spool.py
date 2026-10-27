"""Release-safe intake (owner, 27 Oct 2026; docs/product/lead-desk/release-safe-intake.md).

During a release's hold the API is stopped and the database takes only migrations, so
the edge answers every request 503. Meta, WhatsApp and Google retry that, but a website
form never does, and Zapier, Make and Pabbly do only when set to. The hold therefore
sends the two capture routes here instead:

- ``serve``: its own small container (the API image, standard library only, no database).
  It takes ``POST /v1/lead-desk/capture/{id}`` and ``.../google-ads``, reads the body as
  the API does, keeps the source key only as its SHA-256, writes one file per lead
  (temporary file, fsync, rename) and answers 202 as the API does. A flood is bounded by
  the body size, the number of waiting files and a per-address rate, and a sender has
  15 s to send its body, as at the API.
- ``replay``: inside the API, every minute. It files each waiting lead through the same
  ``Intake.capture`` key check and dedupe, with ``received_at`` the time it arrived here,
  then deletes the file: the lead is in the database now. A wrong key, an unknown source
  or no answers moves it to ``rejected/``, deleted after a week, and so does a file that
  still fails a day after it came. Anything else stays for the next minute.

    python -m ac_platform.lead_desk.spool serve [--port 8080]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qs, parse_qsl, urlsplit

log = logging.getLogger(__name__)

ROOT_ENV = "AC_INTAKE_SPOOL_ROOT"
DEFAULT_ROOT = "/var/lib/ac-intake-spool"
MAX_BODY = 64 * 1024  # the API's own capture limit
MAX_WAITING = 10_000
PER_ADDRESS = 60  # posts a minute from one address
KEEP = timedelta(days=7)
REPLAY_EVERY = 60.0
BODY_SECONDS = 15.0  # the API's own capture reads a body for at most 15 s
GIVE_UP = timedelta(hours=24)
PATH = re.compile(
    r"^/v1/lead-desk/capture/"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r"(/google-ads)?$"
)
HOLD_TEXT = "Authority Closers {environment} is completing a reviewed release.\n"
QUEUED = {"received": True, "outcome": "queued", "lead_id": None}
FOLDERS = ("tmp", "new", "rejected")
BROKEN = "The lead didn't arrive whole. Send it again."


class Refused(Exception):
    """A post the API would refuse too: the status and the API's own words."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def root_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get(ROOT_ENV) or DEFAULT_ROOT)


def prepare(root: Path) -> None:
    for name in FOLDERS:
        (root / name).mkdir(mode=0o700, parents=True, exist_ok=True)


def _record(raw: bytes, content_type: str | None) -> dict[str, Any]:
    """The body as the API's capture reads it (lead_desk/http.py ``_record``)."""
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        if kind == "application/x-www-form-urlencoded":
            pairs = parse_qsl(raw.decode(), keep_blank_values=False, max_num_fields=200)
            return {name[:120]: value[:2000] for name, value in pairs}
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Refused(422, "Send the lead as JSON or as a form.") from None
    if not isinstance(value, dict):
        raise Refused(422, "Send one lead as a JSON object.")
    return value


def _source_key(query: str, headers: Mapping[str, str]) -> str:
    """The key as the API's capture takes it: header, bearer token or ``?key=``."""
    bearer = headers.get("authorization", "").removeprefix("Bearer ").strip()
    key = headers.get("x-lead-desk-key") or bearer or parse_qs(query).get("key", [""])[0]
    if not key or len(key) > 128:
        raise Refused(401, "Send the source key.")
    return key


def entry_for(
    path: str, query: str, headers: Mapping[str, str], body: bytes, now: datetime
) -> dict[str, Any]:
    """What one post keeps: the source, the key's hash, when it came, and the lead."""
    found = PATH.match(path)
    if found is None:
        raise Refused(404, "Not found.")
    if len(body) > MAX_BODY:
        raise Refused(413, "That's too large to send.")
    headers = {name.lower(): value for name, value in headers.items()}
    google = bool(found.group(2))
    if google:
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise Refused(422, "Send the lead as JSON.") from None
        if not isinstance(payload, dict):
            raise Refused(422, "Send one lead as a JSON object.")
        key = payload.pop("google_key", None)
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise Refused(422, "Paste the key from Sales Xray into the lead form's Key box.")
        key = key.strip()
        if not isinstance(payload.get("user_column_data"), list) or not payload["user_column_data"]:
            raise Refused(422, "Google Ads sent a lead with no answers.")
        lead: dict[str, Any] = payload
    else:
        key = _source_key(query, headers)
        lead = _record(body, headers.get("content-type"))
        lead.pop("key", None)
    return {
        "v": 1,
        "id": uuid.uuid4().hex,
        "source_id": found.group(1).lower(),
        "google": google,
        "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "received_at": now.isoformat(),
        "lead": lead,
    }


def write(root: Path, entry: Mapping[str, Any]) -> Path:
    """One file per lead, whole or not at all: a temporary file, fsync, then rename."""
    if len(os.listdir(root / "new")) >= MAX_WAITING:
        raise Refused(503, "The spool is full.")
    stamp = datetime.fromisoformat(str(entry["received_at"])).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"{stamp}-{entry['id']}.json"
    temporary = root / "tmp" / name
    data = json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    final = root / "new" / name
    os.replace(temporary, final)
    folder = os.open(root / "new", os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    return final


def _until(connection: Any, deadline: float) -> None:
    """Let the next read wait only until the body's deadline."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("the body took longer than 15 s")
    connection.settimeout(left)


def _exactly(stream: Any, connection: Any, size: int, deadline: float) -> bytes:
    data = bytearray()
    while len(data) < size:
        _until(connection, deadline)
        part = stream.read1(min(size - len(data), 16_384))
        if not part:
            raise Refused(400, BROKEN)
        data += part
    return bytes(data)


def _chunked(stream: Any, connection: Any, deadline: float) -> bytes:
    """A chunked body, which Caddy passes on as the sender sent it, read as the API
    reads one: at most ``MAX_BODY``, within the deadline."""
    data = bytearray()
    while True:
        _until(connection, deadline)
        line = stream.readline(80)
        try:
            size = int(line.split(b";", 1)[0].strip(), 16)
        except ValueError:
            raise Refused(400, BROKEN) from None
        if size < 0:
            raise Refused(400, BROKEN)
        if size == 0:
            break
        if len(data) + size > MAX_BODY:
            raise Refused(413, "That's too large to send.")
        data += _exactly(stream, connection, size, deadline)
        _until(connection, deadline)
        if stream.readline(3).strip():
            raise Refused(400, BROKEN)
    for _ in range(32):  # trailers, up to a blank line
        _until(connection, deadline)
        if not stream.readline(1024).strip():
            return bytes(data)
    raise Refused(400, BROKEN)


Address = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip(text: str) -> Address | None:
    try:
        return ipaddress.ip_address(text.strip())
    except ValueError:
        return None


def _one(address: Address) -> str:
    if isinstance(address, ipaddress.IPv4Address):
        return address.compressed
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped.compressed
    network = ipaddress.ip_network((address, 64), strict=False)
    return f"{network.network_address.compressed}/64"


def trusted(env: Mapping[str, str] | None = None) -> frozenset[Address]:
    """The edge router's exact addresses (AC_TRUSTED_PROXY_ADDRESSES, as the API reads it)."""
    env = os.environ if env is None else env
    found = (
        _ip(part) for part in env.get("AC_TRUSTED_PROXY_ADDRESSES", "").split(",") if part.strip()
    )
    return frozenset(address for address in found if address is not None)


def sender(peer: str, cloudflare: list[str], trusted: frozenset[Address]) -> str:
    """Who sent a post, as the API's limiter reads it (http/rate_limits.py
    ``client_identity``): Cloudflare's CF-Connecting-IP only when the edge router
    delivered it and there is exactly one, else the peer; an IPv6 sender by its /64,
    so rotating within it doesn't escape the rate. X-Forwarded-For is never read."""
    address = _ip(peer)
    if address is not None and address in trusted and len(cloudflare) == 1:
        forwarded = _ip(cloudflare[0])
        if forwarded is not None:
            return _one(forwarded)
    return "unknown" if address is None else _one(address)


class _Rate:
    """At most ``PER_ADDRESS`` posts a minute from one address."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, list[float]] = {}

    def allow(self, address: str, now: float) -> bool:
        with self._lock:
            recent = [at for at in self._seen.get(address, []) if now - at < 60]
            if len(recent) >= PER_ADDRESS:
                self._seen[address] = recent
                return False
            recent.append(now)
            self._seen[address] = recent
            if len(self._seen) > 10_000:
                self._seen = {address: recent}
            return True


class _Handler(BaseHTTPRequestHandler):
    server_version = "ac-intake-spool"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    # Every read waits at most 15 s, so a sender that stalls, or says its body is
    # longer than it is, can't hold a thread (the spool has 64 processes).
    timeout = 15

    def log_message(self, format: str, *args: Any) -> None:
        return None  # one line per post is logged below, without its content

    def _send(self, status: int, body: bytes, kind: str, retry: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if retry:
            self.send_header("Retry-After", "30")
        self.end_headers()
        self.wfile.write(body)

    def _hold(self) -> None:
        server: SpoolServer = self.server  # type: ignore[assignment]
        self._send(503, server.hold_text.encode(), "text/plain; charset=utf-8", retry=True)

    def _json(self, status: int, value: object) -> None:
        self._send(status, json.dumps(value).encode(), "application/json", retry=status == 503)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, b"ok\n", "text/plain; charset=utf-8")
        else:
            self._hold()

    def do_POST(self) -> None:
        server: SpoolServer = self.server  # type: ignore[assignment]
        parts = urlsplit(self.path)
        try:
            body = self._body()
        except Refused as refused:
            self.close_connection = True
            self._json(refused.status, {"detail": refused.detail})
            return
        if not server.rate.allow(self._address(), time.monotonic()):
            self._json(429, {"detail": "Too many leads at once. Try again in a minute."})
            return
        try:
            entry = entry_for(
                parts.path, parts.query, dict(self.headers.items()), body, datetime.now(UTC)
            )
            write(server.root, entry)
        except Refused as refused:
            if refused.status == 503:
                self._hold()
            else:
                self._json(refused.status, {"detail": refused.detail})
            print(
                json.dumps({"event": "intake_spool_refused", "status": refused.status}),
                file=sys.stderr,
                flush=True,
            )
            return
        print(
            json.dumps({"event": "intake_spooled", "google": entry["google"]}),
            file=sys.stderr,
            flush=True,
        )
        self._json(202, QUEUED)

    def _body(self) -> bytes:
        """The body by its length or in chunks, at most 64 KiB, all of it within 15 s.
        A sender past the deadline is dropped (``handle_one_request`` closes on
        ``TimeoutError``)."""
        deadline = time.monotonic() + BODY_SECONDS
        try:
            if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
                return _chunked(self.rfile, self.connection, deadline)
            length = self.headers.get("Content-Length")
            if length is None or not length.isdigit():
                raise Refused(411, "Send the lead with its length.")
            if int(length) > MAX_BODY:
                raise Refused(413, "That's too large to send.")
            return _exactly(self.rfile, self.connection, int(length), deadline)
        finally:
            self.connection.settimeout(self.timeout)

    def _address(self) -> str:
        server: SpoolServer = self.server  # type: ignore[assignment]
        return sender(
            self.client_address[0],
            self.headers.get_all("CF-Connecting-IP") or [],
            server.trusted,
        )

    def _other(self) -> None:
        self._hold()

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _other


class SpoolServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], root: Path) -> None:
        prepare(root)
        self.root = root
        self.rate = _Rate()
        self.trusted = trusted()
        environment = os.environ.get("AC_ENVIRONMENT") or "production"
        self.hold_text = HOLD_TEXT.format(environment=environment)
        super().__init__(address, _Handler)


# ----- replay, inside the API -------------------------------------------------------------


def _move(path: Path, folder: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.replace(path, path.parent.parent / folder / path.name)


def _prune(root: Path, now: float) -> None:
    for path in (root / "rejected").glob("*.json"):
        with contextlib.suppress(FileNotFoundError):
            if now - path.stat().st_mtime > KEEP.total_seconds():
                path.unlink()


def _keep_or_give_up(path: Path, received_at: datetime, now: datetime, why: str) -> str:
    """A lead that still fails a day after it came moves to rejected/, with one error
    log, so new/ can't fill with files that never file and starve real leads."""
    if now - received_at <= GIVE_UP:
        return "kept"
    _move(path, "rejected")
    log.error("intake_spool_gave_up %s", json.dumps({"file": path.name, "why": why}))
    return "rejected"


def _claim(root: Path) -> TextIO | None:
    """This process's turn to replay, or None while another process holds it."""
    import fcntl

    lock = open(root / ".replay.lock", "a")  # noqa: SIM115 - held until the replay ends
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return None
    return lock


def _waiting(root: Path) -> list[tuple[Path, dict[str, Any] | None]]:
    """The waiting leads, oldest first; None for a file that doesn't read."""
    found: list[tuple[Path, dict[str, Any] | None]] = []
    for path in sorted((root / "new").glob("*.json")):
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
            entry = None
        found.append((path, entry if isinstance(entry, dict) else None))
    return found


async def replay(sessions: Any, root: Path, *, app_url: str) -> dict[str, int]:
    """File every waiting lead; returns how many were filed, known, rejected and kept."""
    from ac_platform.lead_desk.connectors import google_ads
    from ac_platform.lead_desk.intake import Intake
    from ac_platform.lead_desk.store import DeskError

    counts = {"filed": 0, "known": 0, "rejected": 0, "kept": 0}
    if not (root / "new").is_dir():
        return counts
    lock = _claim(root)
    if lock is None:
        return counts
    now = datetime.now(UTC)
    try:
        for path, entry in _waiting(root):
            try:
                if entry is None:
                    raise ValueError("unreadable")
                lead = dict(entry["lead"])
                record = google_ads.to_record(lead) if entry.get("google") else lead
                source_id = uuid.UUID(str(entry["source_id"]))
                received_at = datetime.fromisoformat(str(entry["received_at"]))
                if received_at.tzinfo is None:
                    raise ValueError("no time zone")
                key_sha256 = str(entry["key_sha256"])
            except (ValueError, KeyError, TypeError, google_ads.GoogleAdsError):
                _move(path, "rejected")
                counts["rejected"] += 1
                continue
            try:
                async with sessions() as database, database.begin():
                    _, outcome = await Intake.capture(
                        database,
                        source_id,
                        "",
                        record,
                        app_url=app_url,
                        test_data=bool(entry.get("google")) and lead.get("is_test") is True,
                        kind="google_ads" if entry.get("google") else None,
                        key_sha256=key_sha256,
                        received_at=received_at,
                    )
            except DeskError as error:
                if error.status in {401, 404, 422}:
                    _move(path, "rejected")
                    counts["rejected"] += 1
                else:
                    why = f"status {error.status}"
                    counts[_keep_or_give_up(path, received_at, now, why)] += 1
                continue
            except Exception:
                log.exception("intake_spool_replay_failed")
                counts[_keep_or_give_up(path, received_at, now, "error")] += 1
                continue
            # The lead is in the database now; no second copy waits on disk.
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            counts["known" if outcome in {"known", "skipped"} else "filed"] += 1
        _prune(root, time.time())
    finally:
        lock.close()  # closing releases the lock
    return counts


async def run_replay(
    sessions: Any, stop: asyncio.Event, *, app_url: str, root: Path | None = None
) -> None:
    """Replay every minute for the API's lifetime; quiet while nothing waits."""
    root = root_path() if root is None else root
    while not stop.is_set():
        try:
            counts = await replay(sessions, root, app_url=app_url)
            if any(counts.values()):
                log.warning("intake_spool_replayed %s", json.dumps(counts))
        except Exception:
            log.exception("intake_spool_replay_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=REPLAY_EVERY)


def attach(application: Any, sessions: Any, environment: str, *, app_url: str) -> None:
    """Replay for the API's lifetime by wrapping its lifespan (servers only)."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app: Any) -> Any:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(
                run_replay(sessions, stop, app_url=app_url), name="lead-desk-intake-spool"
            )
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ac_platform.lead_desk.spool")
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - the container's own port
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    server = SpoolServer((args.host, args.port), root_path())
    print(json.dumps({"event": "intake_spool_started", "port": args.port}), flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
