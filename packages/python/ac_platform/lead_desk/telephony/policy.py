"""Who may be called from the company number, what it may cost, and what the lead hears.

The owner, 27 Oct 2026: "consented leads only, recording notice on, … ₹5,000/month
cap while testing, … counsel before real customer calls."

- **Consented leads only.** A lead may be called from the company number when it came
  from a source where the person asked to be contacted (lead forms, website forms and
  chats by default) and asked recently: TRAI's 12 Feb 2025 amendment, clause (bh)(ii),
  counts a sales call on explicit consent as a service call for seven days. Everyone
  else is called from the seller's own phone, as before. The organisation's owner may
  widen the sources or the window once their counsel agrees.
- **The recording notice.** A fixed, versioned sentence, played to the lead before the
  two are joined; a new wording is a new version, never an edit.
- **The spend guard.** A monthly and a daily cap per organisation, and the price per
  leg-minute the provider charges. These are AC's own settings: environment defaults,
  or a staff override written by a data-change script, never shown or editable in the
  organisation's Settings. A call's time limit is what the budget left can pay for.
- **Where it runs.** Only in organisations staff turned it on for
  (``AC_TELEPHONY_TENANTS``). Outside production, real calls go only to the team's
  test phones (``AC_TELEPHONY_TEST_NUMBERS``). In production, nothing is placed until
  counsel has cleared it (``AC_TELEPHONY_COUNSEL_CLEARED``).

No price, cost or minute count ever reaches a person in the app.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from ac_platform.lead_desk.capture import normalise_phone

KEY: Final = "company_calling"
# Staff only: {"monthly_paise", "daily_paise", "rate_paise"} (scripts/data-changes/).
LIMITS_KEY: Final = "company_calling_limits"

SOURCES: Final[dict[str, str]] = {
    "meta": "Facebook and Instagram lead forms",
    "webhook": "Website forms, chats and connected apps",
    "sheet": "Google Sheets",
    "manual": "Leads added by hand",
    "referral": "Referrals",
    "csv": "Imported files",
}
DEFAULT_SOURCES: Final[tuple[str, ...]] = ("meta", "webhook")
DEFAULT_WINDOW_DAYS: Final = 7
MAX_WINDOW_DAYS: Final = 90


@dataclass(frozen=True, slots=True)
class Notice:
    version: str
    text: str
    file: str


NOTICES: Final[dict[str, Notice]] = {
    "recording-notice-en-v1": Notice(
        "recording-notice-en-v1",
        "This call is recorded, for quality and training.",
        "recording-notice-en-v1.wav",
    ),
}
DEFAULT_NOTICE: Final = "recording-notice-en-v1"

# AC's defaults: the owner's ₹5,000 a month while testing, and Exotel's unknown rate
# taken at a careful ₹1.00 a leg-minute until its quote.
DEFAULT_MONTHLY_PAISE: Final = 500_000
DEFAULT_DAILY_PAISE: Final = 50_000
DEFAULT_RATE_PAISE: Final = 100
PULSE_SECONDS: Final = 30
MAX_CALL_SECONDS: Final = 3600
MIN_CALL_SECONDS: Final = 60
# A call still ringing or talking holds this much of the budget until it ends.
RESERVE_MINUTES: Final = 10


@dataclass(frozen=True, slots=True)
class CallingSettings:
    on: bool = False
    number: str | None = None
    notice_on: bool = True
    notice_version: str = DEFAULT_NOTICE
    window_days: int = DEFAULT_WINDOW_DAYS
    sources: tuple[str, ...] = DEFAULT_SOURCES
    # Person id -> that seller's own mobile, rung first.
    mobiles: Mapping[str, str] = field(default_factory=dict)

    @property
    def notice(self) -> Notice | None:
        return NOTICES.get(self.notice_version) if self.notice_on else None


def read(config: Mapping[str, Any]) -> CallingSettings:
    raw = config.get(KEY)
    if not isinstance(raw, Mapping):
        return CallingSettings()
    number = normalise_phone(raw.get("number")) if raw.get("number") else None
    version = str(raw.get("notice_version") or DEFAULT_NOTICE)
    window = raw.get("window_days")
    sources_raw = raw.get("sources")
    sources = (
        tuple(source for source in SOURCES if source in sources_raw)
        if isinstance(sources_raw, list)
        else DEFAULT_SOURCES
    )
    mobiles_raw = raw.get("mobiles")
    mobiles = {
        str(person): mobile
        for person, value in (mobiles_raw.items() if isinstance(mobiles_raw, Mapping) else ())
        if (mobile := normalise_phone(value)) is not None
    }
    return CallingSettings(
        on=raw.get("on") is True,
        number=number,
        # The notice is on unless the owner turned it off.
        notice_on=raw.get("notice_on") is not False,
        notice_version=version if version in NOTICES else DEFAULT_NOTICE,
        window_days=int(window)
        if isinstance(window, int) and 1 <= window <= MAX_WINDOW_DAYS
        else DEFAULT_WINDOW_DAYS,
        sources=sources,
        mobiles=mobiles,
    )


def as_config(value: CallingSettings) -> dict[str, Any]:
    if value.notice_version not in NOTICES:
        raise ValueError("Pick one of the recording notices.")
    if not 1 <= value.window_days <= MAX_WINDOW_DAYS:
        raise ValueError(f"Pick between 1 and {MAX_WINDOW_DAYS} days.")
    unknown = [source for source in value.sources if source not in SOURCES]
    if unknown:
        raise ValueError("Pick sources from the list.")
    return {
        "on": value.on,
        "number": value.number,
        "notice_on": value.notice_on,
        "notice_version": value.notice_version,
        "window_days": value.window_days,
        "sources": [source for source in SOURCES if source in value.sources],
        "mobiles": dict(value.mobiles),
    }


# ----- where it runs -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rules:
    environment: str
    tenants: frozenset[UUID]
    test_numbers: frozenset[str]
    counsel_cleared: bool

    @property
    def production(self) -> bool:
        return self.environment == "production"


def _uuids(raw: str) -> frozenset[UUID]:
    found: set[UUID] = set()
    for part in raw.replace(";", ",").split(","):
        try:
            found.add(UUID(part.strip()))
        except ValueError:
            continue
    return frozenset(found)


def _numbers(raw: Iterable[str]) -> frozenset[str]:
    return frozenset(number for item in raw if (number := normalise_phone(item)) is not None)


def rules(env: Mapping[str, str] | None = None, *, environment: str) -> Rules:
    env = os.environ if env is None else env
    return Rules(
        environment=environment,
        tenants=_uuids(env.get("AC_TELEPHONY_TENANTS") or ""),
        test_numbers=_numbers(
            (env.get("AC_TELEPHONY_TEST_NUMBERS") or "").replace(";", ",").split(",")
        ),
        counsel_cleared=(env.get("AC_TELEPHONY_COUNSEL_CLEARED") or "").strip().lower() == "yes",
    )


# ----- refusals, in words a seller can act on -------------------------------------------


@dataclass(frozen=True, slots=True)
class Refusal:
    reason: str
    words: str


OFF = Refusal("off", "Company calling is off in this workspace.")
NOT_SET_UP = Refusal("not_set_up", "Company calling isn't set up here yet.")
NO_NUMBER = Refusal("no_number", "Your admin adds the company number in Settings → Calling first.")
NO_MOBILE = Refusal("no_mobile", "Add your mobile in Settings → Calling, so we can ring you first.")
NO_PHONE = Refusal("no_phone", "This lead has no phone number.")
NOT_ASKED = Refusal(
    "not_asked", "This lead didn't ask to be contacted, so call from your own phone."
)
TEST_ONLY = Refusal(
    "test_only", "On this test site, company calls go only to the team's test phones."
)
NOT_CLEARED = Refusal("not_cleared", "Company calls start once the legal check is done.")
PAUSED = Refusal("paused", "Company calling is paused for now. Call from your own phone.")


def too_old(days: int) -> Refusal:
    return Refusal(
        "too_old",
        f"This lead asked more than {days} day{'s' if days != 1 else ''} ago, "
        "so call from your own phone.",
    )


def place_check(settings: CallingSettings, run: Rules, *, real_provider: bool) -> Refusal | None:
    """Whether this organisation may place company calls at all right now."""
    if not settings.on:
        return OFF
    if settings.number is None:
        return NO_NUMBER
    if real_provider and run.production and not run.counsel_cleared:
        return NOT_CLEARED
    return None


def lead_check(
    settings: CallingSettings,
    run: Rules,
    *,
    source: str,
    asked_at: datetime,
    phone: str | None,
    now: datetime,
    real_provider: bool,
) -> Refusal | None:
    """Whether this lead may be called from the company number (consented leads only)."""
    number = normalise_phone(phone) if phone else None
    if number is None:
        return NO_PHONE
    if source not in settings.sources:
        return NOT_ASKED
    if now - asked_at > timedelta(days=settings.window_days):
        return too_old(settings.window_days)
    if real_provider and not run.production and number not in run.test_numbers:
        return TEST_ONLY
    return None


def mobile_check(
    settings: CallingSettings, run: Rules, person_id: UUID, *, real_provider: bool
) -> Refusal | None:
    mobile = settings.mobiles.get(str(person_id))
    if mobile is None:
        return NO_MOBILE
    if real_provider and not run.production and mobile not in run.test_numbers:
        return TEST_ONLY
    return None


# ----- the spend guard -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Limits:
    monthly_paise: int
    daily_paise: int
    rate_paise: int  # per leg-minute


def _positive(raw: object, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def limits(config: Mapping[str, Any], env: Mapping[str, str] | None = None) -> Limits:
    """The organisation's caps: a staff override, else this environment's defaults."""
    env = os.environ if env is None else env
    base = Limits(
        monthly_paise=_positive(env.get("AC_TELEPHONY_MONTHLY_CAP_PAISE"), DEFAULT_MONTHLY_PAISE),
        daily_paise=_positive(env.get("AC_TELEPHONY_DAILY_CAP_PAISE"), DEFAULT_DAILY_PAISE),
        rate_paise=_positive(env.get("AC_TELEPHONY_RATE_PAISE"), DEFAULT_RATE_PAISE),
    )
    raw = config.get(LIMITS_KEY)
    if not isinstance(raw, Mapping):
        return base
    return Limits(
        monthly_paise=_positive(raw.get("monthly_paise"), base.monthly_paise),
        daily_paise=_positive(raw.get("daily_paise"), base.daily_paise),
        rate_paise=_positive(raw.get("rate_paise"), base.rate_paise),
    )


def cost_paise(leg_seconds: Iterable[int], rate_paise: int) -> int:
    """What the legs cost at the rate, each rounded up to the provider's 30-second pulse."""
    pulses = sum(math.ceil(max(0, seconds) / PULSE_SECONDS) for seconds in leg_seconds)
    return math.ceil(pulses * rate_paise * PULSE_SECONDS / 60)


def reserve_paise(rate_paise: int) -> int:
    """What a call holds while it rings or talks: both legs for ``RESERVE_MINUTES``."""
    return 2 * RESERVE_MINUTES * rate_paise


def time_limit(left_paise: int, rate_paise: int) -> int | None:
    """The longest call (seconds) the budget left pays for, both legs; None: too little."""
    if rate_paise <= 0:
        return MAX_CALL_SECONDS
    seconds = int(left_paise / (2 * rate_paise) * 60)
    seconds = min(MAX_CALL_SECONDS, seconds - seconds % PULSE_SECONDS)
    return seconds if seconds >= MIN_CALL_SECONDS else None


@dataclass(frozen=True, slots=True)
class Budget:
    left_paise: int
    paused: str | None  # None, "day" or "month"


def budget(cap: Limits, *, month_spent: int, day_spent: int) -> Budget:
    month_left = cap.monthly_paise - month_spent
    day_left = cap.daily_paise - day_spent
    left = min(month_left, day_left)
    if time_limit(left, cap.rate_paise) is not None:
        return Budget(left, None)
    return Budget(max(0, left), "month" if month_left <= day_left else "day")
