"""The release spool (lead_desk/spool.py): what it takes, keeps and answers during a hold."""

from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import logging
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.lead_desk import spool

SOURCE = "6f1c2a4e-7d1b-4c3e-9a55-2b8e1f0d9c11"
PATH = f"/v1/lead-desk/capture/{SOURCE}"
KEY = "fictional-source-key-123"
NOW = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_a_website_form_keeps_its_lead_and_only_the_keys_hash() -> None:
    body = json.dumps({"name": "Fictional Lead", "phone": "98765 00011", "key": KEY}).encode()
    entry = spool.entry_for(
        PATH, "", {"X-Lead-Desk-Key": KEY, "Content-Type": "application/json"}, body, NOW
    )
    assert entry["source_id"] == SOURCE
    assert entry["google"] is False
    assert entry["key_sha256"] == _sha(KEY)
    assert entry["received_at"] == NOW.isoformat()
    assert entry["lead"] == {"name": "Fictional Lead", "phone": "98765 00011"}
    assert KEY not in json.dumps(entry)


def test_the_key_comes_as_the_api_takes_it_bearer_or_query_and_a_form_body_reads() -> None:
    form = b"name=Fictional+Lead&phone=98765+00012"
    bearer = spool.entry_for(
        PATH,
        "",
        {"Authorization": f"Bearer {KEY}", "Content-Type": "application/x-www-form-urlencoded"},
        form,
        NOW,
    )
    assert bearer["key_sha256"] == _sha(KEY)
    assert bearer["lead"] == {"name": "Fictional Lead", "phone": "98765 00012"}
    query = spool.entry_for(PATH, f"key={KEY}", {}, b'{"name": "Fictional"}', NOW)
    assert query["key_sha256"] == _sha(KEY)


def test_google_ads_keeps_the_answers_and_hashes_its_key() -> None:
    payload = {
        "lead_id": "fictional-1",
        "google_key": KEY,
        "user_column_data": [{"column_id": "FULL_NAME", "string_value": "Fictional Lead"}],
    }
    entry = spool.entry_for(f"{PATH}/google-ads", "", {}, json.dumps(payload).encode(), NOW)
    assert entry["google"] is True
    assert entry["key_sha256"] == _sha(KEY)
    assert "google_key" not in entry["lead"]
    assert entry["lead"]["user_column_data"] == payload["user_column_data"]
    assert KEY not in json.dumps(entry)


@pytest.mark.parametrize(
    ("path", "query", "headers", "body", "status"),
    [
        ("/v1/lead-desk/leads", "", {}, b"{}", 404),
        (f"{PATH}/other", "", {}, b"{}", 404),
        (PATH, "", {}, b'{"name": "x"}', 401),
        (PATH, "", {"X-Lead-Desk-Key": "k" * 129}, b"{}", 401),
        (PATH, "", {"X-Lead-Desk-Key": KEY}, b"[1, 2]", 422),
        (PATH, "", {"X-Lead-Desk-Key": KEY}, b"not json", 422),
        (PATH, "", {"X-Lead-Desk-Key": KEY}, b"{" + b" " * spool.MAX_BODY + b"}", 413),
        (f"{PATH}/google-ads", "", {}, b'{"user_column_data": [{}]}', 422),
        (f"{PATH}/google-ads", "", {}, json.dumps({"google_key": KEY}).encode(), 422),
    ],
)
def test_it_refuses_what_the_api_would(
    path: str, query: str, headers: dict[str, str], body: bytes, status: int
) -> None:
    with pytest.raises(spool.Refused) as refused:
        spool.entry_for(path, query, headers, body, NOW)
    assert refused.value.status == status


def test_a_lead_is_written_whole_private_and_a_full_spool_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spool.prepare(tmp_path)
    entry = spool.entry_for(PATH, "", {"X-Lead-Desk-Key": KEY}, b'{"name": "Fictional"}', NOW)
    written = spool.write(tmp_path, entry)
    assert written.parent == tmp_path / "new"
    assert written.stat().st_mode & 0o777 == 0o600
    assert json.loads(written.read_text()) == entry
    assert list((tmp_path / "tmp").iterdir()) == []
    monkeypatch.setattr(spool, "MAX_WAITING", 1)
    with pytest.raises(spool.Refused) as full:
        spool.write(tmp_path, entry)
    assert full.value.status == 503


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[spool.SpoolServer]:
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    running = spool.SpoolServer(("127.0.0.1", 0), tmp_path)
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    yield running
    running.shutdown()
    running.server_close()


