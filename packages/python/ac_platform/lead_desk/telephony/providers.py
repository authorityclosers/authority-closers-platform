"""Cloud telephony for company-number calls: the click-to-call bridge.

The provider rings the seller's own mobile first. When the seller picks up, it plays
the recording notice to the lead, rings the lead and joins the two. The lead sees the
company number. Both legs are ordinary phone calls placed by a licensed operator, so
the app needs no microphone and no phone permission, and the recording has one channel
per side (seller, lead).

- **Exotel** is first (owner, 27 Oct 2026: "Bridge via Exotel (Plivo second)").
- **Plivo** has the same shape and isn't wired yet.
- **``FakeProvider``** stands in for tests, and for development before the keys exist.

This module doesn't decide who may be called or what a call may cost (``policy``), and it
stores nothing (``ledger``). Errors carry words a person can be shown.
"""

from __future__ import annotations

import math
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import quote, urlparse

import httpx
import structlog

events = structlog.get_logger(__name__)

STATUSES: Final[dict[str, str]] = {
    "queued": "queued",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "in_progress": "in_progress",
    "completed": "completed",
    "busy": "busy",
    "no-answer": "no_answer",
    "no_answer": "no_answer",
    "failed": "failed",
    "canceled": "canceled",
    "cancelled": "canceled",
}
FINAL: Final[frozenset[str]] = frozenset({"completed", "busy", "no_answer", "failed", "canceled"})
# A leg that was picked up (Exotel's Leg1Status / Leg2Status and per-leg Status).
ANSWERED: Final[frozenset[str]] = frozenset({"completed", "in-progress", "in_progress", "answered"})
MAX_RECORDING: Final[int] = 60 * 1024 * 1024
_SID: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class TelephonyError(Exception):
    """A call that couldn't be placed or read; the message is safe to show a person."""

    def __init__(self, message: str, *, status: int = 502, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(frozen=True, slots=True)
class BridgeRequest:
    seller: str  # E.164: rung first
    lead: str  # E.164
    caller_id: str  # the company number the lead sees
    reference: str  # our call id, echoed back by the provider
    status_url: str | None  # the provider's status webhook; None: we poll instead
    notice_url: str | None  # played to the lead before the two are joined
    time_limit: int  # seconds; the spend guard sets it
    record: bool = True


@dataclass(frozen=True, slots=True)
class ProviderCall:
    sid: str
    status: str


@dataclass(frozen=True, slots=True)
class CallReport:
    """What the provider says about one call, in our words."""

    sid: str
    status: str
    seller_answered: bool | None = None
    lead_answered: bool | None = None
    talk_seconds: int | None = None
    total_seconds: int | None = None
    leg_seconds: tuple[int, ...] = ()
    price_paise: int | None = None
    recording_url: str | None = None

    @property
    def final(self) -> bool:
        return self.status in FINAL


@dataclass(frozen=True, slots=True)
class Recording:
    content: bytes
    content_type: str


class Provider(Protocol):
    name: str
    label: str
    real: bool  # places real phone calls

    async def start_bridge(self, request: BridgeRequest) -> ProviderCall: ...

    async def report(self, sid: str) -> CallReport: ...

    async def fetch_recording(self, url: str) -> Recording: ...


def normal_status(raw: object) -> str:
    return STATUSES.get(str(raw or "").strip().lower(), "queued")


def _int(raw: object) -> int | None:
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or value < 0:
        return None
    return int(round(value))


def _paise(raw: object) -> int | None:
    """Exotel's price in rupees ("1.25") as paise; None while it isn't known yet."""
    try:
        rupees = float(str(raw))
    except (TypeError, ValueError):
        return None
    if math.isnan(rupees) or rupees < 0:
        return None
    return int(round(abs(rupees) * 100))


# ----- Exotel --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExotelConfig:
    sid: str
    api_key: str
    api_token: str
    subdomain: str

    @property
    def base(self) -> str:
        return f"https://{self.subdomain}/v1/Accounts/{quote(self.sid, safe='')}"


def exotel_config(env: Mapping[str, str] | None = None) -> ExotelConfig | None:
    """Exotel's keys, or None while any is missing (company calling stays off)."""
    env = os.environ if env is None else env
    names = (
        "AC_TELEPHONY_EXOTEL_SID",
        "AC_TELEPHONY_EXOTEL_API_KEY",
        "AC_TELEPHONY_EXOTEL_API_TOKEN",
    )
    values = {name: (env.get(name) or "").strip() for name in names}
    if not all(values.values()):
        return None
    subdomain = (env.get("AC_TELEPHONY_EXOTEL_SUBDOMAIN") or "api.exotel.com").strip().lower()
    subdomain = subdomain.removeprefix("https://").removeprefix("http://").split("/")[0]
    if not subdomain.endswith((".exotel.com", ".exotel.in")):
        return None
    return ExotelConfig(
        sid=values["AC_TELEPHONY_EXOTEL_SID"],
        api_key=values["AC_TELEPHONY_EXOTEL_API_KEY"],
        api_token=values["AC_TELEPHONY_EXOTEL_API_TOKEN"],
        subdomain=subdomain,
    )


# Exotel's 409 codes for the first leg (the seller's phone).
_EXOTEL_CODES: Final[dict[str, str]] = {
    "1012": "Your phone seems to be switched off. Turn it on, then call again.",
    "10706": "Your phone is on another call. Call again when it's free.",
}


def _exotel_refusal(response: httpx.Response) -> TelephonyError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    rest = body.get("RestException") if isinstance(body, dict) else None
    code = str((rest or {}).get("Code") or "") if isinstance(rest, dict) else ""
    said = str((rest or {}).get("Message") or "")[:200] if isinstance(rest, dict) else ""
    events.info(
        "lead_desk_company_call_refused",
        provider="exotel",
        http=response.status_code,
        code=code or None,
        said=said or None,
    )
    if response.status_code in {401, 403}:
        return TelephonyError(
            "Company calling isn't set up right: the calling service refused our keys.",
            status=503,
            code="keys",
        )
    if response.status_code == 429:
        return TelephonyError(
            "Too many calls at once. Try again in a minute.", status=429, code="busy"
        )
    if code in _EXOTEL_CODES:
        return TelephonyError(_EXOTEL_CODES[code], status=409, code=code)
    if response.status_code == 404:
        return TelephonyError("The calling service doesn't know this call.", status=404)
    if response.status_code < 500:
        return TelephonyError("The calling service couldn't place this call.", code=code or None)
    return TelephonyError("The calling service had a problem. Try again in a minute.")


def exotel_report(call: Mapping[str, Any]) -> CallReport:
    """Exotel's call details (``GET …/Calls/{sid}.json?details=true``, or a status
    webhook's body) in our words."""
    details_raw = call.get("Details")
    details: Mapping[str, Any] = details_raw if isinstance(details_raw, Mapping) else {}
    talk = _int(details.get("ConversationDuration", call.get("ConversationDuration")))
    total = _int(call.get("Duration"))
    legs_raw = details.get("Legs", call.get("Legs"))
    legs: list[Mapping[str, Any]] = []
    if isinstance(legs_raw, list):
        for item in legs_raw:
            if isinstance(item, Mapping):
                inner = item.get("Leg")
                legs.append(inner if isinstance(inner, Mapping) else item)
    leg_seconds = tuple(
        value for value in (_int(leg.get("OnCallDuration")) for leg in legs) if value is not None
    )
    statuses = [str(leg.get("Status") or "").lower() for leg in legs]

    def answered(index: int, key: str) -> bool | None:
        said = str(details.get(key) or "").lower()
        if not said and index < len(statuses):
            said = statuses[index]
        if said:
            return said in ANSWERED or (index == 1 and bool(talk))
        return True if talk else None

    url = str(call.get("RecordingUrl") or "").strip() or None
    return CallReport(
        sid=str(call.get("Sid") or call.get("CallSid") or ""),
        status=normal_status(call.get("Status")),
        seller_answered=answered(0, "Leg1Status"),
        lead_answered=answered(1, "Leg2Status"),
        talk_seconds=talk,
        total_seconds=total,
        leg_seconds=leg_seconds,
        price_paise=_paise(call.get("Price")),
        recording_url=url,
    )


class ExotelProvider:
    """Exotel's Connect API: two numbers, the first one rung first."""

    name = "exotel"
    label = "Exotel"
    real = True

    def __init__(
        self, cfg: ExotelConfig, client: httpx.AsyncClient | None = None, *, timeout: float = 15
    ) -> None:
        self.cfg = cfg
        self._client = client
        self.timeout = timeout

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.request(
                method,
                f"{self.cfg.base}{path}",
                data=data,
                params=params,
                auth=(self.cfg.api_key, self.cfg.api_token),
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError:
            raise TelephonyError(
                "The calling service didn't answer. Try again in a minute."
            ) from None
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code >= 400:
            raise _exotel_refusal(response)
        try:
            body = response.json()
        except ValueError:
            raise TelephonyError("The calling service answered in a way we can't read.") from None
        return body if isinstance(body, dict) else {}

    async def start_bridge(self, request: BridgeRequest) -> ProviderCall:
        data = {
            "From": request.seller,
            "To": request.lead,
            "CallerId": request.caller_id,
            "CallType": "trans",
            "TimeLimit": str(request.time_limit),
            "TimeOut": "40",
            "Record": "true" if request.record else "false",
            "RecordingChannels": "dual",
            "RecordingFormat": "mp3",
            "CustomField": request.reference[:128],
        }
        if request.status_url:
            data |= {
                "StatusCallback": request.status_url,
                "StatusCallbackEvents[0]": "terminal",
                "StatusCallbackEvents[1]": "answered",
                "StatusCallbackContentType": "application/json",
            }
        if request.notice_url:
            # Played to the lead (the callee) before the two are joined.
            data |= {"StartPlaybackToNew": "Callee", "StartPlaybackValueNew": request.notice_url}
        body = await self._request("POST", "/Calls/connect.json", data=data)
        call = body.get("Call") if isinstance(body.get("Call"), dict) else {}
        sid = str((call or {}).get("Sid") or "")
        if not _SID.match(sid):
            raise TelephonyError("The calling service didn't start the call. Try again.")
        return ProviderCall(sid=sid, status=normal_status((call or {}).get("Status")))

    async def report(self, sid: str) -> CallReport:
        if not _SID.match(sid):
            raise TelephonyError("The calling service doesn't know this call.", status=404)
        body = await self._request(
            "GET", f"/Calls/{quote(sid, safe='')}.json", params={"details": "true"}
        )
        call = body.get("Call")
        return exotel_report(call if isinstance(call, Mapping) else {})

    async def fetch_recording(self, url: str) -> Recording:
        host = (urlparse(url).hostname or "").lower()
        if urlparse(url).scheme != "https" or not host.endswith((".exotel.com", ".exotel.in")):
            raise TelephonyError("That recording isn't from the calling service.", status=404)
        client = self._client or httpx.AsyncClient(timeout=60)
        try:
            response = await client.get(url, auth=(self.cfg.api_key, self.cfg.api_token))
        except httpx.HTTPError:
            raise TelephonyError("The recording didn't download. Try again in a minute.") from None
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code >= 400:
            raise TelephonyError(
                "The recording isn't ready yet. Try again in a minute.", status=409
            )
        if len(response.content) > MAX_RECORDING:
            raise TelephonyError("That recording is too large.", status=413)
        kind = response.headers.get("content-type", "audio/mpeg").split(";")[0].strip()
        return Recording(response.content, kind if kind.startswith("audio/") else "audio/mpeg")


# ----- Plivo (second; the same shape) --------------------------------------------------


class PlivoProvider:
    """Plivo is the second provider (cheaper per minute); not wired yet."""

    name = "plivo"
    label = "Plivo"
    real = True

    async def start_bridge(self, request: BridgeRequest) -> ProviderCall:
        raise TelephonyError("Calls through Plivo aren't wired yet.", status=503)

    async def report(self, sid: str) -> CallReport:
        raise TelephonyError("Calls through Plivo aren't wired yet.", status=503)

    async def fetch_recording(self, url: str) -> Recording:
        raise TelephonyError("Calls through Plivo aren't wired yet.", status=503)


# ----- the stand-in ------------------------------------------------------------------


class FakeProvider:
    """No phone rings. A call rings for 6 seconds, talks until 20, then ends with 14
    seconds of talk; a lead number ending in 0 doesn't answer. Development and tests
    only: ``provider_from_env`` never gives it to production."""

    name = "fake"
    label = "Test calls (no phone rings)"
    real = False
    RINGING: Final = 6
    ENDS: Final = 20
    TALK: Final = 14

    def __init__(self, clock: Any = None) -> None:
        self._clock = clock or time.time

    async def start_bridge(self, request: BridgeRequest) -> ProviderCall:
        answers = "1" if not request.lead.endswith("0") else "0"
        return ProviderCall(sid=f"fake-{int(self._clock())}-{answers}", status="queued")

    async def report(self, sid: str) -> CallReport:
        parts = sid.split("-")
        if len(parts) != 3 or parts[0] != "fake" or not parts[1].isdigit():
            raise TelephonyError("The calling service doesn't know this call.", status=404)
        elapsed = self._clock() - int(parts[1])
        if elapsed < self.RINGING:
            return CallReport(sid=sid, status="ringing")
        if elapsed < self.ENDS:
            return CallReport(sid=sid, status="in_progress", seller_answered=True)
        if parts[2] == "0":
            return CallReport(
                sid=sid,
                status="no_answer",
                seller_answered=True,
                lead_answered=False,
                talk_seconds=0,
                total_seconds=self.RINGING,
                leg_seconds=(self.RINGING,),
            )
        return CallReport(
            sid=sid,
            status="completed",
            seller_answered=True,
            lead_answered=True,
            talk_seconds=self.TALK,
            total_seconds=self.ENDS,
            leg_seconds=(self.ENDS, self.TALK),
        )

    async def fetch_recording(self, url: str) -> Recording:
        raise TelephonyError("Test calls have no recording.", status=404)


def provider_from_env(
    env: Mapping[str, str] | None = None,
    *,
    environment: str,
    client: httpx.AsyncClient | None = None,
) -> Provider | None:
    """The provider this environment calls through, or None (company calling is off)."""
    env = os.environ if env is None else env
    name = (env.get("AC_TELEPHONY_PROVIDER") or "").strip().lower()
    if name == "exotel":
        cfg = exotel_config(env)
        return ExotelProvider(cfg, client) if cfg is not None else None
    if name == "plivo":
        return PlivoProvider()
    if name == "fake" and environment != "production":
        return FakeProvider()
    return None
