"""Call capture setup: the steps every seller goes through before working in an
organisation (owner, 30 Oct 2026: "simple clicks and disclosure one by one, so that all
our old as well as new users have to agree").

The steps are the seller's name and phone, what Sales X-Ray captures and why (agreeing is
the standing consent in ``auto_consent``, recorded there), the recordings folder, running
in the background, and uploads on. This module keeps only what the other records don't:

- A phone finished: an audit event naming the phone (this install's id, its model and app
  version) and what it found (folder, background, uploads). Nothing about a call, a lead
  or a number.
- A seller said no at the disclosure: an audit event. The app asks again after
  ``ASK_AGAIN_AFTER``; turning the consent off in Settings, Privacy counts the same way.

Append-only (resource ``sales_xray_capture_setup``, the person's id, in the organisation's
chain): the newest event is the seller's last word; nothing is overwritten. Owners, admins
and managers read everyone's in Team.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository

RESOURCE_TYPE: Final = "sales_xray_capture_setup"
ACTION: Final = "sales_xray.capture_setup.v1"
# A no at the disclosure is asked again the next day (owner: "declining is allowed,
# recorded and asked again").
ASK_AGAIN_AFTER: Final = timedelta(days=1)
# Who sells, so who goes through it: not Viewers or Finance, who change nothing.
REQUIRED_ROLES: Final = frozenset({"owner", "admin", "manager", "member"})
# Enough history for every phone a seller has used; older events are kept, only not read.
_READ_LIMIT: Final = 200

Outcome = Literal["completed", "declined"]
TeamState = Literal[
    "set_up", "phone_pending", "declined", "turned_off", "consent_changed", "not_started"
]


class SetupError(ValueError):
    """A step that can't be recorded, in words the app can show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Phone:
    device: str
    model: str
    family: str
    app_version: str
    at: datetime
    recordings: bool
    background: bool
    uploads: bool

    def view(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "model": self.model,
            "app_version": self.app_version,
            "at": self.at.isoformat(),
            "recordings": self.recordings,
            "background": self.background,
            "uploads": self.uploads,
        }


@dataclass(frozen=True, slots=True)
class Setup:
    """A seller's setup in one organisation: each phone's newest finish, newest first, and
    the newest no (None once a phone finished after it)."""

    phones: tuple[Phone, ...] = field(default_factory=tuple)
    declined_at: datetime | None = None
    key: str | None = None
    event_id: UUID | None = None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _fold(rows: list[Any]) -> Setup:
    """Rows newest first: each phone's newest finish and the last word."""
    phones: dict[str, Phone] = {}
    declined_at: datetime | None = None
    newest: tuple[UUID, str | None] | None = None
    decided = False
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        at = _utc(row.occurred_at)
        if newest is None:
            key = payload.get("idempotency_key")
            newest = (row.id, key if isinstance(key, str) else None)
        outcome = payload.get("outcome")
        if outcome == "declined" and not decided:
            declined_at = at
        if outcome in ("completed", "declined"):
            decided = True
        device = _text(payload.get("device"), 80)
        if outcome == "completed" and device and device not in phones:
            phones[device] = Phone(
                device=device,
                model=_text(payload.get("model"), 80),
                family=_text(payload.get("family"), 20),
                app_version=_text(payload.get("app_version"), 40),
                at=at,
                recordings=payload.get("recordings") is True,
                background=payload.get("background") is True,
                uploads=payload.get("uploads") is True,
            )
    return Setup(
        phones=tuple(phones.values()),
        declined_at=declined_at,
        key=newest[1] if newest else None,
        event_id=newest[0] if newest else None,
    )


def read_setup(connection: Any, *, tenant_id: UUID, person_id: UUID) -> Setup:
    rows = connection.execute(
        select(AuditEvent.id, AuditEvent.payload, AuditEvent.occurred_at)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.resource_type == RESOURCE_TYPE,
            AuditEvent.resource_id == str(person_id),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
        .limit(_READ_LIMIT)
    ).all()
    return _fold(list(rows))


async def setup(database: Any, tenant_id: UUID, person_id: UUID) -> Setup:
    def read(session: Any) -> Setup:
        return read_setup(session.connection(), tenant_id=tenant_id, person_id=person_id)

    result: Setup = await database.run_sync(read)
    return result


async def team(database: Any, tenant_id: UUID, people: list[UUID]) -> dict[UUID, Setup]:
    """Everyone's setup in one read (Team), for the members asked about."""
    wanted = {str(person) for person in people}
    if not wanted:
        return {}
    rows = (
        await database.execute(
            select(
                AuditEvent.id,
                AuditEvent.payload,
                AuditEvent.occurred_at,
                AuditEvent.resource_id,
            )
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.resource_type == RESOURCE_TYPE,
                AuditEvent.resource_id.in_(wanted),
            )
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.sequence_no.desc())
        )
    ).all()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row.resource_id), []).append(row)
    return {person: _fold(grouped.get(str(person), [])[:_READ_LIMIT]) for person in people}


def last_no(found: Setup, consent: str, consent_since: datetime | None) -> datetime | None:
    """When the seller last said no: at the disclosure, or by turning the consent off."""
    turned_off = consent_since if consent == "off" else None
    moments = [moment for moment in (found.declined_at, turned_off) if moment is not None]
    return max(moments) if moments else None


def ask_again_at(no: datetime | None) -> datetime | None:
    return no + ASK_AGAIN_AFTER if no is not None else None


def team_state(found: Setup, consent: str) -> TeamState:
    """One line per seller on Team: set up, or why not."""
    if consent == "on":
        return "set_up" if found.phones else "phone_pending"
    if consent == "off":
        return "turned_off"
    if found.declined_at is not None:
        return "declined"
    # Agreed and finished once, then the words or the upload terms changed.
    return "consent_changed" if found.phones else "not_started"


def phone_payload(phone: dict[str, Any]) -> dict[str, Any]:
    """What a finished phone keeps: its install id, model and app version, and what it
    found. Refused without an install id."""
    device = _text(phone.get("device"), 80)
    if not device:
        raise SetupError(422, "Open Sales X-Ray on your phone to finish setting it up.")
    return {
        "device": device,
        "model": _text(phone.get("model"), 80),
        "family": _text(phone.get("family"), 20),
        "app_version": _text(phone.get("app_version"), 40),
        "recordings": phone.get("recordings") is True,
        "background": phone.get("background") is True,
        "uploads": phone.get("uploads") is True,
    }


async def record(
    database: Any,
    *,
    tenant_id: UUID,
    person_id: UUID,
    session_id: UUID | None,
    outcome: Outcome,
    phone: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    now: datetime,
) -> UUID:
    """Append a finished phone or a no. The same idempotency key again (a double tap)
    appends nothing."""
    if idempotency_key:
        found = await setup(database, tenant_id, person_id)
        if found.event_id is not None and found.key == idempotency_key:
            return found.event_id
    payload: dict[str, Any] = {"outcome": outcome}
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key
    if outcome == "completed":
        payload |= phone_payload(phone or {})
    event = await AuditRepository(database).append(
        tenant_id=tenant_id,
        actor_person_id=person_id,
        session_id=session_id,
        action=ACTION,
        resource_type=RESOURCE_TYPE,
        resource_id=str(person_id),
        payload=payload,
        reason=(
            "Finished call capture setup on a phone."
            if outcome == "completed"
            else "Said no to call capture for now."
        ),
        now=now,
    )
    return UUID(str(event.id))
