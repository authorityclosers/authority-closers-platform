"""How many lead calls reach analysis (owner, 17 Nov 2026 app review: "upload/analysis
required"; since the Luna switch only about two people upload calls).

Admin reads it to measure the required capture setup and the "your call wasn't checked"
card. Three seller counts and two call counts, nothing else:

- Sellers calling: people with at least one connected lead call the app logged.
- Of them, set up with uploads on: their newest finished capture setup (any phone) had
  uploads on (``capture_setup``). A seller may pause uploads later in Settings, so this is
  the setup's word, not today's switch; "uploaded" below is the evidence.
- Of them, uploaded: at least one of those calls has its recording attached.
- Calls seen (connected lead calls the app logged) and calls uploaded (recording attached).

Counts only: no person, workspace, lead, number or call is named. Sandbox organisations and
test leads are left out, as every other number leaves them out. Read-only and bounded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, select

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai import capture_setup
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.lead_desk.capture_stuck import expects_recording
from ac_platform.lead_desk.models import Lead, LeadEvent

SCHEMA: Final = "ac.sales-xray.upload-funnel/1"
WINDOWS: Final[Mapping[str, timedelta]] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}
LIMIT: Final = 50_000


@dataclass(frozen=True, slots=True)
class CallSeen:
    """A connected lead call the app logged: whose, in which organisation."""

    event_id: str
    tenant_id: UUID
    person_id: UUID


def seen(rows: Iterable[Any]) -> list[CallSeen]:
    """The calls that expect a recording: connected, made by the seller, not a sample."""
    from ac_platform.lead_desk.store import call_out  # the store imports half the app

    calls = []
    for row in rows:
        data = row.data if isinstance(row.data, dict) else {}
        if row.actor_person_id is None or not expects_recording(data) or not call_out(data):
            continue
        calls.append(CallSeen(str(row.id), row.tenant_id, row.actor_person_id))
    return calls


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def tally(
    calls: Sequence[CallSeen],
    uploaded: set[str],
    uploads_on: set[tuple[UUID, UUID]],
) -> dict[str, Any]:
    """The funnel from the calls seen, the call ids with a recording, and the (organisation,
    person) pairs whose newest setup had uploads on."""
    calling = {(call.tenant_id, call.person_id) for call in calls}
    done = [call for call in calls if call.event_id in uploaded]
    uploading = {(call.tenant_id, call.person_id) for call in done}
    on = calling & uploads_on
    return {
        "sellers": {
            "calling": len(calling),
            "uploads_on": len(on),
            "uploaded": len(uploading),
            "uploads_on_share": _share(len(on), len(calling)),
            "uploaded_share": _share(len(uploading), len(calling)),
            # Everyone set up with uploads on, calling in this window or not.
            "uploads_on_all": len(uploads_on),
        },
        "calls": {
            "seen": len(calls),
            "uploaded": len(done),
            "uploaded_share": _share(len(done), len(calls)),
        },
    }


def uploads_on_of(rows: Iterable[Any]) -> set[tuple[UUID, UUID]]:
    """(organisation, person) whose newest finish on any phone had uploads on. Rows are the
    capture-setup events, newest first."""
    grouped: dict[tuple[UUID, str], list[Any]] = {}
    for row in rows:
        grouped.setdefault((row.tenant_id, str(row.resource_id)), []).append(row)
    found: set[tuple[UUID, UUID]] = set()
    for (tenant, person), items in grouped.items():
        setup = capture_setup._fold(items)
        if any(phone.uploads for phone in setup.phones):
            try:
                found.add((tenant, UUID(person)))
            except ValueError:
                continue
    return found


async def read(database: Any, *, now: datetime, window: str) -> dict[str, Any]:
    """The funnel for one window (24h, 7d or 30d), across every real organisation."""
    since = now - WINDOWS[window]
    sandboxes = select(ConversationSandboxOrganisation.tenant_id)
    rows = (
        await database.execute(
            select(
                LeadEvent.id,
                LeadEvent.tenant_id,
                LeadEvent.actor_person_id,
                LeadEvent.data,
            )
            .join(Lead, and_(Lead.id == LeadEvent.lead_id, Lead.tenant_id == LeadEvent.tenant_id))
            .where(
                LeadEvent.kind == "call",
                LeadEvent.created_at >= since,
                LeadEvent.created_at <= now,
                LeadEvent.actor_person_id.is_not(None),
                Lead.test_data.is_(False),
                LeadEvent.tenant_id.not_in(sandboxes),
            )
            .order_by(LeadEvent.created_at.desc())
            .limit(LIMIT + 1)
        )
    ).all()
    truncated = len(rows) > LIMIT
    calls = seen(rows[:LIMIT])
    # A recording joins its call as a later row naming it (``for_call``).
    recorded = (
        await database.scalars(
            select(LeadEvent.data["for_call"].as_string()).where(
                LeadEvent.kind == "call",
                LeadEvent.created_at >= since,
                LeadEvent.data["recording"].as_boolean().is_(True),
                LeadEvent.tenant_id.not_in(sandboxes),
            )
        )
    ).all()
    setups = (
        await database.execute(
            select(
                AuditEvent.id,
                AuditEvent.tenant_id,
                AuditEvent.resource_id,
                AuditEvent.payload,
                AuditEvent.occurred_at,
            )
            .where(
                AuditEvent.resource_type == capture_setup.RESOURCE_TYPE,
                AuditEvent.tenant_id.not_in(sandboxes),
            )
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
            .limit(LIMIT)
        )
    ).all()
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "window": window,
        "since": since.isoformat(),
        **tally(calls, {value for value in recorded if value}, uploads_on_of(setups)),
        "truncated": truncated,
    }


__all__ = ["SCHEMA", "WINDOWS", "CallSeen", "read", "seen", "tally", "uploads_on_of"]
