"""Challenge failures cannot admit a guest or leak an upstream secret/body."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from ac_platform.conversation_intelligence.acquisition_challenge import (
    SITEVERIFY,
    UPLOAD_ACTION,
    UploadChallenge,
)
from ac_platform.conversation_intelligence.application import ConversationDenied

NOW = datetime(2026, 9, 14, tzinfo=UTC)
HOST = "salesxray.example.test"


def _response(**changes):
    return {
        "success": True,
        "hostname": HOST,
        "action": UPLOAD_ACTION,
        "challenge_ts": NOW.isoformat(),
        **changes,
    }


def _verify(monkeypatch, payload, *, status=200):
    secret, challenge = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    calls = []

    def request(req):
        calls.append(req)
        assert str(req.url) == SITEVERIFY
        assert req.method == "POST"
        assert secret.encode() in req.content and challenge.encode() in req.content
        assert "remoteip" not in req.content.decode()
        return httpx.Response(status, content=json.dumps(payload).encode())

    real_client = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return real_client(transport=httpx.MockTransport(request), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    verifier = UploadChallenge(secret=SecretStr(secret), hostname=HOST, clock=lambda: NOW)
    return verifier, challenge, calls


def test_only_current_success_for_the_exact_host_and_action_passes(monkeypatch):
    verifier, token, calls = _verify(monkeypatch, _response())
    asyncio.run(verifier.verify(token))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"success": False},
        {"success": "true"},
        {"success": 1},
        {"hostname": "other.example.test"},
        {"action": "login"},
        {"challenge_ts": (NOW - timedelta(minutes=5)).isoformat()},
        {"challenge_ts": (NOW + timedelta(minutes=1)).isoformat()},
        {"challenge_ts": "2026-09-14T00:00:00"},
        {"challenge_ts": None},
    ],
)
def test_rejection_stale_and_wrong_scope_are_sanitized(monkeypatch, changes):
    verifier, token, calls = _verify(monkeypatch, _response(**changes))
    with pytest.raises(ConversationDenied) as failure:
        asyncio.run(verifier.verify(token))
    assert token not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [301, 307, 401, 429, 500])
def test_no_redirect_or_http_error_is_accepted(monkeypatch, status):
    verifier, token, _ = _verify(monkeypatch, _response(), status=status)
    with pytest.raises(ConversationDenied):
        asyncio.run(verifier.verify(token))


def test_response_is_bounded_before_parsing(monkeypatch):
    verifier, token, _ = _verify(monkeypatch, _response(detail="x" * 16384))
    with pytest.raises(ConversationDenied):
        asyncio.run(verifier.verify(token))


def test_invalid_token_does_not_call_provider(monkeypatch):
    verifier, _, calls = _verify(monkeypatch, _response())
    for value in ("", "x" * 2049, None, False):
        with pytest.raises(ConversationDenied):
            asyncio.run(verifier.verify(value))
    assert calls == []
