"""Websites and landing pages: one line of script, and every form fill is a lead.

The organisation pastes one line into its site's head (owner, 30 Oct 2026: "connecting
websites matters a lot to customers… today's way of adding websites and landing pages is
a frustrating experience")::

    <script src="https://<sales xray>/sx.js" data-key="sxw_…" async></script>

The script (``apps/sales-xray-web/public/sx.js``) says hello once per page, with how many
lead forms the page has, and sends each lead form's fields when a visitor submits it, with
where the visit came from: the page, the referrer, the UTM tags and the ad click ids
(``gclid``, ``gbraid``, ``wbraid``, ``fbclid``, Meta's ``_fbc`` and ``_fbp``).

- **The key is public**, like an ad pixel's id: it names the organisation's website source
  (a ``webhook`` source with ``config.website``). It is checked by its SHA-256, as source
  keys are. Rotating it stops the old line everywhere.
- **Sites appear by themselves.** The first hello from a new host adds that site
  ("We saw your site at 10:42"). A paused site's forms add no leads; a removed site stays
  in the table as removed, so its host can't add itself again until someone adds it back.
- **Counted, not tracked.** Each page keeps a few counters per day (views, lead forms,
  form fills, new leads, bot fills turned away). There is no visitor id and no IP address
  is kept; the ad ids come from the visitor's own address bar and the ad platforms' own
  first-party cookies, and go only into the lead the visitor sent.
- **Leads go the one way every source goes**: ``LeadDesk.ingest`` (deduped by phone, then
  by email, allocated by the rules). The lead's record keeps the form's answers, plus
  ``attribution`` and ``website`` parts. The ad platforms' stage senders already read click
  ids from ``attribution`` (``journey/providers.click_ids``), so a website lead's stages
  reach Google Ads (and Microsoft, TikTok, LinkedIn) like any other lead's.
- **Spam and bots**: the browser must send an Origin that matches the page; a headless
  browser (``navigator.webdriver``), a form filled with no key press or tap in under three
  seconds, or a name that is a link is turned away and counted; each address may send only
  a few leads (``http/rate_limits.py``), and each site at most ``SITE_LEADS_PER_WINDOW``
  in ``SITE_WINDOW``.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from ac_platform.lead_desk.capture import CaptureError, clean, first_email, normalise_phone
from ac_platform.lead_desk.capture import key as field_key
from ac_platform.lead_desk.models import LeadSite, LeadSitePage, LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, utcnow

KEY_PREFIX: Final[str] = "sxw_"
KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^sxw_[A-Za-z0-9_-]{20,64}$")
SOURCE_LABEL: Final[str] = "Website"
MAX_SITES: Final[int] = 50
MAX_PAGES_A_DAY: Final[int] = 100
OTHER_PAGES: Final[str] = "(other pages)"
MAX_FIELDS: Final[int] = 40
MAX_KEY: Final[int] = 80
MAX_VALUE: Final[int] = 1000
PERIOD_DAYS: Final[int] = 30
SHOWN_PAGES: Final[int] = 20
# A lead form filled faster than this, with no key press or tap, is a bot.
FAST_MS: Final[int] = 3000
SITE_WINDOW: Final[timedelta] = timedelta(minutes=10)
SITE_LEADS_PER_WINDOW: Final[int] = 30
# The same person sending the same site's form again within this window is one lead
# ("known"), not a repeat: a double tap, or a form sent again after a fix.
RESEND_WINDOW_S: Final[int] = 30 * 60
# A lead the browser kept and sent again counts from when it was first sent, within a day.
RESEND_UP_TO: Final[timedelta] = timedelta(hours=25)
# Seen again within this time: the site row is not written again for one more view.
SEEN_EVERY: Final[timedelta] = timedelta(seconds=60)

Status = Literal["active", "paused", "removed"]
PLATFORMS: Final[frozenset[str]] = frozenset(
    {
        "wordpress",
        "elementor",
        "webflow",
        "framer",
        "wix",
        "squarespace",
        "shopify",
        "hubspot",
        "carrd",
        "unbounce",
        "instapage",
        "systeme",
        "nextjs",
        "other",
    }
)
# The ad and campaign tags kept with a lead, as the address bar and the ad platforms'
# own cookies name them.
UTM_KEYS: Final[tuple[str, ...]] = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
)
CLICK_KEYS: Final[tuple[str, ...]] = (
    "gclid",
    "gbraid",
    "wbraid",
    "fbclid",
    "msclkid",
    "ttclid",
    "li_fat_id",
)
COOKIE_KEYS: Final[tuple[str, ...]] = ("fbc", "fbp")
PLACE_KEYS: Final[tuple[str, ...]] = ("landing_url", "referrer")
TOUCH_KEYS: Final[tuple[str, ...]] = (*UTM_KEYS, *CLICK_KEYS, *COOKIE_KEYS, *PLACE_KEYS, "at")
_CLICK_VALUE = re.compile(r"^[A-Za-z0-9_\-.~]{6,512}$")
_FBC = re.compile(r"^fb\.[0-9]\.[0-9]{10,13}\.[A-Za-z0-9_\-.~]{6,512}$")
_FBP = re.compile(r"^fb\.[0-9]\.[0-9]{10,13}\.[0-9]{5,20}$")
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{1,63})*$")
_TEST_SUFFIXES: Final[tuple[str, ...]] = (".localhost", ".local", ".test", ".example", ".invalid")
# Form fields never kept, whatever the form calls them: secrets, payment details, identity
# numbers and the form tools' own plumbing.
_SECRET = re.compile(
    r"(pass(word|code)?|pwd|card|expiry|aadhaa?r|ifsc|account_?(no|number)|captcha|"
    r"turnstile|nonce|token|csrf|honeypot|^action$|^sx_|"
    r"(^|_)(cvv|cvc|otp|pan|ssn|iban|upi)(_no|_number)?($|_))",
)
_PLUMBING: Final[frozenset[str]] = frozenset(
    {
        "post_id",
        "form_id",
        "queried_id",
        "referer_title",
        "referrer_title",
        "page_url",
        "redirect",
        "redirect_to",
        "submit",
        "wpcf7",
        "elementor_form_id",
    }
)
_LINK = re.compile(r"(https?://|www\.|<\s*/?\s*[a-z]+[^>]*>)", re.IGNORECASE)
ROLES: Final[frozenset[str]] = frozenset(
    {"name", "first_name", "last_name", "phone", "email", "company", "city", "message"}
)


class WebsiteError(DeskError):
    """What a website's script did wrong; the message is safe to show."""


