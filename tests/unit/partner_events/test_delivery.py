"""Signing, retry schedule and the signed POST (local MockTransport; no network, no DNS)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import socket
import stat
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from ac_platform.partner_events import delivery
from ac_platform.partner_events.delivery import (
    MAX_ATTEMPTS,
    Outcome,
    address_refusal,
    dead_letter_text,
    mask_url,
    notify_owner,
    post,
    public_address,
    read_secrets,
    retry_delay,
    signature,
    signature_header,
    url_allowed,
)

SECRET = b"whsec-fictional-test-secret"
NEXT = b"whsec-fictional-next-secret"
BODY = b'{"event_id":"6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11","schema":"sx.analysis_completed.v1"}'
T = 1760850842
URL = "https://hooks.example.test/sx"


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)


def test_signature_known_answer_vector() -> None:
    assert signature(SECRET, T, BODY) == (
        "03030e1ba33036a54e6259c9252f7ec1121a63fdc023853f52968b7fdd7eb159"
    )
    assert signature_header(T, BODY, [SECRET]) == (
        "t=1760850842,v1=03030e1ba33036a54e6259c9252f7ec1121a63fdc023853f52968b7fdd7eb159"
    )
    # During a rotation both secrets sign; a receiver accepts either.
    assert signature_header(T, BODY, [SECRET, NEXT]) == (
        "t=1760850842,v1=03030e1ba33036a54e6259c9252f7ec1121a63fdc023853f52968b7fdd7eb159"
        ",v1=dbb592058641b1bba1f0cb3a24976e2349ab02370dae4f41f23f14cd0272101a"
    )


def test_retry_schedule_doubles_from_10_seconds_to_an_hour() -> None:
    assert [retry_delay(n).total_seconds() for n in (1, 2, 3, 4, 9, 10, 11, 24)] == [
        10,
        20,
        40,
        80,
        2560,
        3600,
        3600,
        3600,
    ]
    # 25 attempts: 24 waits, about 16.4 hours of retries before the dead letter.
    total = sum((retry_delay(n) for n in range(1, MAX_ATTEMPTS)), timedelta())
    assert MAX_ATTEMPTS == 25
    assert total == timedelta(seconds=59_110)


@pytest.mark.parametrize(
    "url,environment,allowed",
    [
        ("https://hooks.example.test/sx", "production", True),
        ("https://hooks.example.test:8443/sx?x=1", "staging", True),
        ("http://127.0.0.1:8787/hook", "development", True),
        ("http://localhost:8787/hook", "test", True),
        ("http://127.0.0.1:8787/hook", "production", False),
        ("http://localhost/hook", "staging", False),
        ("http://hooks.example.test/sx", "development", False),
        ("https://user:pass@hooks.example.test/sx", "production", False),
        ("https://hooks.example.test/sx#frag", "production", False),
        ("ftp://hooks.example.test/sx", "development", False),
        ("https://", "production", False),
    ],
)
def test_url_policy(url: str, environment: str, allowed: bool) -> None:
    assert url_allowed(url, environment) is allowed


def test_masked_url_shows_scheme_host_and_port_only() -> None:
    assert mask_url("https://hooks.example.test/sx/secret-path?token=abc") == (
        "https://hooks.example.test/…"
    )
    assert mask_url("http://127.0.0.1:8787/hook") == "http://127.0.0.1:8787/…"


@pytest.mark.parametrize(
    "current,following,expected",
    [
        ("FICTIONAL", None, [SECRET]),
        ("FICTIONAL", "NEXT", [SECRET, NEXT]),
        # Review 18 Oct, item 9: a rotation with the next secret not yet set still signs.
        ("FICTIONAL", "MISSING", [SECRET]),
        ("MISSING", None, None),
        ("MISSING", "NEXT", None),
    ],
)
def test_secrets_come_from_the_named_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
    current: str,
    following: str | None,
    expected: list[bytes] | None,
) -> None:
    monkeypatch.setenv("AC_PARTNER_WEBHOOK_SECRET__FICTIONAL", SECRET.decode())
    monkeypatch.setenv("AC_PARTNER_WEBHOOK_SECRET__NEXT", NEXT.decode())
    monkeypatch.delenv("AC_PARTNER_WEBHOOK_SECRET__MISSING", raising=False)
    prefix = "AC_PARTNER_WEBHOOK_SECRET__"
    assert read_secrets(prefix + current, prefix + following if following else None) == expected


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


async def _post(handler: Any, **changes: Any) -> Outcome:
    values: dict[str, Any] = {
        "url": URL,
        "event_id": "e",
        "event_type": "analysis.completed",
        "body": BODY,
        "secrets": [SECRET],
        "environment": "development",
    }
    values.update(changes)
    async with _client(handler) as client:
        return await post(client, **values)


def test_signed_post_sends_exact_bytes_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, text="stored")

    outcome = run(
        _post(
            handler,
            event_id="6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11",
            secrets=[SECRET, NEXT],
            clock=lambda: float(T),
        )
    )
    assert outcome.delivered and outcome.http_status == 202 and outcome.error_code is None
    (request,) = seen
    assert request.method == "POST"
    assert request.content == BODY
    assert request.headers["X-SX-Event-Id"] == "6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11"
    assert request.headers["X-SX-Event-Type"] == "analysis.completed"
    assert request.headers["Content-Type"] == "application/json; charset=utf-8"
    # A receiver verifies with either secret over "<t>." + raw body.
    parts = request.headers["X-SX-Signature"].split(",")
    assert parts[0] == f"t={T}"
    for secret, part in zip((SECRET, NEXT), parts[1:], strict=True):
        expected = hmac.new(secret, f"{T}.".encode() + request.content, hashlib.sha256)
        assert part == "v1=" + expected.hexdigest()


@pytest.mark.parametrize(
    "response,error",
    [
        (httpx.Response(500), "http_status"),
        (
            httpx.Response(302, headers={"Location": "https://elsewhere.example.test/"}),
            "http_status",
        ),
        (httpx.Response(404), "http_status"),
    ],
)
def test_non_2xx_is_a_failure_and_redirects_are_not_followed(
    response: httpx.Response, error: str
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return response

    outcome = run(_post(handler))
    assert not outcome.delivered
    assert outcome.error_code == error and outcome.http_status == response.status_code
    assert calls == [URL]


@pytest.mark.parametrize(
    "exception,error",
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connect_error"),
        (httpx.RemoteProtocolError("broken"), "transport_error"),
        # Review 18 Oct, item 10: not an httpx.HTTPError; these escaped and crashed the runner.
        (httpx.InvalidURL("bad"), "client_error"),
        (ValueError("odd"), "client_error"),
        (RuntimeError("odd"), "client_error"),
    ],
)
def test_send_failures_have_content_free_codes(exception: Exception, error: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    outcome = run(_post(handler))
    assert outcome.http_status is None and outcome.error_code == error


@pytest.mark.parametrize(
    "url",
    ["https://hooks.example.test:port/sx", "https://[::1/sx"],
)
def test_an_invalid_url_is_a_client_error_not_a_crash(url: str) -> None:
    with pytest.raises(httpx.InvalidURL):
        httpx.URL(url)  # httpx refuses it outside its HTTPError family
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    outcome = run(_post(handler, url=url))
    assert outcome.http_status is None and outcome.error_code == "client_error"
    assert sent == []


class _Endless(httpx.AsyncByteStream):
    """A response body that would never end; reading it fails the test."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        raise AssertionError("the response body must never be read")
        yield b""  # pragma: no cover