def _ask(
    server: spool.SpoolServer, method: str, path: str, body: bytes = b"", **headers: str
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        connection.request(method, path, body=body or None, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_the_server_answers_a_capture_post_as_the_api_does(server: spool.SpoolServer) -> None:
    body = b'{"name": "Fictional Lead", "phone": "98765 00013"}'
    status, headers, answer = _ask(
        server, "POST", PATH, body, **{"X-Lead-Desk-Key": KEY, "Content-Type": "application/json"}
    )
    assert status == 202
    assert json.loads(answer) == {"received": True, "outcome": "queued", "lead_id": None}
    assert headers["Cache-Control"] == "no-store"
    [kept] = list((server.root / "new").iterdir())
    assert json.loads(kept.read_text())["lead"]["name"] == "Fictional Lead"
    for path in server.root.rglob("*"):
        if path.is_file():
            assert KEY.encode() not in path.read_bytes()


def test_the_server_holds_everything_else_and_reports_its_health(
    server: spool.SpoolServer,
) -> None:
    assert _ask(server, "GET", "/health")[0] == 200
    status, headers, answer = _ask(server, "GET", PATH)
    assert status == 503 and headers["Retry-After"] == "30"
    assert answer == b"Authority Closers staging is completing a reviewed release.\n"
    assert _ask(server, "POST", PATH, b'{"name": "x"}')[0] == 401
    assert _ask(server, "POST", "/v1/lead-desk/leads", b"{}", **{"X-Lead-Desk-Key": KEY})[0] == 404
    assert list((server.root / "new").iterdir()) == []


def test_one_address_is_held_to_a_rate(
    server: spool.SpoolServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spool, "PER_ADDRESS", 2)
    statuses = [
        _ask(server, "POST", PATH, b'{"name": "Fictional"}', **{"X-Lead-Desk-Key": KEY})[0]
        for _ in range(3)
    ]
    assert statuses == [202, 202, 429]


def _raw(server: spool.SpoolServer, request: bytes, wait: float = 5) -> bytes:
    """Send bytes as they are; return all the server answers before it closes."""
    with socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=wait) as sock:
        sock.sendall(request)
        answer = b""
        while chunk := sock.recv(4096):
            answer += chunk
            if b"\r\n\r\n" in answer and answer.endswith(b"}"):
                break
        return answer


def _post(headers: str, body: bytes) -> bytes:
    return (
        f"POST {PATH} HTTP/1.1\r\nHost: spool\r\nX-Lead-Desk-Key: {KEY}\r\n"
        f"Content-Type: application/json\r\nConnection: close\r\n{headers}\r\n"
    ).encode() + body


def test_a_chunked_body_is_read_as_the_api_reads_it(server: spool.SpoolServer) -> None:
    body = b'{"name": "Fictional Chunked", "phone": "98765 00031"}'
    chunked = b"".join(
        f"{len(part):x}\r\n".encode() + part + b"\r\n" for part in (body[:20], body[20:])
    )
    answer = _raw(server, _post("Transfer-Encoding: chunked\r\n", chunked + b"0\r\n\r\n"))
    assert answer.startswith(b"HTTP/1.1 202"), answer
    [kept] = list((server.root / "new").iterdir())
    assert json.loads(kept.read_text())["lead"]["name"] == "Fictional Chunked"

    huge = f"{spool.MAX_BODY + 1:x}\r\n".encode()
    assert _raw(server, _post("Transfer-Encoding: chunked\r\n", huge)).startswith(b"HTTP/1.1 413")
    broken = b"zz\r\n{}\r\n0\r\n\r\n"
    assert _raw(server, _post("Transfer-Encoding: chunked\r\n", broken)).startswith(b"HTTP/1.1 400")
    assert len(list((server.root / "new").iterdir())) == 1


def test_a_stalled_sender_frees_its_thread(
    server: spool.SpoolServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert spool._Handler.timeout == 15 and spool.BODY_SECONDS == 15
    monkeypatch.setattr(spool, "BODY_SECONDS", 0.5)
    started = time.monotonic()
    # Says 100 bytes, sends 10, then waits: the spool drops it at the deadline.
    answer = _raw(server, _post("Content-Length: 100\r\n", b'{"name": "'), wait=10)
    assert answer == b"" and time.monotonic() - started < 5
    assert list((server.root / "new").iterdir()) == []


@pytest.mark.parametrize(
    ("peer", "cloudflare"),
    [
        ("172.18.0.2", ["198.51.100.7"]),
        ("172.18.0.2", ["2001:db8:1:2:3:4:5:6"]),
        ("172.18.0.2", ["::ffff:198.51.100.9"]),
        ("172.18.0.2", ["198.51.100.7", "198.51.100.8"]),
        ("172.18.0.2", ["not an address"]),
        ("172.18.0.2", []),
        ("172.18.0.9", ["198.51.100.7"]),
        ("2001:db8:9:9::1", []),
    ],
)
def test_the_sender_is_read_as_the_apis_limiter_reads_it(peer: str, cloudflare: list[str]) -> None:
    from ac_platform.http.rate_limits import client_identity

    edge = spool.trusted({"AC_TRUSTED_PROXY_ADDRESSES": "172.18.0.2"})
    scope = {
        "type": "http",
        "client": (peer, 443),
        "headers": [(b"cf-connecting-ip", value.encode()) for value in cloudflare],
    }
    assert spool.sender(peer, cloudflare, edge) == client_identity(
        scope, trusted_proxy_addresses=edge
    )


def test_the_rate_is_per_cloudflare_address_never_a_forwarded_one(
    server: spool.SpoolServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spool, "PER_ADDRESS", 2)
    # The test's peer stands in for the edge router.
    server.trusted = spool.trusted({"AC_TRUSTED_PROXY_ADDRESSES": "127.0.0.1"})

    def ask(**headers: str) -> int:
        body = b'{"name": "Fictional"}'
        return _ask(server, "POST", PATH, body, **{"X-Lead-Desk-Key": KEY, **headers})[0]

    # A sender that rotates X-Forwarded-For is still one address.
    assert [ask(**{"X-Forwarded-For": f"203.0.113.{n}"}) for n in range(3)] == [202, 202, 429]
    # Cloudflare's own header tells real senders apart.
    first, second = {"CF-Connecting-IP": "198.51.100.7"}, {"CF-Connecting-IP": "198.51.100.8"}
    assert [ask(**first), ask(**first), ask(**second), ask(**first)] == [202, 202, 202, 429]
    # From anyone but the edge router, the header is the sender's own words.
    server.trusted = frozenset()
    assert ask(**{"CF-Connecting-IP": "198.51.100.10"}) == 429


class _Database:
    async def __aenter__(self) -> _Database:
        return self

    async def __aexit__(self, *error: object) -> None:
        return None

    def begin(self) -> _Database:
        return self


def test_a_filed_lead_leaves_no_copy_and_one_failing_for_a_day_is_set_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from ac_platform.lead_desk.intake import Intake

    spool.prepare(tmp_path)
    now = datetime.now(UTC)
    for name, age in (("Fictional Filed", 5), ("Fictional Waiting", 5), ("Fictional Old", 25 * 60)):
        body = json.dumps({"name": name}).encode()
        entry = spool.entry_for(
            PATH, "", {"X-Lead-Desk-Key": KEY}, body, now - timedelta(minutes=age)
        )
        spool.write(tmp_path, entry)

    async def capture(database: Any, source_id: Any, token: str, record: Any, **_: Any) -> Any:
        if record["name"] == "Fictional Filed":
            return uuid4(), "created"
        raise RuntimeError("the database is away")

    monkeypatch.setattr(Intake, "capture", staticmethod(capture))

    def replay() -> dict[str, int]:
        return asyncio.run(spool.replay(_Database, tmp_path, app_url="https://x.test"))

    with caplog.at_level(logging.ERROR, logger=spool.__name__):
        assert replay() == {"filed": 1, "known": 0, "rejected": 1, "kept": 1}
        assert replay() == {"filed": 0, "known": 0, "rejected": 0, "kept": 1}
    gave_up = [record for record in caplog.records if "intake_spool_gave_up" in record.getMessage()]
    assert len(gave_up) == 1 and "Fictional" not in gave_up[0].getMessage()
    names = {
        folder: sorted(
            json.loads(path.read_text())["lead"]["name"] for path in (tmp_path / folder).iterdir()
        )
        for folder in ("new", "rejected")
    }
    assert names == {"new": ["Fictional Waiting"], "rejected": ["Fictional Old"]}
    assert not (tmp_path / "done").exists()
    assert set(spool.FOLDERS) == {"tmp", "new", "rejected"}