_UNSAFE = re.compile(r"[\x00\ud800-\udfff]")


def _text(value: object, limit: int) -> str | None:
    """``clean`` for what a website sends: also no NUL or lone surrogate, which PostgreSQL
    refuses."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    return clean(_UNSAFE.sub("", str(value)), limit)


# ----- what the browser sends ------------------------------------------------------


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def normalise_host(raw: object) -> str | None:
    """A site's host as the list shows it: lower case, no ``www.``, no port."""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if "//" not in text:
        if re.match(r"^[a-z][a-z0-9+.-]*:(?![0-9])", text):
            return None  # another kind of address (javascript:, mailto:), not a site
        text = "//" + text
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        return None
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("[") or ":" in host:
        return None  # an IPv6 address is a test, never a site to list
    if "." not in host and host != "localhost":
        return None
    return host if _HOST.fullmatch(host) else None


def is_test_host(host: str) -> bool:
    """A computer's own address or a test name: its leads are test data."""
    return (
        host == "localhost"
        or host.endswith(_TEST_SUFFIXES)
        or re.fullmatch(r"[0-9.]+", host) is not None
    )


def page_path(url: object) -> str:
    """A page as the list shows it: its path, without the query or a trailing slash."""
    try:
        path = urlsplit(_UNSAFE.sub("", str(url or ""))).path or "/"
    except ValueError:
        return "/"
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path[:300]


def page_address(url: object) -> str | None:
    """The page's address without its query (the tags are kept apart, in attribution)."""
    try:
        parts = urlsplit(_UNSAFE.sub("", str(url or "")))
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"[:500]


def origin_host(origin: str | None) -> str | None:
    if not origin or origin == "null":
        return None
    return normalise_host(origin)


def platform_of(raw: object) -> str | None:
    value = str(raw or "").strip().lower()[:24]
    return value if value in PLATFORMS else None


def clean_touch(raw: object) -> dict[str, str]:
    """One visit's tags and ids, each checked for its shape; anything else is dropped."""
    if not isinstance(raw, Mapping):
        return {}
    found: dict[str, str] = {}
    for name in UTM_KEYS:
        value = _text(raw.get(name), 200)
        if value:
            found[name] = value
    for name in CLICK_KEYS:
        value = _text(raw.get(name), 512)
        if value and _CLICK_VALUE.fullmatch(value):
            found[name] = value
    fbc, fbp = _text(raw.get("fbc"), 600), _text(raw.get("fbp"), 64)
    if fbc and _FBC.fullmatch(fbc):
        found["fbc"] = fbc
    if fbp and _FBP.fullmatch(fbp):
        found["fbp"] = fbp
    for name in PLACE_KEYS:
        address = page_address(raw.get(name))
        if address:
            found[name] = address
    at = raw.get("at")
    if isinstance(at, (int, float)) and not isinstance(at, bool) and 1e12 <= at <= 1e13:
        found["at"] = datetime.fromtimestamp(at / 1000, tz=utcnow().tzinfo).isoformat()
    return found


