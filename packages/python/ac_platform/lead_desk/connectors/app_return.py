"""Connect from the Sales Xray app: Meta and Google sign in only in the phone's browser.

Facebook and Google refuse their sign-in inside an app's web view, so in the app a
Connect opens in the system browser (a Custom Tab on Android), which has no Sales Xray
session. The flow:

1. The page (signed in, inside the app) keeps a random verifier and asks for the
   provider's sign-in address with ``app_challenge`` = SHA-256 of it. The signed state
   carries the challenge with the workspace and person.
2. The app opens that address in the system browser. The provider returns to our
   callback there; seeing an app state, the callback swaps nothing and needs no
   session: it seals the provider's one-time code with the state (AES-GCM, 10
   minutes) and sends the browser to the app at
   ``com.authorityclosers.salesxray:/connect/return`` with the sealed hand-off in the
   fragment (``return_page``).
3. The app opens the Leads page with the sealed hand-off in the fragment; the page
   posts it with its verifier to ``…/app-complete`` on its own session. The server
   checks the state is this person's in this workspace and that the verifier answers
   the challenge, then swaps the code and connects, exactly as the web callback does.

A stolen hand-off is useless without the verifier, which never leaves the app's page,
and the person's own session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from typing import Any, Final, Literal
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["meta", "google", "whatsapp"]
APP_RETURN: Final[str] = "com.authorityclosers.salesxray:/connect/return"
HANDOFF_SECONDS: Final[int] = 10 * 60
CHALLENGE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{43}$")
VERIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
HANDOFF: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{20,8192}$")
RESULT: Final[re.Pattern[str]] = re.compile(r"^[a-z_]{1,32}$")
# Where the app opens the page that finishes each Connect.
RETURN_PATHS: Final[dict[str, str]] = {
    "meta": "/leads?tab=sources",
    "google": "/leads?tab=sources",
    "whatsapp": "/organisation?tab=integrations",
}


class HandoffError(ValueError):
    """A hand-off that can't finish a Connect; the message is safe to show."""


class AppComplete(BaseModel):
    """The app came back from the provider: the sealed hand-off and the page's verifier."""

    model_config = ConfigDict(extra="forbid")
    handoff: str = Field(min_length=20, max_length=8192)
    verifier: str = Field(min_length=43, max_length=128)


class AppCompleted(BaseModel):
    result: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def challenge_of(verifier: str) -> str:
    """The challenge a verifier answers: unpadded base64url of its SHA-256."""
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def answers(challenge: object, verifier: str) -> bool:
    if not isinstance(challenge, str) or not CHALLENGE.fullmatch(challenge):
        return False
    if not VERIFIER.fullmatch(verifier):
        return False
    return hmac.compare_digest(challenge_of(verifier), challenge)


def seal(key: bytes, *, provider: Provider, code: str, state: str, now: float | None = None) -> str:
    """The provider's code and our state, sealed for the app (10 minutes, one Connect)."""
    body = json.dumps(
        {"c": code, "s": state, "x": int((now or time.time()) + HANDOFF_SECONDS)},
        separators=(",", ":"),
    ).encode()
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(key).encrypt(nonce, body, f"app-connect:{provider}".encode())
    return _b64(nonce + sealed)


def open_(
    key: bytes, handoff: str, *, provider: Provider, now: float | None = None
) -> tuple[str, str]:
    """The code and state inside a hand-off, if it is ours, for this provider and fresh."""
    if not HANDOFF.fullmatch(handoff):
        raise HandoffError("That didn't finish. Connect again from Sales Xray.")
    try:
        raw = _unb64(handoff)
        body = json.loads(
            AESGCM(key).decrypt(raw[:12], raw[12:], f"app-connect:{provider}".encode())
        )
    except Exception:  # noqa: BLE001 - any failure means the hand-off can't be used
        raise HandoffError("That didn't finish. Connect again from Sales Xray.") from None
    if int(body.get("x", 0)) < (now or time.time()):
        raise HandoffError("That took too long. Connect again from Sales Xray.")
    code, state = body.get("c"), body.get("s")
    if not isinstance(code, str) or not isinstance(state, str) or not code or not state:
        raise HandoffError("That didn't finish. Connect again from Sales Xray.")
    return code, state


def return_page(
    provider: Provider, *, handoff: str | None = None, result: str | None = None
) -> HTMLResponse:
    """A small page that sends the browser back to the app with the outcome.

    As the app's Google sign-in does (http/auth.py): the hand-off travels in the
    page body, never in a Location header, so it stays out of edge access logs;
    the /v1 policy allows no script or style, so a meta refresh opens the app and
    the link is the manual fallback.
    """
    parts: dict[str, Any] = {"provider": provider, "path": RETURN_PATHS[provider]}
    if handoff is not None:
        parts["handoff"] = handoff
    else:
        parts["result"] = result if result and RESULT.fullmatch(result) else "failed"
    fragment = "&".join(
        f"{name}={value}" if name != "path" else f"path={_quote(str(value))}"
        for name, value in parts.items()
    )
    target = f"{APP_RETURN}#{fragment}"
    link = html.escape(target, quote=True)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="0;url={link}">'
        "<title>Back to Sales Xray</title></head><body>"
        f'<p><a href="{link}">Back to the Sales Xray app</a></p>'
        "</body></html>"
    )
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


def _quote(path: str) -> str:
    return quote(path, safe="/")
