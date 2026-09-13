"""Bounded server-side bot challenge verification for the public upload entry."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import SecretStr

from ac_platform.conversation_intelligence.application import ConversationDenied, utc

SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
UPLOAD_ACTION = "sales_xray_upload"
MAX_RESPONSE_BYTES = 16 * 1024


class UploadChallenge:
    def __init__(
        self,
        *,
        secret: SecretStr,
        hostname: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            not isinstance(secret, SecretStr)
            or not 1 <= len(secret.get_secret_value()) <= 256
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", hostname)
        ):
            raise ValueError("A configured upload challenge is required.")
        self._secret, self.hostname, self.clock = secret, hostname, clock

    async def verify(self, token: str) -> None:
        if not isinstance(token, str) or not 1 <= len(token) <= 2048:
            raise ConversationDenied("Please refresh the upload check and try again.")
        try:
            async with (
                asyncio.timeout(10),
                httpx.AsyncClient(
                    timeout=httpx.Timeout(8.0), follow_redirects=False, trust_env=False
                ) as client,
                client.stream(
                    "POST",
                    SITEVERIFY,
                    data={"secret": self._secret.get_secret_value(), "response": token},
                    headers={"accept": "application/json"},
                ) as response,
            ):
                if response.status_code != 200:
                    raise ValueError("challenge_unavailable")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ValueError("challenge_response_too_large")
                    body.extend(chunk)
            value = json.loads(body)
            if (
                type(value) is not dict
                or value.get("success") is not True
                or value.get("hostname") != self.hostname
                or value.get("action") != UPLOAD_ACTION
                or not isinstance(value.get("challenge_ts"), str)
            ):
                raise ValueError("challenge_rejected")
            challenged = datetime.fromisoformat(value["challenge_ts"].replace("Z", "+00:00"))
            if challenged.tzinfo is None:
                raise ValueError("challenge_clock_missing")
            age = utc(self.clock()) - challenged.astimezone(UTC)
            if not -timedelta(seconds=30) <= age < timedelta(minutes=5):
                raise ValueError("challenge_expired")
        except (httpx.HTTPError, ValueError, TypeError, UnicodeError, TimeoutError):
            # Neither upstream bodies nor exception strings may carry credentials
            # or challenge response tokens into the application error/log path.
            raise ConversationDenied("Please refresh the upload check and try again.") from None