def clean_attribution(raw: object, *, page: str | None, title: str | None) -> dict[str, Any]:
    """Where the lead came from: this visit's tags (last touch) at the top, the visitor's
    first landing in the last 90 days under ``first_touch`` when it differs."""
    data = raw if isinstance(raw, Mapping) else {}
    last = clean_touch(data.get("last") if isinstance(data.get("last"), Mapping) else data)
    first = clean_touch(data.get("first"))
    out: dict[str, Any] = dict(last)
    if page:
        out["page_url"] = page
    if title:
        out["page_title"] = title
    if first and first != last:
        out["first_touch"] = first
    # Meta's click id from its cookie when the address bar had none (fb.1.<ms>.<fbclid>).
    if "fbclid" not in out and "fbc" in out:
        out["fbclid"] = out["fbc"].split(".", 3)[3]
    return out


def came_from(attribution: Mapping[str, Any], host: str) -> str:
    """One plain line for the lead's sheet: "Google Ads · Diwali offer"."""
    source = str(attribution.get("utm_source") or "").strip()
    medium = str(attribution.get("utm_medium") or "").strip().lower()
    campaign = str(attribution.get("utm_campaign") or "").strip()
    if any(attribution.get(k) for k in ("gclid", "gbraid", "wbraid")):
        where = "Google Ads"
    elif attribution.get("fbclid") or source.lower() in {"facebook", "fb", "instagram", "ig"}:
        name = (
            "Instagram"
            if source.lower() in {"instagram", "ig"}
            else "Facebook"
            if source.lower() in {"facebook", "fb"}
            else "Facebook / Instagram"
        )
        paid = bool(attribution.get("fbclid")) or medium in {"cpc", "paid", "paid_social", "ad"}
        where = f"{name} ad" if paid else name
    elif attribution.get("msclkid"):
        where = "Microsoft Ads"
    elif attribution.get("ttclid"):
        where = "TikTok ad"
    elif attribution.get("li_fat_id"):
        where = "LinkedIn ad"
    elif source:
        where = source[:1].upper() + source[1:60]
    else:
        referrer = normalise_host(attribution.get("referrer"))
        if referrer and referrer != host:
            where = "Google search" if referrer.startswith("google.") else referrer
        else:
            where = "Direct visit"
    return f"{where} · {campaign[:80]}" if campaign else where


@dataclass(frozen=True, slots=True)
class FormField:
    label: str
    value: str
    role: str | None


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def _secret_value(value: str) -> bool:
    """A card number by its shape: 13 to 19 digits passing the card check. Card numbers
    never start with 0, so a phone written with its trunk or international 0 is never one."""
    digits = re.sub(r"[ -]", "", value)
    return digits.isdigit() and 13 <= len(digits) <= 19 and digits[0] != "0" and _luhn(digits)


def _contact_like(role: object, value: str) -> bool:
    """A phone or email answer, or a number with its country code (+91…, 0091…), is never
    taken for a card number, even when its digits pass the card check."""
    return role in ("phone", "email") or value.strip().startswith(("+", "00"))


def clean_fields(raw: object) -> list[FormField]:
    """The form's answers, in order. Secrets, payment details and form plumbing are dropped
    here even when the script missed them."""
    items: Iterable[Any]
    if isinstance(raw, Mapping):
        items = ({"k": name, "v": value} for name, value in raw.items())
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    fields: list[FormField] = []
    seen: dict[str, int] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        label = _text(item.get("k"), MAX_KEY)
        value = _text(item.get("v"), MAX_VALUE)
        if not label or not value:
            continue
        name = field_key(label)
        if (
            not name
            or name.startswith("_")
            or _SECRET.search(name)
            or name in _PLUMBING
            or (_secret_value(value) and not _contact_like(item.get("r"), value))
        ):
            continue
        said = item.get("r")
        role = said if isinstance(said, str) and said in ROLES else None
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            label = f"{label} ({seen[label]})"
        fields.append(FormField(label=label, value=value, role=role))
        if len(fields) >= MAX_FIELDS:
            break
    return fields


