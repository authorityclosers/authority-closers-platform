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

from ac_platform.bug_reports.models import AREAS, MAX_FILES

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


def scrub_block(value: str, limit: int = 2 * 1024 * 1024) -> str:
    """Many lines of text (a log a person attached), each redacted; the lines stay."""
    lines = []
    for line in value[:limit].splitlines():
        for pattern, marker in _REDACTIONS:
            line = pattern.sub(marker, line)
        lines.append(line)
    return "\n".join(lines)


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
# 26 Oct 2026): never content, only the name, when, the page's route template and, since
# the advanced reporter (31 Oct 2026), the step's words from fixed lists. The app's names
# carry its prefix ("sx.tap"); the first pattern dropped them, so trails arrived empty.
MAX_TRAIL = 50
_STEP = re.compile(r"[a-z][a-z0-9_]{1,47}(?:\.[a-z][a-z0-9_]{1,47})?")
_STEP_AT = re.compile(r"[0-9T:.+\-Z]{10,40}")
_STEP_FIELDS = frozenset(
    {"screen", "from", "nav", "target", "feature", "via", "from_kind", "to_kind", "outcome"}
)
_STEP_WORD = re.compile(r"[a-z][a-z0-9_]{0,47}")


def clean_trail(value: object) -> list[dict[str, Any]]:
    """At most twenty recent app steps, each a known-shaped event name with its time and
    route; anything else is dropped."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[-MAX_TRAIL:]:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        if not isinstance(event, str) or _STEP.fullmatch(event) is None:
            continue
        step: dict[str, Any] = {"event": event}
        at = item.get("at")
        if isinstance(at, str) and _STEP_AT.fullmatch(at):
            step["at"] = at
        if isinstance(item.get("route"), str) and item["route"].strip():
            step["route"] = scrub_route(item["route"], 200)
        detail = item.get("detail")
        if isinstance(detail, dict):
            words = {
                key: value
                for key, value in detail.items()
                if key in _STEP_FIELDS and isinstance(value, str) and _STEP_WORD.fullmatch(value)
            }
            if words:
                step["detail"] = words
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


# The advanced reporter's own parts (owner, 31 Oct 2026): steps to reproduce, comments on
# parts of the screen (where each part is, never its text), slow or failed calls, speed.
MAX_STEPS = 20
MAX_COMMENTS = 20
MAX_CALLS = 15
_COMPONENT = re.compile(r"[A-Z][A-Za-z0-9]{2,40}")
_TAG = re.compile(r"[a-z][a-z0-9-]{0,24}")
_REFERENCE = re.compile(r"[A-Za-z0-9_.:-]{4,64}")
_SPEED_FIELDS = (
    "first_byte_ms",
    "ready_ms",
    "loaded_ms",
    "largest_paint_ms",
    "layout_shift",
    "memory_mb",
    "page_age_s",
)


def _whole(value: object, low: int, high: int) -> int | None:
    if isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high:
        return int(value)
    return None


def _items(value: object, limit: int) -> list[dict[str, Any]]:
    return (
        [item for item in value[:limit] if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def clean_advanced(value: object) -> dict[str, Any] | None:
    """The advanced reporter's parts, each bounded and scrubbed; None when there are none."""
    if not isinstance(value, dict):
        return None
    raw_steps = value.get("steps")
    steps = [
        text
        for text in (
            scrub_text(step, 200)
            for step in (raw_steps if isinstance(raw_steps, list) else [])[:MAX_STEPS]
        )
        if text
    ]
    comments: list[dict[str, Any]] = []
    for item in _items(value.get("comments"), MAX_COMMENTS):
        number = _whole(item.get("n"), 1, 50)
        if number is None:
            continue
        components = item.get("components")
        entry: dict[str, Any] = {
            "n": number,
            "note": scrub_text(item.get("note"), 500),
            "selector": scrub_text(item.get("selector"), 400),
            "components": [
                name
                for name in (components if isinstance(components, list) else [])[:3]
                if isinstance(name, str) and _COMPONENT.fullmatch(name)
            ],
            "on_picture": item.get("on_picture") is True,
        }
        testid = scrub_text(item.get("testid"), 80)
        if testid:
            entry["testid"] = testid
        tag = item.get("tag")
        if isinstance(tag, str) and _TAG.fullmatch(tag):
            entry["tag"] = tag
        role = scrub_text(item.get("role"), 40)
        if role:
            entry["role"] = role
        raw_box = item.get("box")
        box: dict[str, Any] = raw_box if isinstance(raw_box, dict) else {}
        where = {key: _whole(box.get(key), -20_000, 20_000) for key in ("x", "y", "w", "h")}
        if all(number is not None for number in where.values()):
            entry["box"] = where
        comments.append(entry)
    calls: list[dict[str, Any]] = []
    for item in _items(value.get("calls"), MAX_CALLS):
        path = item.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            continue
        call: dict[str, Any] = {
            "path": scrub_route(path, 200),
            "failed": item.get("failed") is True,
        }
        if item.get("method") in METHODS:
            call["method"] = item["method"]
        status = _whole(item.get("status"), 0, 599)
        if status is not None:
            call["status"] = status
        took = _whole(item.get("ms"), 0, 600_000)
        if took is not None:
            call["ms"] = took
        reference = item.get("reference")
        if isinstance(reference, str) and _REFERENCE.fullmatch(reference):
            call["reference"] = reference
        calls.append(call)
    given_speed = value.get("speed")
    raw_speed: dict[str, Any] = given_speed if isinstance(given_speed, dict) else {}
    speed = {
        key: round(float(raw_speed[key]), 3)
        for key in _SPEED_FIELDS
        if isinstance(raw_speed.get(key), int | float)
        and not isinstance(raw_speed.get(key), bool)
        and 0 <= raw_speed[key] < 10_000_000
    }
    return {
        "steps": steps,
        "comments": comments,
        "calls": calls,
        "speed": speed,
        "marked": value.get("marked") is True,
        "files": _whole(value.get("files"), 0, MAX_FILES) or 0,
    }


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
