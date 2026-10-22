"""Sales X-Ray product telemetry (owner, 22 Oct 2026: "optimize based on user telemetry… better
quality and very cheap").

What people do in Sales X-Ray, as counts for Admin and the cost optimiser: reports opened,
report sections read and for how long, what people do in a section, on-demand, full-report and
re-analyse taps, outcomes saved and errors shown. The client
(``apps/sales-xray-web/app/telemetry.ts``) sends these; the server takes only the events below.

- Every payload value is one of a fixed set, a short code token, a bounded number or a flag:
  no free text, no call content, nothing personal. ``device`` and ``app`` may ride on any event.
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
from datetime import datetime
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
    required: Iterable[str] = (),
    takes_call: bool = False,
) -> TelemetryEventDefinition:
    typed = {"device": _DEVICES, "app": _APPS}
    typed.update({key: frozenset(items) for key, items in (values or {}).items()})
    limits = dict(numbers or {})
    codes = frozenset(tokens)
    keys = tuple(sorted({*typed, *limits, *codes}))
    return TelemetryEventDefinition(
        event_version="1.0",
        allowed_payload_keys=keys,
        values=MappingProxyType(typed),
        numbers=MappingProxyType(limits),
        tokens=codes,
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
        "Sales X-Ray product telemetry is consented, disposable analytics only: what screens "
        "and report sections people open, for how long, taps and errors, never call content. "
        "It never creates progress, payment, access, audit or scoring state."
    ),
    call_refs=call_refs,
    person_daily_cap=PERSON_DAILY_CAP,
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
    "AI_LEVELS",
    "CALL_REF_PREFIX",
    "LOOKS",
    "MAX_DWELL_MS",
    "PERSON_DAILY_CAP",
    "READ_BANDS",
    "REPORT_SECTIONS",
    "RETENTION_DAYS",
    "RETENTION_POLICY_ID",
    "SALES_XRAY_EVENTS",
    "SALES_XRAY_SURFACE",
    "SECTION_ACTIONS",
    "SKILLS",
    "SalesXrayAdmission",
    "call_ref",
    "call_refs",
]