def record_of(
    fields: list[FormField],
    *,
    attribution: Mapping[str, Any],
    website: Mapping[str, Any],
    host: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """The lead's record and which answer holds each of the desk's fields.

    The answers sit at the top (shown on the lead's sheet as they were asked); ``Page`` and
    ``Came from`` say in plain words where it came from; the raw tags and ids sit under
    ``attribution`` and the site's details under ``website``, which the sheet doesn't list.
    """
    record: dict[str, Any] = {item.label: item.value for item in fields}
    mapping: dict[str, str] = {}
    by_role: dict[str, FormField] = {}
    for item in fields:
        if item.role and item.role not in by_role:
            by_role[item.role] = item
    for role in ("name", "phone", "email", "company", "city"):
        found = by_role.get(role)
        if found is not None:
            mapping[role] = found.label
    if "name" not in mapping and ("first_name" in by_role or "last_name" in by_role):
        joined = " ".join(
            by_role[part].value for part in ("first_name", "last_name") if part in by_role
        )
        if joined:
            record.setdefault("Full name", joined[:200])
            mapping["name"] = "Full name"
    if attribution.get("page_url"):
        record.setdefault("Page", str(attribution["page_url"]))
    record.setdefault("Came from", came_from(attribution, host))
    record["attribution"] = dict(attribution)
    record["website"] = dict(website)
    return record, mapping


@dataclass(frozen=True, slots=True)
class Contact:
    phone: str | None
    email: str | None
    # The answers they came from, so the lead takes exactly these.
    phone_label: str | None = None
    email_label: str | None = None


def contact_of(fields: list[FormField], default_country: str) -> Contact:
    """The phone and email the form holds: the ones it marks, else any answer shaped so."""
    phone = email = phone_label = email_label = None
    marked = [item for item in fields if item.role in ("phone", "email")]
    for item in [*marked, *(item for item in fields if item.role is None)]:
        if phone is None and item.role in ("phone", None):
            phone = normalise_phone(item.value, default_country=default_country)
            phone_label = item.label if phone else None
        if email is None and item.role in ("email", None):
            email = first_email(item.value.lower())
            email_label = item.label if email else None
    return Contact(phone, email, phone_label, email_label)


def bot_reason(
    fields: list[FormField],
    *,
    webdriver: object,
    interactions: object,
    elapsed_ms: object,
    trap: object = False,
) -> str | None:
    """Why this form fill is a bot's, or None. ``trap``: the form's honeypot (a field
    people can't reach) held text."""
    if webdriver is True:
        return "headless"
    if trap is True:
        return "honeypot"
    touched = interactions if isinstance(interactions, int) else 0
    spent = elapsed_ms if isinstance(elapsed_ms, int) else None
    if touched <= 0 and spent is not None and spent < FAST_MS:
        return "too_fast"
    for item in fields:
        if item.role in ("name", "first_name", "last_name", "phone") and _LINK.search(item.value):
            return "link_in_name"
    return None


def sent_at(raw: object, now: datetime) -> datetime:
    """When the browser first sent this lead (a kept lead sent again says so), if that is
    within the last day; else now."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            at = datetime.fromtimestamp(raw / 1000, tz=now.tzinfo)
        except (OverflowError, OSError, ValueError):
            return now
        if now - RESEND_UP_TO <= at <= now + timedelta(minutes=5):
            return min(at, now)
    return now


def resend_ref(host: str, phone: str | None, email: str | None, now: datetime) -> str:
    """The same person, the same site, within half an hour: the same reference."""
    window = int(now.timestamp()) // RESEND_WINDOW_S
    return "web:" + hashlib.sha256(f"{host}|{phone or email}|{window}".encode()).hexdigest()[:40]


def snippet(script_url: str, key: str) -> str:
    return f'<script src="{script_url}" data-key="{key}" async></script>'


# ----- how many leads a site may send --------------------------------------------------


class SiteLimiter:
    """At most ``SITE_LEADS_PER_WINDOW`` leads per site in ``SITE_WINDOW``, per process.

    The per-address limit sits in front (``http/rate_limits.py``); this one stops a form
    that someone scripts from many addresses from filling the desk."""

    def __init__(self, *, most: int = 5000, clock: Any = time.monotonic) -> None:
        self._seen: OrderedDict[str, deque[float]] = OrderedDict()
        self._most = most
        self._clock = clock

    def allow(self, name: str) -> bool:
        now = self._clock()
        window = SITE_WINDOW.total_seconds()
        times = self._seen.pop(name, None) or deque()
        while times and now - times[0] > window:
            times.popleft()
        allowed = len(times) < SITE_LEADS_PER_WINDOW
        if allowed:
            times.append(now)
        self._seen[name] = times
        while len(self._seen) > self._most:
            self._seen.popitem(last=False)
        return allowed


LIMITER = SiteLimiter()


# ----- the views a manager sees ---------------------------------------------------------


class PageView(BaseModel):
    path: str
    title: str | None
    views: int
    forms: int
    fills: int
    leads: int
    blocked: int
    rate: float | None = Field(description="Form fills per view, 0-1; None without views.")
    last_day: date


class SiteView(BaseModel):
    site_id: UUID
    host: str
    label: str
    status: Status
    platform: str | None
    added: Literal["person", "seen"]
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_page: str | None
    last_lead_at: datetime | None
    test: bool
    views: int
    forms: int
    fills: int
    leads: int
    blocked: int
    rate: float | None
    pages: tuple[PageView, ...]


class Websites(BaseModel):
    on: bool
    # None until a manager starts (Add website): a read never makes the key.
    key: str | None
    script_url: str
    snippet: str | None
    period_days: int
    sites: tuple[SiteView, ...]
    views: int
    leads: int
    rate: float | None
    now: datetime


class NewSite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=3, max_length=300)


class SiteStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "paused"]


def _rate(fills: int, views: int) -> float | None:
    return round(min(1.0, fills / views), 4) if views > 0 else None


# ----- the store --------------------------------------------------------------------------


class SiteBook:
    """The organisation's websites, for a signed-in manager."""

    def __init__(self, desk: LeadDesk, *, app_url: str) -> None:
        self.desk = desk
        self.db = desk.db
        self.tenant_id = desk.tenant_id
        self.app_url = app_url.rstrip("/")

    @property
    def script_url(self) -> str:
        return f"{self.app_url}/sx.js"

    async def source(self, *, create: bool) -> LeadSource | None:
        """The organisation's website source (its key), made the first time it's asked for."""
        rows = (
            await self.db.scalars(
                select(LeadSource)
                .where(LeadSource.tenant_id == self.tenant_id, LeadSource.kind == "webhook")
                .order_by(LeadSource.created_at)
            )
        ).all()
        found = next((row for row in rows if (row.config or {}).get("website")), None)
        if found is not None or not create:
            return found
        # Two "Start"s at once: the second waits, then finds the first one's source.
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:name))"),
            {"name": f"lead-desk-website:{self.tenant_id}"},
        )
        again = await self.source(create=False)
        if again is not None:
            return again
        key = new_key()
        found = LeadSource(
            id=uuid4(),
            tenant_id=self.tenant_id,
            kind="webhook",
            label=SOURCE_LABEL,
            token_sha256=key_hash(key),
            config={"website": {"key": key}},
            active=True,
            received=0,
            created_by_person_id=self.desk.viewer.person_id,
            created_at=self.desk.now,
            updated_at=self.desk.now,
        )
        self.db.add(found)
        await self.db.flush()
        return found

    async def read(self) -> Websites:
        self.desk._require_manager()
        source = await self.source(create=False)
        key = str((source.config or {})["website"]["key"]) if source is not None else None
        sites = (
            await self.db.scalars(
                select(LeadSite)
                .where(LeadSite.tenant_id == self.tenant_id, LeadSite.status != "removed")
                .order_by(LeadSite.created_at)
            )
        ).all()
        since = self.desk.now.date() - timedelta(days=PERIOD_DAYS - 1)
        live = [site.id for site in sites]
        per_page = (
            select(
                LeadSitePage.site_id.label("site_id"),
                LeadSitePage.path.label("path"),
                func.max(LeadSitePage.title).label("title"),
                func.sum(LeadSitePage.views).label("views"),
                func.max(LeadSitePage.forms).label("forms"),
                func.sum(LeadSitePage.fills).label("fills"),
                func.sum(LeadSitePage.leads).label("leads"),
                func.sum(LeadSitePage.blocked).label("blocked"),
                func.max(LeadSitePage.day).label("last_day"),
            )
            .where(
                LeadSitePage.tenant_id == self.tenant_id,
                LeadSitePage.site_id.in_(live),
                LeadSitePage.day >= since,
            )
            .group_by(LeadSitePage.site_id, LeadSitePage.path)
            .subquery()
        )
        ranked = select(
            per_page,
            func.row_number()
            .over(
                partition_by=per_page.c.site_id,
                order_by=(
                    per_page.c.leads.desc(),
                    per_page.c.fills.desc(),
                    per_page.c.views.desc(),
                    per_page.c.path,
                ),
            )
            .label("rank"),
        ).subquery()
        totals = (
            {
                site_id: (
                    int(views or 0),
                    int(forms or 0),
                    int(fills or 0),
                    int(leads or 0),
                    int(blocked or 0),
                )
                for site_id, views, forms, fills, leads, blocked in (
                    await self.db.execute(
                        select(
                            per_page.c.site_id,
                            func.sum(per_page.c.views),
                            func.sum(per_page.c.forms),
                            func.sum(per_page.c.fills),
                            func.sum(per_page.c.leads),
                            func.sum(per_page.c.blocked),
                        ).group_by(per_page.c.site_id)
                    )
                ).tuples()
            }
            if live
            else {}
        )
        pages: dict[UUID, list[PageView]] = {}
        rows: Iterable[tuple[Any, ...]] = (
            (
                await self.db.execute(
                    select(
                        ranked.c.site_id,
                        ranked.c.path,
                        ranked.c.title,
                        ranked.c.views,
                        ranked.c.forms,
                        ranked.c.fills,
                        ranked.c.leads,
                        ranked.c.blocked,
                        ranked.c.last_day,
                    )
                    .where(ranked.c.rank <= SHOWN_PAGES)
                    .order_by(ranked.c.site_id, ranked.c.rank)
                )
            ).tuples()
            if live
            else []
        )
        for site_id, path, title, viewed, forms, fills, leads, blocked, last_day in rows:
            pages.setdefault(site_id, []).append(
                PageView(
                    path=path,
                    title=title,
                    views=int(viewed or 0),
                    forms=int(forms or 0),
                    fills=int(fills or 0),
                    leads=int(leads or 0),
                    blocked=int(blocked or 0),
                    rate=_rate(int(fills or 0), int(viewed or 0)),
                    last_day=last_day,
                )
            )
        shown: list[SiteView] = []
        for site in sites:
            views, forms, fills, leads, blocked = totals.get(site.id, (0, 0, 0, 0, 0))
            shown.append(
                SiteView(
                    site_id=site.id,
                    host=site.host,
                    label=site.label,
                    status=site.status,
                    platform=site.platform,
                    added=site.added,
                    first_seen_at=site.first_seen_at,
                    last_seen_at=site.last_seen_at,
                    last_page=site.last_page,
                    last_lead_at=site.last_lead_at,
                    test=is_test_host(site.host),
                    views=views,
                    forms=forms,
                    fills=fills,
                    leads=leads,
                    blocked=blocked,
                    rate=_rate(fills, views),
                    pages=tuple(pages.get(site.id, [])),
                )
            )
        all_views = sum(site.views for site in shown if not site.test)
        all_fills = sum(site.fills for site in shown if not site.test)
        return Websites(
            on=source is not None and source.active,
            key=key,
            script_url=self.script_url,
            snippet=snippet(self.script_url, key) if key else None,
            period_days=PERIOD_DAYS,
            sites=tuple(shown),
            views=all_views,
            leads=sum(site.leads for site in shown if not site.test),
            rate=_rate(all_fills, all_views),
            now=self.desk.now,
        )

    async def _site(self, site_id: UUID) -> LeadSite:
        self.desk._require_manager()
        site = await self.db.scalar(
            select(LeadSite)
            .where(LeadSite.id == site_id, LeadSite.tenant_id == self.tenant_id)
            .with_for_update()
        )
        if site is None or site.status == "removed":
            raise DeskError(404, "That website isn't connected any more.")
        return site

    async def add(self, command: NewSite) -> UUID:
        """A site named before its first visit (it shows as waiting), or one removed earlier
        and added back."""
        self.desk._require_manager()
        host = normalise_host(command.address)
        if host is None:
            raise DeskError(422, "Type the website's address, like yourbusiness.com.")
        await self.source(create=True)
        site = await self.db.scalar(
            select(LeadSite)
            .where(LeadSite.tenant_id == self.tenant_id, LeadSite.host == host)
            .with_for_update()
        )
        if site is None:
            if await _count(self.db, self.tenant_id) >= MAX_SITES:
                raise DeskError(422, f"A workspace can connect up to {MAX_SITES} websites.")
            site = _new_site(self.tenant_id, host, added="person", now=self.desk.now)
            site.created_by_person_id = self.desk.viewer.person_id
            self.db.add(site)
        elif site.status == "removed":
            site.status = "active"
            site.updated_at = self.desk.now
        await self.db.flush()
        return site.id

    async def set_status(self, site_id: UUID, status: Literal["active", "paused"]) -> None:
        site = await self._site(site_id)
        site.status = status
        site.updated_at = self.desk.now
        await self.db.flush()

    async def remove(self, site_id: UUID) -> None:
        site = await self._site(site_id)
        site.status = "removed"
        site.updated_at = self.desk.now
        await self.db.flush()

    async def test_lead(self, site_id: UUID, *, command_id: UUID) -> UUID | None:
        """A fictional visitor's form from this site, filed the way a visitor's is but as
        test data (Leads → Test leads), so a manager sees how website leads arrive."""
        site = await self._site(site_id)
        stamp = self.desk.now.strftime("%H%M%S")
        fields = [
            FormField("Full name", f"Website test {stamp}", "name"),
            FormField("Email", f"website-test-{stamp}@example.com", "email"),
            FormField("Message", "A test from the Websites card in Sales X-Ray.", "message"),
        ]
        attribution = {
            "utm_source": "sales-xray",
            "utm_medium": "test",
            "utm_campaign": "website-test",
            "page_url": f"https://{site.host}/",
        }
        record, mapping = record_of(
            fields,
            attribution=attribution,
            website={"host": site.host, "path": "/", "form": "Test", "test": True},
            host=site.host,
        )
        lead, _ = await self.desk.ingest(
            record,
            source="webhook",
            source_label=f"{SOURCE_LABEL} · {site.label}"[:120],
            source_ref=f"web-test:{command_id}",
            mapping=mapping,
            actor=self.desk.viewer.person_id,
            test_data=True,
            kind="website",
            command_id=command_id,
        )
        await self.db.flush()
        return lead.id if lead is not None else None

    async def rotate(self) -> None:
        self.desk._require_manager()
        source = await self.source(create=True)
        assert source is not None
        key = new_key()
        source.token_sha256 = key_hash(key)
        source.config = {**(source.config or {}), "website": {"key": key}}
        source.updated_at = self.desk.now
        await self.db.flush()