def test_the_response_body_is_never_read() -> None:
    outcome = run(_post(lambda request: httpx.Response(200, stream=_Endless())))
    assert outcome.delivered and outcome.http_status == 200


def test_a_slow_endpoint_stops_at_the_wall_clock_budget() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    outcome = run(_post(handler, budget=0.05))
    assert outcome.http_status is None and outcome.error_code == "timeout"
    assert outcome.duration_ms < 2_000


def _resolver(*addresses: str, error: Exception | None = None) -> Any:
    asked: list[tuple[str, int]] = []

    async def resolve(host: str, port: int) -> list[str]:
        asked.append((host, port))
        if error is not None:
            raise error
        return list(addresses)

    resolve.asked = asked  # type: ignore[attr-defined]
    return resolve


@pytest.mark.parametrize(
    "addresses,error,code",
    [
        (("93.184.216.34",), None, None),
        (("2606:2800:220:1:248:1893:25c8:1946",), None, None),
        (("10.0.0.5",), None, "address_refused"),
        (("192.168.1.10",), None, "address_refused"),
        (("172.16.0.1",), None, "address_refused"),
        (("127.0.0.1",), None, "address_refused"),
        (("169.254.169.254",), None, "address_refused"),
        (("100.64.0.1",), None, "address_refused"),
        (("0.0.0.0",), None, "address_refused"),  # noqa: S104 - an address to refuse
        (("::1",), None, "address_refused"),
        (("fe80::1",), None, "address_refused"),
        (("fd00::1",), None, "address_refused"),
        (("::ffff:127.0.0.1",), None, "address_refused"),
        (("224.0.0.1",), None, "address_refused"),
        (("93.184.216.34", "10.0.0.5"), None, "address_refused"),
        ((), None, "dns_error"),
        ((), socket.gaierror("no such host"), "dns_error"),
    ],
)
def test_outside_development_only_public_addresses_are_sent_to(
    addresses: tuple[str, ...], error: Exception | None, code: str | None
) -> None:
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200)

    resolve = _resolver(*addresses, error=error)
    outcome = run(_post(handler, environment="production", resolve=resolve))
    assert resolve.asked == [("hooks.example.test", 443)]
    assert outcome.error_code == code
    assert sent == ([URL] if code is None else [])


