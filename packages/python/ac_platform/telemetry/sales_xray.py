"""Sales X-Ray product telemetry (owner, 22 Oct 2026: "optimize based on user telemetry… better
quality and very cheap").

What people do in Sales X-Ray, as counts for Admin and the cost optimiser: reports opened,
report sections read and for how long, what people do in a section, on-demand, full-report and
re-analyse taps, outcomes saved and errors shown. Since 24 Oct 2026 (owner: "Build full
performance and usage telemetry") also how the app performs: screens and the flow between them,
tap-to-response time for key actions, Web Vitals, app start, script errors, slow API calls, rage
and dead taps and feature use. The client (``apps/sales-xray-web/app/telemetry.ts`` and
``telemetry-auto.tsx``) sends these; the server takes only the events below. Who it is recorded
for (on by default, any person or workspace can turn it off) is ``sales_xray_consent.py``.

- Every payload value is one of a fixed set, a short code token, a version or fingerprint
  label, a bounded number or a flag: no free text, no call content, no lead names or numbers,
  nothing personal. The device class, device tier, network, app and app version may ride on
  any event.
- A call is named only by ``call_ref``: ``c_`` and 16 hex characters of HMAC(this
  environment's metrics key, ``call:`` and the recording id), filled in by the server after it
  finds the call in the caller's workspace. The cost export can make the same reference, so
  "cost per useful report" joins without either side holding a call id.
- Events are disposable analytics (``analytics_events``): never progress, payment, access or
  score state (AGENTS.md). Kept 180 days; at most 2,000 per person in any 24 hours.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.brain4 import DIMENSION_IDS
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.telemetry.ingest import (
    SALES_XRAY_ROUTE_TEMPLATES,
    TelemetryEventDefinition,
    TelemetrySurface,
)
from ac_platform.usage_people.pseudonyms import ensure_key

RETENTION_DAYS = 180
RETENTION_POLICY_ID = "sx-product-analytics-v1"
PERSON_DAILY_CAP = 2000
PROVENANCE_SOURCE = "authenticated_sales_xray_api"
PROVENANCE_VERSION = "sales-xray-product-telemetry-v1"

CALL_REF_PREFIX = "c_"
CALL_REF_LENGTH = 16

# Longest a section read counts for, so a report left open on a desk does not skew dwell.
MAX_DWELL_MS = 600_000

_DEVICES = frozenset({"phone", "tablet", "desktop"})
_APPS = frozenset({"web", "android"})
# How capable the device is (its cores and memory), its network speed and link as the browser
# reports them: what makes "40% of devices are slow when clicking a lead" answerable.
TIERS = frozenset({"low", "mid", "high", "unknown"})
NETWORKS = frozenset({"slow_2g", "2g", "3g", "4g", "unknown"})
LINKS = frozenset({"wifi", "cellular", "ethernet", "offline", "unknown"})
# The app's screens, one per route template (telemetry.ts screenOf), and a lead open on Leads.
SCREENS = frozenset(
    {
        "home",
        "dashboard",
        "analysis",
        "new_call",
        "calls_list",
        "report",
        "calls",
        "leads",
        "lead",
        "chats",
        "coaching",
        "prospects",
        "prospect",
        "organisation",
        "org_insights",
        "org_invites",
        "org_person",
        "settings",
        "settings_section",
        "account",
        "billing",
        "plans",
        "apps",
        "developers",
        "review",
        "other",
    }
)
# Key actions whose tap-to-response time is measured (telemetry-auto.tsx actionOf).
ACTIONS = frozenset(
    {
        "lead_open",
        "call_start",
        "tab_switch",
        "outcome_save",
        "report_open",
        "nav_switch",
        "sheet_open",
        "search",
        "save",
        "send",
        "filter",
        "back",
        "other",
    }
)
TAP_TARGETS = frozenset(
    {"button", "link", "tab", "row", "card", "input", "icon", "text", "image", "other"}
)
VITALS = frozenset({"lcp", "inp", "cls", "fcp", "ttfb"})
RATINGS = frozenset({"good", "needs_improvement", "poor"})
ERROR_KINDS = frozenset({"error", "rejection", "react", "chunk"})
ERROR_NAMES = frozenset(
    {
        "typeerror",
        "referenceerror",
        "rangeerror",
        "syntaxerror",
        "chunkloaderror",
        "aborterror",
        "networkerror",
        "securityerror",
        "notallowederror",
        "quotaexceedederror",
        "error",
        "other",
    }
)
ERROR_SOURCES = frozenset({"app", "vendor", "extension", "unknown"})
API_STATUSES = frozenset({"2xx", "3xx", "4xx", "5xx", "network", "unknown"})
# Longest a tap is timed for, a screen is stayed on and a start or vital is counted.
MAX_ACTION_MS = 60_000
# Lead OS (24 Oct 2026): a lead's desk stage kinds, Junk included, never a business's labels.
LEAD_KINDS = frozenset({"new", "not_connected", "follow_up", "interested", "won", "lost", "junk"})
WAIT_BANDS = frozenset({"under_2m", "2_to_5m", "5_to_15m", "over_15m", "unknown"})
MAX_WAIT_MS = 3_600_000
YES_NO = ("yes", "no")
PERMISSION_STATES = ("granted", "denied", "not_in_build")
# The Android app's own permissions, by short names the intake's personal-data guard allows.
APP_PERMISSIONS = ("calls", "rec_files", "notifications", "mic", "all_files", "folder", "call_log")
MAX_STAY_MS = 1_800_000
MAX_LOAD_MS = 120_000
# The Report's parts as its components name them (xray-report/panels.tsx: Overview, the AI
# coaching score or detailed analysis, Final Call Outcome, Prospect's Information) and the
# call's other tabs. One skill of the coaching score is "analysis" with its ``skill``.
REPORT_SECTIONS = frozenset(
    {"overview", "analysis", "outcome", "prospect-information", "coaching", "transcript"}
)
# Brain 4.0's 18 skills, "d01" to "d18" (the client sends lower case only).
SKILLS = frozenset(dimension.lower() for dimension in DIMENSION_IDS)
# Which Report the call showed: the Brain 4.0 coaching score or the earlier pointers.
LOOKS = frozenset({"brain4", "pointers"})
READ_BANDS = frozenset({"under_5s", "5_30s", "30_120s", "over_120s"})
SECTION_ACTIONS = frozenset({"expand", "collapse", "copy", "clip", "helpful", "not_helpful"})
# The call's AI-on-calls level when the person tapped (call-ai-client.ts).
AI_LEVELS = frozenset({"off", "data_only", "auto", "full"})


def _event(
    *,
    values: Mapping[str, Iterable[str]] | None = None,
    numbers: Mapping[str, float] | None = None,
    tokens: Iterable[str] = (),
    labels: Iterable[str] = (),
    required: Iterable[str] = (),
    takes_call: bool = False,
) -> TelemetryEventDefinition:
    # Every event may say where it ran: device class and tier, network and link, app.
    typed = {"device": _DEVICES, "app": _APPS, "tier": TIERS, "net": NETWORKS, "link": LINKS}
    typed.update({key: frozenset(items) for key, items in (values or {}).items()})
    limits = dict(numbers or {})
    codes = frozenset(tokens)
    names = frozenset({"app_version", *labels})
    keys = tuple(sorted({*typed, *limits, *codes, *names}))
    return TelemetryEventDefinition(
        event_version="1.0",
        allowed_payload_keys=keys,
        values=MappingProxyType(typed),
        numbers=MappingProxyType(limits),
        tokens=codes,
        labels=names,
        required=frozenset(required),
        takes_call=takes_call,
    )


SALES_XRAY_EVENTS: Mapping[str, TelemetryEventDefinition] = MappingProxyType(
    {
        "sx.sign_in": _event(
            values={"method": ("password", "email_code", "google")}, required=("method",)
        ),
        "sx.sign_out": _event(),
        "sx.upload_started": _event(
            values={
                "size_band": ("under_5mb", "5_to_20mb", "over_20mb"),
                "format": ("mp3", "wav", "m4a", "ogg", "flac", "other"),
            }
        ),
        "sx.upload_finished": _event(
            values={"outcome": ("saved", "interrupted", "cancelled")},
            numbers={"seconds": 86_400},
            required=("outcome",),
        ),
        "sx.analysis_seen_done": _event(
            values={"wait_band": ("under_2m", "2_to_5m", "5_to_15m", "over_15m", "unknown")}
        ),
        # A report shown: the view it opened in, brief (one pass) or full, and where from.
        "sx.report_opened": _event(
            values={
                "view": ("report", "coaching", "transcript", "document", "share"),
                "level": ("brief", "full"),
                "source": ("calls", "lead", "prospect", "notification", "link", "upload", "other"),
            },
            required=("view",),
            takes_call=True,
        ),
        # One report section read: its band (and the milliseconds, capped), sent when it
        # leaves the screen or the page is hidden.
        "sx.section_read": _event(
            values={
                "section": REPORT_SECTIONS,
                "skill": SKILLS,
                "look": LOOKS,
                "read_band": READ_BANDS,
            },
            numbers={"dwell_ms": MAX_DWELL_MS},
            required=("section", "read_band"),
            takes_call=True,
        ),
        "sx.section_action": _event(
            values={"section": REPORT_SECTIONS, "skill": SKILLS, "action": SECTION_ACTIONS},
            required=("section", "action"),
            takes_call=True,
        ),
        # A section's deeper analysis asked for on demand.
        "sx.on_demand_requested": _event(
            values={"section": REPORT_SECTIONS, "level": AI_LEVELS},
            required=("section", "level"),
            takes_call=True,
        ),
        # "Get full report" for the whole call.
        "sx.full_report_requested": _event(
            values={"surface": ("call", "report", "lead", "calls"), "level": AI_LEVELS},
            required=("surface",),
            takes_call=True,
        ),
        "sx.reanalyse_requested": _event(
            values={"surface": ("call", "report", "lead", "calls")},
            required=("surface",),
            takes_call=True,
        ),
        "sx.coaching_opened": _event(values={"scope": ("call", "mine", "team")}),
        "sx.clip_played": _event(values={"kind": ("preview", "full")}),
        "sx.paywall_seen": _event(tokens=("surface",)),
        "sx.paywall_clicked": _event(tokens=("surface", "action")),
        "sx.mission_started": _event(),
        "sx.mission_completed": _event(),
        "sx.prospect_edited": _event(tokens=("field",)),
        "sx.outcome_set": _event(tokens=("outcome",), required=("outcome",), takes_call=True),
        "sx.error_shown": _event(tokens=("surface", "code"), required=("surface", "code")),
        # Performance and usage (owner, 24 Oct 2026). A screen shown, the one before it and
        # how long that one was stayed on: flows, drop-offs and the screen heatmap.
        "sx.screen_viewed": _event(
            values={
                "screen": SCREENS,
                "from": SCREENS | {"none"},
                "nav": ("first", "push", "back", "reload"),
            },
            numbers={"stay_ms": MAX_STAY_MS},
            required=("screen", "nav"),
        ),
        # Tap to response: from the tap to the screen settling (no change for 150 ms), and
        # the browser's own input-to-paint time for the same tap.
        "sx.action_timing": _event(
            values={
                "action": ACTIONS,
                "result": ("settled", "timeout", "no_change"),
                "screen": SCREENS,
            },
            numbers={"ms": MAX_ACTION_MS, "paint_ms": MAX_ACTION_MS},
            required=("action", "ms", "result"),
        ),
        # Core Web Vitals per screen; CLS is sent times 1,000.
        "sx.web_vital": _event(
            values={"metric": VITALS, "rating": RATINGS, "screen": SCREENS},
            numbers={"value": MAX_LOAD_MS},
            required=("metric", "value"),
        ),
        # The app's start: from the page or app opening to the first screen working.
        "sx.app_start": _event(
            values={
                "start": ("cold", "warm"),
                "nav_type": ("navigate", "reload", "back_forward", "prerender"),
                "screen": SCREENS,
            },
            numbers={"ms": MAX_LOAD_MS},
            required=("start", "ms"),
        ),
        # A script error: its kind and class, and a fingerprint of where it was thrown (a
        # hash of the error class and the top stack frame's file and line), never its text.
        "sx.js_error": _event(
            values={
                "kind": ERROR_KINDS,
                "error": ERROR_NAMES,
                "source": ERROR_SOURCES,
                "screen": SCREENS,
            },
            labels=("where",),
            required=("kind", "error"),
        ),
        # An API call slower than 1.5 s or failed: its route with every id taken out.
        "sx.api_slow": _event(
            values={"status": API_STATUSES, "screen": SCREENS},
            tokens=("endpoint",),
            numbers={"ms": MAX_LOAD_MS},
            required=("endpoint", "status", "ms"),
        ),
        # Three or more taps in a second on one spot, or a tap that changed nothing.
        "sx.tap_issue": _event(
            values={
                "kind": ("rage", "dead"),
                "target": TAP_TARGETS,
                "action": ACTIONS,
                "screen": SCREENS,
            },
            required=("kind", "target"),
        ),
        # A named feature used (the screens name them), for adoption.
        "sx.feature_used": _event(
            values={"screen": SCREENS}, tokens=("feature",), required=("feature",)
        ),
        # Lead OS (24 Oct 2026, asked by the Lead OS session): the pipeline board and sheet.
        # A stage move: how it was made, whether an AI suggestion made it, the stage kinds
        # either side, how many required fields it asked for, and the wait from opening the
        # stage sheet to saving.
        "sx.lead_stage_moved": _event(
            values={
                "via": ("board", "sheet", "after_call", "table", "bulk", "meeting"),
                "source": ("seller", "ai_suggestion"),
                "from_kind": LEAD_KINDS,
                "to_kind": LEAD_KINDS,
                "wait": WAIT_BANDS,
            },
            numbers={"needs": 4, "wait_ms": MAX_WAIT_MS},
            required=("via", "to_kind"),
        ),
        "sx.board_drag": _event(
            values={"result": ("moved", "sheet", "refused", "undone")}, required=("result",)
        ),
        # From opening a lead to its first call, message or move.
        "sx.lead_open_to_action": _event(
            values={"wait": WAIT_BANDS, "first": ("call", "message", "move")},
            numbers={"wait_ms": MAX_WAIT_MS},
            required=("wait",),
        ),
        # The Android app (1.0.25, asked by the Android session): collected by the app,
        # sent by the page under the same switch (telemetry-auto.tsx drains the bridge).
        # Launch: process start or resume to first paint, and whether the app pages or
        # the live site were shown.
        "sx.app_launch": _event(
            values={"start": ("cold", "warm"), "pages": ("app", "live")},
            numbers={"ms": MAX_ACTION_MS},
            required=("start", "ms"),
        ),
        # Frames drawn in a session, slow (over 16.7 ms) and frozen (over 700 ms).
        "sx.app_frames": _event(
            numbers={
                "frames": 10_000_000,
                "slow": 10_000_000,
                "frozen": 10_000_000,
                "p90_ms": 1_000,
            },
            required=("frames",),
        ),
        # Why the app last closed (Android 11+), counted once each.
        "sx.app_exit": _event(
            values={
                "reason": (
                    "anr",
                    "crash",
                    "crash_native",
                    "low_memory",
                    "excessive_resource",
                    "killed_by_system",
                    "other",
                ),
                "foreground": YES_NO,
            },
            required=("reason",),
        ),
        # Once a day: the phone's make and model, versions and tiers (never an identifier).
        "sx.device_profile": _event(
            values={
                "ram_tier": ("2", "3", "4", "6", "8", "12plus"),
                "low_ram": YES_NO,
                "storage_free": ("lt1", "1to4", "4to16", "16plus"),
                "store": ("direct", "play"),
            },
            numbers={"android": 100, "memory_class": 65_536},
            tokens=("maker",),
            labels=("model_label", "webview"),
        ),
        "sx.device_state": _event(
            values={
                "battery_saver": YES_NO,
                "battery_unrestricted": YES_NO,
                "standby_bucket": (
                    "exempted",
                    "active",
                    "working_set",
                    "frequent",
                    "rare",
                    "restricted",
                    "unknown",
                ),
                "notifications": ("on", "off"),
            }
        ),
        "sx.network_state": _event(
            values={
                "transport": ("wifi", "cellular", "ethernet", "vpn", "other", "none"),
                "metered": YES_NO,
                "validated": YES_NO,
                "down_tier": ("unknown", "lt1", "1to5", "5to20", "20plus"),
                "cell_gen": ("2g", "3g", "4g", "5g", "unknown"),
            }
        ),
        # When a permission changes: each of the app's permissions, granted or not.
        "sx.permission_snapshot": _event(
            values={permission: PERMISSION_STATES for permission in APP_PERMISSIONS}
        ),
        "sx.lead_suggestion": _event(
            values={
                "action": ("shown", "accepted", "changed", "dismissed"),
                "from": ("call", "chat", "rule"),
            },
            required=("action",),
        ),
    }
)

# The words people are shown about usage analytics, one entry per version (the Sales X-Ray
# privacy page's "Usage analytics" section, word for word; a test pins them). Every stored
# event and every opt-out or opt-in records the version. A change of words is a new version,
# never an edit (supersede, never overwrite).
# v1 (24 Oct 2026, 00:00 IST) was the web app's alone; v2 adds what the Android app records
# (1.0.25) and Firebase Crashlytics, so its words change and so does the version.
NOTICE_V1 = "sx-product-analytics-2026-10-24-v1"
NOTICE_VERSION = "sx-product-analytics-2026-10-24-v2"
# v2 is in force from 22:30 UTC on 23 Oct 2026 (04:00 IST, 24 Oct).
NOTICE_EFFECTIVE_AT = datetime(2026, 10, 23, 22, 30, tzinfo=UTC)
NOTICES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        NOTICE_V1: (
            "Sales X-Ray records how its app is used and how fast it responds, to make it "
            "faster, easier to use and cheaper to run. It records the screens and report "
            "sections you open and for how long, taps and how quickly the app responds to "
            "them, errors, page speed, the app version and the type of device and network. "
            "It never records call content, transcripts, lead names, phone numbers or email "
            "addresses. Records are kept for 180 days and are never used to score you or to "
            "set your access, payments or plan.",
            "This is on in every workspace unless it is turned off. You can turn it off for "
            "yourself at any time in Settings, Privacy; an owner or admin can turn it off for "
            "the whole workspace there. Sandbox workspaces never record it.",
        ),
        NOTICE_VERSION: (
            "Sales X-Ray records how its app is used and how fast it responds, to make it faster, "
            "easier to use and cheaper to run. It records the screens and report sections you open"
            " and for how long, taps and how quickly the app responds to them, errors, page speed,"
            " the app version and the type of device and network. In the Android app it also "
            "records how the app itself runs (how fast it starts, how smoothly it draws and why it"
            " last closed), the phone's make, model, Android and WebView versions, its memory and "
            "free-storage tier, its battery-saver and notification settings, its network type and "
            "speed tier, and which of the app's permissions are on. It never records call content,"
            " transcripts, lead names, phone numbers, email addresses, contacts or location. "
            "Records are kept for 180 days and are never used to score you or to set your access, "
            "payments or plan.",
            "This is on in every workspace unless it is turned off. You can turn it off for "
            "yourself at any time in Settings, Privacy; an owner or admin can turn it off for the "
            "whole workspace there. Sandbox workspaces never record it. Crash reports from the "
            "Android app go to Firebase Crashlytics (provided by Google); from app version 1.0.25 "
            "they stop too when this is turned off.",
        ),
    }
)


def call_ref(inner: bytes, outer: bytes, recording_id: UUID | str) -> str:
    """``c_`` and 16 hex characters of HMAC(key, ``call:`` and the recording id)."""
    message = f"call:{recording_id}".encode()
    digest = hashlib.sha256(outer + hashlib.sha256(inner + message).digest()).hexdigest()
    return CALL_REF_PREFIX + digest[:CALL_REF_LENGTH]


def call_refs(
    connection: Any, tenant_id: UUID, call_ids: frozenset[UUID], now: datetime
) -> dict[UUID, str]:
    """Each call id found in this workspace, with its recording's reference."""
    if not call_ids:
        return {}
    rows = connection.execute(
        select(
            ConversationGuestSubmission.submission_id, ConversationGuestSubmission.recording_id
        ).where(
            ConversationGuestSubmission.tenant_id == tenant_id,
            ConversationGuestSubmission.submission_id.in_(sorted(call_ids)),
        )
    ).all()
    if not rows:
        return {}
    inner, outer = ensure_key(connection, now)
    return {submission: call_ref(inner, outer, recording) for submission, recording in rows}