async def _count(db: Any, tenant_id: UUID) -> int:
    return int(
        await db.scalar(
            select(func.count()).where(
                LeadSite.tenant_id == tenant_id, LeadSite.status != "removed"
            )
        )
        or 0
    )


def _new_site(tenant_id: UUID, host: str, *, added: str, now: datetime) -> LeadSite:
    return LeadSite(
        id=uuid4(),
        tenant_id=tenant_id,
        host=host,
        label=host[:120],
        status="active",
        platform=None,
        added=added,
        first_seen_at=None,
        last_seen_at=None,
        last_page=None,
        leads=0,
        last_lead_at=None,
        created_by_person_id=None,
        created_at=now,
        updated_at=now,
    )


# ----- what the script sends (no session: the public key names the organisation) --------


@dataclass(frozen=True, slots=True)
class Visit:
    """A hello or a form fill, as read from the script's body and the request."""

    key: str
    host: str
    path: str
    page: str | None
    title: str | None


def read_visit(body: Mapping[str, Any], origin: str | None) -> Visit:
    key = str(body.get("k") or "")
    if not KEY_PATTERN.fullmatch(key):
        raise WebsiteError(401, "This website line has no Sales X-Ray key.")
    url = body.get("u")
    host = normalise_host(url)
    if host is None:
        raise WebsiteError(422, "Send the page's address.")
    if origin_host(origin) != host:
        # A browser always names the page it sends from; a mismatch is someone else's page.
        raise WebsiteError(403, "This page isn't the one the form is on.")
    return Visit(
        key=key,
        host=host,
        path=page_path(url),
        page=page_address(url),
        title=_text(body.get("t"), 200),
    )


