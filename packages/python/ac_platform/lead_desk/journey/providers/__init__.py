"""Ad platforms that learn from a business's lead stages.

Each platform module gives the engine the same few things:

- ``SPEC``: its name, what it learns from, and its own events (with the meanings
  each event suits), so the engine can match a business's stages to them;
- ``identity(lead)``: what the platform matches a lead on (its own lead id, a click
  id, hashed contact details), or None when this lead can't go to it;
- ``body(...)``: the one event, frozen before it is sent;
- ``send(...)``: one try, answered as an ``Answer`` (delivered, try again, wait for
  the customer, or never).

Nothing here decides a lead's stage. Platforms only hear about stages people set.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

ProviderId = Literal["meta", "google_ads", "linkedin", "tiktok", "microsoft_ads"]
PROVIDERS: Final[tuple[ProviderId, ...]] = (
    "meta",
    "google_ads",
    "linkedin",
    "tiktok",
    "microsoft_ads",
)


@dataclass(frozen=True, slots=True)
class EventOption:
    """One event a platform knows: its own name, plain words, and the meanings it suits."""

    id: str
    words: str
    milestones: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Spec:
    id: ProviderId
    name: str
    brand: str  # the brand library's key, for the logo
    # How the platform names events: "stage" (free names, one per stage), "action" (the
    # business's own conversion actions or goals, made for it here), "standard" (the
    # platform's fixed event list).
    naming: Literal["stage", "action", "standard"]
    learns: str  # plain words: what the platform does with the stages
    reaches: str  # plain words: which leads can go to it
    destination: str  # plain words for where events go ("dataset", "account")
    options: tuple[EventOption, ...] = ()
    # The meanings sent by default, in funnel order; "all" sends every stage.
    sends: tuple[str, ...] | Literal["all"] = "all"
    max_name: int = 50
    name_pattern: re.Pattern[str] = field(
        default_factory=lambda: re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,49}$")
    )

    def option(self, option_id: str) -> EventOption | None:
        return next((item for item in self.options if item.id == option_id), None)


@dataclass(frozen=True, slots=True)
class Answer:
    """What one send came to: delivered, try again (when), or rejected for good."""

    http_status: int | None
    error_code: str | None
    duration_ms: int
    trace_id: str | None = None
    wait: str = "retry"  # retry | customer | never

    @property
    def delivered(self) -> bool:
        return self.error_code is None


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hashed_email(email: str | None) -> str | None:
    """Trimmed, lower case, then SHA-256 (every platform's rule)."""
    value = (email or "").strip().lower()
    return sha256(value) if "@" in value else None


def phone_digits(phone: str | None) -> str | None:
    """Digits only with the country code, no leading zeros."""
    digits = re.sub(r"[^0-9]", "", phone or "").lstrip("0")
    return digits if 8 <= len(digits) <= 15 else None


def hashed_phone(phone: str | None) -> str | None:
    digits = phone_digits(phone)
    return sha256(digits) if digits else None


def hashed_e164(phone: str | None) -> str | None:
    """Google's and TikTok's rule: E.164 with the plus sign, then SHA-256."""
    digits = phone_digits(phone)
    return sha256(f"+{digits}") if digits else None


def digest(body: Mapping[str, Any]) -> str:
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")))


def event_id(provider: str, lead_ref: str, event_name: str) -> str:
    """The same lead and stage always get the same id, so the platform keeps one copy."""
    if provider == "meta":
        # Kept from the Meta-only sender (0104), so events it sent are not sent twice.
        return sha256(f"sales-xray:{lead_ref}:{event_name}")[:40]
    return sha256(f"sales-xray:{provider}:{lead_ref}:{event_name}")[:40]


# Click ids a website form or a platform's own lead form may carry, by platform.
CLICK_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "gclid": ("gclid", "gcl_id", "GCLID"),
    "gbraid": ("gbraid",),
    "wbraid": ("wbraid",),
    "fbclid": ("fbclid",),
    "ttclid": ("ttclid",),
    "li_fat_id": ("li_fat_id",),
    "msclkid": ("msclkid", "MSCLKID"),
}
_CLICK: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_\-.~]{6,512}$")


def click_ids(payload: Any) -> dict[str, str]:
    """The ad click ids in a lead's record (top level, or in its utm/tracking part)."""
    found: dict[str, str] = {}
    if not isinstance(payload, Mapping):
        return found
    places: list[Mapping[str, Any]] = [payload]
    for nested in ("tracking", "utm", "attribution", "details", "meta", "google"):
        value = payload.get(nested)
        if isinstance(value, Mapping):
            places.append(value)
    for name, keys in CLICK_KEYS.items():
        for place in places:
            value = next((place.get(key) for key in keys if place.get(key)), None)
            if isinstance(value, str) and _CLICK.fullmatch(value.strip()):
                found[name] = value.strip()
                break
    return found