def test_development_sends_to_loopback_without_a_lookup() -> None:
    resolve = _resolver(error=AssertionError("no lookup in development"))
    outcome = run(
        _post(
            lambda request: httpx.Response(204),
            url="http://127.0.0.1:8787/hook",
            resolve=resolve,
        )
    )
    assert outcome.delivered and resolve.asked == []


def test_address_refusal_reads_the_port_and_refuses_hostless_urls() -> None:
    resolve = _resolver("93.184.216.34")
    assert run(address_refusal("https://hooks.example.test:8443/x", resolve)) is None
    assert resolve.asked == [("hooks.example.test", 8443)]
    assert run(address_refusal("https:///x", resolve)) == "url_refused"


@pytest.mark.parametrize(
    "value,public",
    [("8.8.8.8", True), ("10.1.2.3", False), ("::ffff:10.1.2.3", False), ("fe80::1%eth0", False),
     ("not-an-address", False)],
)  # fmt: skip
def test_public_address(value: str, public: bool) -> None:
    assert public_address(value) is public


def _fake_notifier(tmp_path: Path, exit_code: int = 0) -> Path:
    script = tmp_path / "ac-notify-owner"
    record = tmp_path / "record.txt"
    script.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$1" > "{record}"\nenv >> "{record}"\nexit {exit_code}\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_owner_alert_runs_the_host_command_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AC_PARTNER_WEBHOOK_SECRET__FICTIONAL", SECRET.decode())
    monkeypatch.setenv("GEMINI_API_KEY", "fictional-key")
    monkeypatch.setattr(delivery, "NOTIFY_OWNER", str(_fake_notifier(tmp_path)))
    event = UUID("6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11")
    endpoint = UUID("452a62d8-0000-4000-8000-000000000001")
    text = dead_letter_text("production", endpoint, event, 25)
    assert notify_owner(text) == "sent"
    record = (tmp_path / "record.txt").read_text()
    assert record.splitlines()[0] == text
    assert "endpoint 452a62d8, event 6b6b1a0e, 25 attempts" in text
    assert SECRET.decode() not in record and "fictional-key" not in record


def test_owner_alert_is_best_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delivery, "NOTIFY_OWNER", str(tmp_path / "missing"))
    assert notify_owner("x") == "absent"
    monkeypatch.setattr(delivery, "NOTIFY_OWNER", str(_fake_notifier(tmp_path, exit_code=3)))
    assert notify_owner("x") == "failed"