async def _source_for(db: Any, key: str) -> LeadSource:
    source: LeadSource | None = await db.scalar(
        select(LeadSource).where(
            LeadSource.token_sha256 == key_hash(key), LeadSource.kind == "webhook"
        )
    )
    if source is None or not (source.config or {}).get("website"):
        raise WebsiteError(401, "This website line's key isn't in use any more.")
    if not source.active:
        raise WebsiteError(403, "Website leads are switched off in Sales X-Ray.")
    return source


async def _site_for(db: Any, source: LeadSource, host: str, now: datetime) -> LeadSite | None:
    """The site, added the first time it says hello (None when the workspace is full)."""
    site: LeadSite | None = await db.scalar(
        select(LeadSite).where(LeadSite.tenant_id == source.tenant_id, LeadSite.host == host)
    )
    if site is not None:
        return site
    if await _count(db, source.tenant_id) >= MAX_SITES:
        return None
    # Two first hellos at once: one row; the other finds it.
    await db.execute(
        insert(LeadSite)
        .values(
            id=uuid4(),
            tenant_id=source.tenant_id,
            host=host,
            label=host[:120],
            status="active",
            added="seen",
            leads=0,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "host"])
    )
    found: LeadSite | None = await db.scalar(
        select(LeadSite).where(LeadSite.tenant_id == source.tenant_id, LeadSite.host == host)
    )
    return found


