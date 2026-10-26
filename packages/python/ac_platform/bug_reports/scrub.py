"""What a bug report may carry about the screen, the device and recent errors.

The device scrubs before it sends; the server scrubs again and keeps only the fields listed
here, so a report never stores secrets, sign-in codes, contact details, transcripts or call
content. Free text is cut short; anything shaped like a token, key, email address or phone
number becomes a marker.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from ac_platform.bug_reports.models import AREAS

MAX_ERRORS = 20
ERROR_KINDS = ("error", "rejection", "console", "notice", "http")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # JSON web tokens and bearer headers.
    (re.compile(r"\beyJ[\w-]{6,}\.[\w-]{6,}\.[\w-]{6,}"), "[token]"),
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]{8,}"), "Bearer [token]"),
    # Our keys and common provider key shapes.
    (re.compile(r"\b(?:ac_(?:live|test)|sk|pk|rk|whsec|AIza)[\w-]{10,}"), "[key]"),
    (
        re.compile(r"(?i)\b(?:password|passwd|secret|token|otp|cookie|api[_-]?key)\s*[:=]\s*\S+"),
        "[secret]",
    ),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    # Long opaque strings: hex digests, base64 blobs, signed URL parts.
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}"), "[long]"),
    # Phone numbers: nine or more digits with optional separators.
    (re.compile(r"(?<![\w-])\+?\d(?:[\s().-]?\d){8,}(?![\w-])"), "[phone]"),
)

# An id in a route (a UUID, a number, or a long opaque part with a digit) becomes ":id", so
# a route is the screen's pattern (#15, 26 Oct 2026: "/analysis/calls/<uuid>" was "/[long]").
_ID_PART = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|[0-9]+|(?=[A-Za-z_-]*[0-9])[A-Za-z0-9_-]{16,}",
    re.I,
)
# Query keys whose values are always dropped from a route.
_SECRET_KEYS = re.compile(
    r"(?i)token|code|key|secret|password|state|auth|session|email|phone|mobile|signature|sig"
)
# First match wins: a call's own page is its Report, the rest of /analysis is Calls.
_ROUTE_AREAS: tuple[tuple[str, str], ...] = (
    ("/leads", "leads"),
    ("/prospects", "leads"),
    ("/chats", "chats"),
    ("/calls", "calls"),
    ("/analysis/calls/", "report"),
    ("/analysis", "calls"),
    ("/coaching", "coaching"),
    ("/settings", "settings"),
    ("/account", "settings"),
    ("/organisation", "settings"),
    ("/billing", "settings"),
    ("/plans", "settings"),
    ("/developers", "settings"),
    ("/connect", "settings"),
    ("/login", "sign_in"),
    ("/auth", "sign_in"),
    ("/dashboard", "home"),
)


def scrub_text(value: object, limit: int) -> str:
    """One line of plain text, redacted and cut to ``limit`` characters."""
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    for pattern, marker in _REDACTIONS:
        text = pattern.sub(marker, text)
    return text[:limit]


def _route_part(value: str, limit: int) -> str:
    """One part of a route: an id becomes ":id", anything else is scrubbed like text."""
    return ":id" if _ID_PART.fullmatch(value) else scrub_text(value, limit)


def scrub_route(value: object, limit: int = 512) -> str:
    """A route's pattern: ids become ":id", secret-looking query values are dropped, each
    part is scrubbed on its own (a redaction never spans a "/"), and there is no fragment."""
    if not isinstance(value, str) or not value.strip():
        return "/"
    parts = urlsplit(value.strip())
    path = "/".join(_route_part(segment, 80) for segment in parts.path.split("/"))
    path = path if path.startswith("/") else "/" + path
    query = [
        (scrub_text(key, 40), "" if _SECRET_KEYS.search(key) else _route_part(val, 80))
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
    ][:12]
    route = path + ("?" + urlencode(query, safe=":[]") if query else "")
    return route[:limit] or "/"


def area_for(route: str, hint: object = None) -> str:
    """The product area a route belongs to; the device's hint only when it is known."""
    path = urlsplit(route).path.rstrip("/") or "/"
    for prefix, area in _ROUTE_AREAS:
        if prefix.endswith("/"):
            if path.startswith(prefix) and len(path) > len(prefix):
                return area
        elif path == prefix or path.startswith(prefix + "/"):
            return area
    if path == "/":
        return "home"
    return hint if isinstance(hint, str) and hint in AREAS else "other"


