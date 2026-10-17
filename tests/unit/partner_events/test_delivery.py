"""Signing, retry schedule and the signed POST (local MockTransport; no network)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Any

import httpx
import pytest

from ac_platform.partner_events.delivery import (
    MAX_ATTEMPTS,
    mask_url,
    post,
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


def test_secrets_come_from_the_named_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AC_PARTNER_WEBHOOK_SECRET__FICTIONAL", SECRET.decode())
    monkeypatch.delenv("AC_PARTNER_WEBHOOK_SECRET__MISSING", raising=False)
    assert read_secrets("AC_PARTNER_WEBHOOK_SECRET__FICTIONAL", None) == [SECRET]
    assert read_secrets("AC_PARTNER_WEBHOOK_SECRET__MISSING", None) is None
    assert (
        read_secrets("AC_PARTNER_WEBHOOK_SECRET__FICTIONAL", "AC_PARTNER_WEBHOOK_SECRET__MISSING")
        is None
    )


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_signed_post_sends_exact_bytes_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, text="stored")

    with _client(handler) as client:
        outcome = post(
            client,
            url="https://hooks.example.test/sx",
            event_id="6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11",
            event_type="analysis.completed",
            body=BODY,
            secrets=[SECRET, NEXT],
            clock=lambda: float(T),
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

    with _client(handler) as client:
        outcome = post(
            client,
            url="https://hooks.example.test/sx",
            event_id="e",
            event_type="analysis.completed",
            body=BODY,
            secrets=[SECRET],
        )
    assert not outcome.delivered
    assert outcome.error_code == error and outcome.http_status == response.status_code
    assert calls == ["https://hooks.example.test/sx"]


@pytest.mark.parametrize(
    "exception,error",
    [
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.ConnectError("refused"), "connect_error"),
        (httpx.RemoteProtocolError("broken"), "transport_error"),
    ],
)
def test_transport_failures_have_content_free_codes(exception: Exception, error: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with _client(handler) as client:
        outcome = post(
            client,
            url="https://hooks.example.test/sx",
            event_id="e",
            event_type="analysis.completed",
            body=BODY,
            secrets=[SECRET],
        )
    assert outcome.http_status is None and outcome.error_code == error