async def _count_page(
    db: Any,
    site: LeadSite,
    path: str,
    *,
    day: date,
    now: datetime,
    title: str | None = None,
    views: int = 0,
    forms: int = 0,
    fills: int = 0,
    leads: int = 0,
    blocked: int = 0,
) -> None:
    """Add to one page's counters for the day. A site's 300th new page of the day and later
    ones count under "(other pages)", so a bot's made-up addresses can't fill the table."""
    exists = await db.scalar(
        select(func.count()).where(
            LeadSitePage.site_id == site.id, LeadSitePage.day == day, LeadSitePage.path == path
        )
    )
    if not exists:
        today = await db.scalar(
            select(func.count()).where(LeadSitePage.site_id == site.id, LeadSitePage.day == day)
        )
        if int(today or 0) >= MAX_PAGES_A_DAY:
            path, title = OTHER_PAGES, None
    statement = insert(LeadSitePage).values(
        site_id=site.id,
        day=day,
        path=path,
        tenant_id=site.tenant_id,
        title=title,
        views=views,
        forms=forms,
        fills=fills,
        leads=leads,
        blocked=blocked,
        updated_at=now,
    )
    table = LeadSitePage.__table__.c
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["site_id", "day", "path"],
            set_={
                "title": func.coalesce(statement.excluded.title, table.title),
                "views": table.views + statement.excluded.views,
                "forms": func.greatest(table.forms, statement.excluded.forms),
                "fills": table.fills + statement.excluded.fills,
                "leads": table.leads + statement.excluded.leads,
                "blocked": table.blocked + statement.excluded.blocked,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


async def hello(db: Any, body: Mapping[str, Any], origin: str | None) -> str:
    """A page with the line was opened: the site is seen, the page counted. Returns the
    site's state for the script ("active", "paused", "removed", "full")."""
    visit = read_visit(body, origin)
    source = await _source_for(db, visit.key)
    now = utcnow()
    site = await _site_for(db, source, visit.host, now)
    if site is None:
        return "full"
    if site.status == "removed":
        return "removed"
    forms = body.get("f")
    forms = min(forms, 50) if isinstance(forms, int) and forms >= 0 else 0
    platform = platform_of(body.get("p"))
    if (
        site.last_seen_at is None
        or now - site.last_seen_at >= SEEN_EVERY
        or (platform is not None and platform != site.platform)
    ):
        # One statement, so two pages opened at once can't undo each other.
        await db.execute(
            update(LeadSite)
            .where(LeadSite.id == site.id)
            .values(
                first_seen_at=func.coalesce(LeadSite.first_seen_at, now),
                last_seen_at=now,
                last_page=visit.page,
                platform=func.coalesce(platform, LeadSite.platform),
                updated_at=now,
            )
        )
    await _count_page(
        db, site, visit.path, day=now.date(), now=now, title=visit.title, views=1, forms=forms
    )
    await db.flush()
    return site.status


@dataclass(frozen=True, slots=True)
class Filed:
    outcome: str  # created | repeat | known | blocked | paused | removed | no_contact | full
    lead_id: UUID | None = None
    reason: str | None = None


async def file_lead(
    db: Any, body: Mapping[str, Any], origin: str | None, *, limiter: SiteLimiter = LIMITER
) -> Filed:
    """A visitor sent a lead form: one lead, stamped with its page and where it came from.
    A workspace with all its site slots taken still gets the lead; only the site's row and
    counters wait for a slot."""
    visit = read_visit(body, origin)
    source = await _source_for(db, visit.key)
    now = utcnow()
    site = await _site_for(db, source, visit.host, now)
    if site is not None and site.status != "active":
        return Filed(site.status)
    fields = clean_fields(body.get("fields"))
    reason = bot_reason(
        fields,
        webdriver=body.get("wd"),
        interactions=body.get("it"),
        elapsed_ms=body.get("ms"),
        trap=body.get("hp"),
    )
    day = now.date()
    if reason is not None:
        if site is not None:
            await _count_page(db, site, visit.path, day=day, now=now, blocked=1)
        return Filed("blocked", reason=reason)
    if not limiter.allow(f"{source.tenant_id}:{visit.host}"):
        raise WebsiteError(429, "Too many leads from this website just now. Try again soon.")
    desk = LeadDesk(
        db,
        Viewer(
            person_id=source.created_by_person_id,
            tenant_id=source.tenant_id,
            role="system",
            name=SOURCE_LABEL,
        ),
    )
    _, config = await desk.settings()
    contact = contact_of(fields, config["default_country"])
    if contact.phone is None and contact.email is None:
        return Filed("no_contact")
    attribution = clean_attribution(body.get("a"), page=visit.page, title=visit.title)
    record, mapping = record_of(
        fields,
        attribution=attribution,
        website={
            "host": visit.host,
            "path": visit.path,
            "form": _text(body.get("form"), 120),
            "platform": platform_of(body.get("p")),
            "user_agent": _text(body.get("ua"), 300),
        },
        host=visit.host,
    )
    # The lead takes the phone and email the contact check chose, not just the first marked.
    for name, label in (("phone", contact.phone_label), ("email", contact.email_label)):
        if label is not None:
            mapping[name] = label
        else:
            mapping.pop(name, None)
    label = site.label if site is not None else visit.host[:120]
    try:
        lead, outcome = await desk.ingest(
            record,
            source="webhook",
            source_label=f"{SOURCE_LABEL} · {label}"[:120],
            source_ref=resend_ref(
                visit.host, contact.phone, contact.email, sent_at(body.get("at"), now)
            ),
            mapping=mapping,
            actor=None,
            test_data=is_test_host(visit.host),
            kind="website",
        )
    except CaptureError as error:
        raise WebsiteError(422, str(error)) from None
    created = outcome == "created"
    if outcome in ("created", "repeat"):
        # Single statements, so two leads at once both count.
        await db.execute(
            update(LeadSource)
            .where(LeadSource.id == source.id)
            .values(received=LeadSource.received + 1, last_received_at=now)
        )
        if site is not None:
            await db.execute(
                update(LeadSite)
                .where(LeadSite.id == site.id)
                .values(
                    leads=LeadSite.leads + (1 if created else 0),
                    last_lead_at=now,
                    first_seen_at=func.coalesce(LeadSite.first_seen_at, now),
                    last_seen_at=now,
                    updated_at=now,
                )
            )
            await _count_page(
                db, site, visit.path, day=day, now=now, fills=1, leads=1 if created else 0
            )
    await db.flush()
    return Filed(outcome, lead.id if lead is not None else None)