SALES_XRAY_SURFACE = TelemetrySurface(
    events=SALES_XRAY_EVENTS,
    routes=frozenset(SALES_XRAY_ROUTE_TEMPLATES),
    provenance_source=PROVENANCE_SOURCE,
    provenance_version=PROVENANCE_VERSION,
    disclaimer=(
        "Sales X-Ray product telemetry is disposable usage and performance analytics, on unless "
        "a person or workspace turns it off: screens and report sections opened and for how "
        "long, taps and response times, errors and page speed, never call content. It never "
        "creates progress, payment, access, audit or scoring state."
    ),
    call_refs=call_refs,
    person_daily_cap=PERSON_DAILY_CAP,
    purge_every=timedelta(hours=1),
)


class SalesXrayAdmission:
    """A coarse per-process shield: at most ``per_minute`` events per workspace a minute.

    The durable limit is the per-person daily cap the intake counts in the database.
    """

    def __init__(
        self, *, per_minute: int = 1200, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._windows: dict[UUID, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def admit(self, *, tenant_id: UUID, event_count: int, payload_bytes: int) -> bool:
        now = self._clock()
        with self._lock:
            start, used = self._windows.get(tenant_id, (now, 0))
            if now - start >= 60:
                start, used = now, 0
            if used + event_count > self._per_minute:
                return False
            self._windows[tenant_id] = (start, used + event_count)
            if len(self._windows) > 10_000:
                for key, (began, _) in list(self._windows.items()):
                    if now - began >= 60:
                        del self._windows[key]
            return True


__all__ = [
    "ACTIONS",
    "AI_LEVELS",
    "CALL_REF_PREFIX",
    "LEAD_KINDS",
    "LINKS",
    "LOOKS",
    "MAX_ACTION_MS",
    "MAX_DWELL_MS",
    "NETWORKS",
    "APP_PERMISSIONS",
    "NOTICES",
    "NOTICE_V1",
    "NOTICE_EFFECTIVE_AT",
    "NOTICE_VERSION",
    "PERSON_DAILY_CAP",
    "READ_BANDS",
    "REPORT_SECTIONS",
    "RETENTION_DAYS",
    "RETENTION_POLICY_ID",
    "SALES_XRAY_EVENTS",
    "SALES_XRAY_SURFACE",
    "SCREENS",
    "SECTION_ACTIONS",
    "SKILLS",
    "TIERS",
    "SalesXrayAdmission",
    "call_ref",
    "call_refs",
]