_STRING_FIELDS: dict[str, dict[str, int]] = {
    "app": {
        "version": 40,
        "release": 40,
        "build": 64,
        "native_version": 40,
        "native_build": 40,
        # The screen's name (telemetry's screenOf, #15), e.g. "report".
        "page": 40,
    },
    "device": {
        "platform": 40,
        "os": 40,
        "browser": 60,
        "model": 60,
        "viewport": 20,
        "screen": 20,
        "language": 20,
        "timezone": 64,
    },
}
_ENUM_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "app": {"channel": ("web", "android", "ios", "desktop")},
    "device": {"theme": ("light", "dark"), "connection": ("2g", "3g", "4g", "slow-2g", "wifi")},
}
_BOOL_FIELDS: dict[str, tuple[str, ...]] = {
    "app": (),
    "device": ("mobile", "touch", "online", "standalone"),
}
_NUMBER_FIELDS: dict[str, tuple[str, ...]] = {
    "app": (),
    "device": ("pixel_ratio", "memory_gb"),
}


# The last app steps before a report (telemetry event names, oldest first; demo P0,
# 26 Oct 2026): never content, only the name, when and the page's route template.
MAX_TRAIL = 20
_STEP = re.compile(r"[a-z][a-z0-9_]{1,63}")
_STEP_AT = re.compile(r"[0-9T:.+\-Z]{10,40}")


def clean_trail(value: object) -> list[dict[str, str]]:
    """At most twenty recent app steps, each a known-shaped event name with its time and
    route; anything else is dropped."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for item in value[-MAX_TRAIL:]:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        if not isinstance(event, str) or _STEP.fullmatch(event) is None:
            continue
        step = {"event": event}
        at = item.get("at")
        if isinstance(at, str) and _STEP_AT.fullmatch(at):
            step["at"] = at
        if isinstance(item.get("route"), str) and item["route"].strip():
            step["route"] = scrub_route(item["route"], 200)
        out.append(step)
    return out


def clean_context(value: object) -> dict[str, Any]:
    """Only the app and device fields listed above, each bounded, and the trail."""
    raw = value if isinstance(value, dict) else {}
    out: dict[str, Any] = {}
    for group in ("app", "device"):
        source = raw.get(group)
        source = source if isinstance(source, dict) else {}
        kept: dict[str, Any] = {}
        for key, limit in _STRING_FIELDS[group].items():
            text = scrub_text(source.get(key), limit)
            if text:
                kept[key] = text
        for key, options in _ENUM_FIELDS[group].items():
            if source.get(key) in options:
                kept[key] = source[key]
        for key in _BOOL_FIELDS[group]:
            if isinstance(source.get(key), bool):
                kept[key] = source[key]
        for key in _NUMBER_FIELDS[group]:
            number = source.get(key)
            if (
                isinstance(number, int | float)
                and not isinstance(number, bool)
                and 0 <= number < 1000
            ):
                kept[key] = round(float(number), 2)
        out[group] = kept
    trail = clean_trail(raw.get("trail"))
    if trail:
        out["trail"] = trail
    return out


def clean_errors(value: object) -> list[dict[str, Any]]:
    """At most twenty recent client errors, newest last, each with known fields only."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[-MAX_ERRORS:]:
        if not isinstance(item, dict) or item.get("kind") not in ERROR_KINDS:
            continue
        entry: dict[str, Any] = {"kind": item["kind"]}
        at = item.get("at")
        if isinstance(at, str) and re.fullmatch(r"[0-9T:.+\-Z]{10,40}", at):
            entry["at"] = at
        message = scrub_text(item.get("message"), 300)
        if message:
            entry["message"] = message
        raw_source = item.get("source")
        source = (
            scrub_route(raw_source, 200)
            if isinstance(raw_source, str) and raw_source.startswith("/")
            else scrub_text(raw_source, 200)
        )
        if source:
            entry["source"] = source
        reference = item.get("reference")
        if isinstance(reference, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{4,64}", reference):
            entry["reference"] = reference
        status = item.get("status")
        if isinstance(status, int) and not isinstance(status, bool) and 0 <= status < 600:
            entry["status"] = status
        if item.get("method") in METHODS:
            entry["method"] = item["method"]
        if isinstance(item.get("path"), str):
            entry["path"] = scrub_route(item["path"], 200)
        out.append(entry)
    return out
