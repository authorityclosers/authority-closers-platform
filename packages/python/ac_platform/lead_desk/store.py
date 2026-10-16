"""Lead Desk reads and writes for one workspace and one signed-in person.

Who sees what: a seller sees the leads they own (and ones they added); an
owner or admin of the workspace sees every lead, the team and the sources.
Every change to a lead adds a history event; nothing is deleted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import Person
from ac_platform.lead_desk import allocation
from ac_platform.lead_desk.capture import (
    CaptureError,
    bounded_payload,
    display_name,
    extract,
    flatten,
)
from ac_platform.lead_desk.contracts import (
    Counts,
    Desk,
    Disposition,
    FieldValue,
    LeadDetail,
    LeadEventView,
    LeadPage,
    LeadRow,
    Me,
    NewLead,
    Numbers,
    Reassign,
    RepOption,
    RepRules,
    RepView,
    SettingsCommand,
    SettingsView,
    Team,
)
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent, LeadRep
from ac_platform.lead_desk.vocabulary import (
    CLOSED_STAGES,
    NEEDS_FOLLOW_UP,
    OPEN_STAGES,
    REASON_LABELS,
    SOURCE_LABELS,
    STAGE_LABELS,
    retry_after,
    stage_after_connected,
    stage_after_not_connected,
)
from ac_platform.tenancy.models import Membership

MANAGERS = frozenset({"owner", "admin"})
SELLER_ROLES = ("owner", "admin", "member")
QUEUE_LIMIT = 30
PAGE_SIZE = 50
DEFAULT_MAX_OPEN = 50
DEFAULT_SETTINGS: dict[str, Any] = {
    "auto_reassign": False,
    "reassign_minutes": 10,
    "default_country": "91",
}
IST = ZoneInfo("Asia/Kolkata")


class DeskError(Exception):
    """A refusal the person can act on; the message is shown as is."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class Viewer:
    person_id: UUID
    tenant_id: UUID
    role: str
    name: str

    @property
    def can_manage(self) -> bool:
        return self.role in MANAGERS


@dataclass(frozen=True, slots=True)
class _Rep:
    state: allocation.RepState
    role: str
    row: LeadRep | None


def utcnow() -> datetime:
    return datetime.now(UTC)


def person_name(person: Person | None) -> str:
    if person is None:
        return "A teammate"
    if person.display_name and person.display_name.strip():
        return person.display_name.strip()
    if person.first_name and person.first_name.strip():
        return person.first_name.strip()
    if person.email:
        return person.email.split("@", 1)[0]
    return "A teammate"


def content_ref(record: Mapping[str, Any]) -> str:
    """A stable id for a record that has none, so re-imports don't duplicate it."""
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    return "h:" + hashlib.sha256(encoded.encode()).hexdigest()[:40]


def _strings(values: Any) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if isinstance(item, str) and item.strip())


class LeadDesk:
    def __init__(
        self,
        database: AsyncSession,
        viewer: Viewer,
        *,
        call_mode: Literal["simulated", "phone"] = "simulated",
        sandbox: bool = False,
        now: datetime | None = None,
    ) -> None:
        self.db = database
        self.viewer = viewer
        self.tenant_id = viewer.tenant_id
        self.call_mode = call_mode
        self.sandbox = sandbox
        self.now = now or utcnow()
        self._sequence = 0

    # ----- shared reads --------------------------------------------------------

    def _day_start(self) -> datetime:
        local = self.now.astimezone(IST)
        return datetime.combine(local.date(), time.min, tzinfo=IST).astimezone(UTC)

    async def settings(self) -> tuple[int, dict[str, Any]]:
        row = await self.db.get(LeadDeskSettings, self.tenant_id)
        if row is None:
            return 0, dict(DEFAULT_SETTINGS)
        return row.revision, {**DEFAULT_SETTINGS, **row.config}

    async def _names(self, person_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = {person_id for person_id in person_ids if person_id is not None}
        if not ids:
            return {}
        people = (await self.db.scalars(select(Person).where(Person.id.in_(ids)))).all()
        return {person.id: person_name(person) for person in people}

    async def _reps(self) -> list[_Rep]:
        members = (
            await self.db.execute(
                select(Membership.person_id, Membership.role, Person)
                .join(Person, Person.id == Membership.person_id)
                .where(
                    Membership.tenant_id == self.tenant_id,
                    Membership.status == "active",
                    Membership.ended_at.is_(None),
                    Membership.role.in_(SELLER_ROLES),
                )
            )
        ).all()
        rows = {
            row.person_id: row
            for row in (
                await self.db.scalars(select(LeadRep).where(LeadRep.tenant_id == self.tenant_id))
            ).all()
        }
        loads = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.count())
                    .where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.owner_person_id.is_not(None),
                        Lead.stage.in_(OPEN_STAGES),
                    )
                    .group_by(Lead.owner_person_id)
                )
            ).all()
        )
        latest = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.max(Lead.assigned_at))
                    .where(Lead.tenant_id == self.tenant_id, Lead.owner_person_id.is_not(None))
                    .group_by(Lead.owner_person_id)
                )
            ).all()
        )
        reps: list[_Rep] = []
        for person_id, role, person in members:
            row = rows.get(person_id)
            reps.append(
                _Rep(
                    allocation.RepState(
                        person_id=person_id,
                        name=person_name(person),
                        available=row.available if row else True,
                        max_open=row.max_open if row else DEFAULT_MAX_OPEN,
                        open_leads=int(loads.get(person_id, 0)),
                        languages=_strings(row.languages) if row else (),
                        areas=_strings(row.areas) if row else (),
                        interests=_strings(row.interests) if row else (),
                        last_assigned_at=latest.get(person_id),
                    ),
                    role,
                    row,
                )
            )
        reps.sort(key=lambda rep: rep.state.name.lower())
        return reps

    def _event(
        self,
        lead: Lead,
        kind: str,
        data: dict[str, Any],
        *,
        actor: UUID | None,
        command_id: UUID | None = None,
    ) -> LeadEvent:
        event = LeadEvent(
            id=uuid4(),
            tenant_id=self.tenant_id,
            lead_id=lead.id,
            kind=kind,
            actor_person_id=actor,
            command_id=command_id,
            data=json.loads(json.dumps(data, default=str)),
            # One request can add several events; a microsecond apart keeps their order.
            created_at=self.now + timedelta(microseconds=self._sequence),
        )
        self._sequence += 1
        self.db.add(event)
        return event

    def _visible(self) -> Any:
        if self.viewer.can_manage:
            return Lead.tenant_id == self.tenant_id
        return and_(
            Lead.tenant_id == self.tenant_id,
            or_(
                Lead.owner_person_id == self.viewer.person_id,
                and_(
                    Lead.owner_person_id.is_(None),
                    Lead.created_by_person_id == self.viewer.person_id,
                ),
            ),
        )

    async def _lead(self, lead_id: UUID, *, lock: bool = False) -> Lead:
        query = select(Lead).where(Lead.id == lead_id, self._visible())
        if lock:
            query = query.with_for_update()
        lead = await self.db.scalar(query)
        if lead is None:
            raise DeskError(404, "This lead isn't on your desk.")
        return lead

    async def _command_seen(self, command_id: UUID) -> LeadEvent | None:
        return await self.db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == self.tenant_id, LeadEvent.command_id == command_id
            )
        )

    # ----- rows ------------------------------------------------------------------

    def _why(self, lead: Lead, day_end: datetime) -> tuple[str, str]:
        source = lead.source_label or SOURCE_LABELS.get(lead.source, lead.source)
        if lead.stage in CLOSED_STAGES:
            return "closed", STAGE_LABELS[lead.stage]
        if lead.owner_person_id is None:
            return "waiting", "Waiting for an owner"
        due = lead.next_action_at
        if lead.stage == "new" and due is None:
            return "new", "New lead"
        if due is not None and due <= self.now:
            if lead.repeats and lead.last_result is None:
                return "due", f"Asked again · {source}"
            if lead.stage == "not_connected":
                label = REASON_LABELS.get(lead.last_result or "", "Not connected")
                tries = f"{lead.attempts} tr{'y' if lead.attempts == 1 else 'ies'}"
                return "retry", f"Try again · {label.lower()} · {tries}"
            if lead.stage == "new":
                return "due", f"Asked again · {source}"
            return "due", f"{STAGE_LABELS[lead.stage]} due"
        if due is not None and due <= day_end:
            return "later", "Try again" if lead.stage == "not_connected" else "Follow-up"
        return "open", STAGE_LABELS[lead.stage]

    def _row(self, lead: Lead, names: Mapping[UUID, str], day_end: datetime) -> LeadRow:
        kind, why = self._why(lead, day_end)
        result_label = (
            STAGE_LABELS.get(lead.last_result) or REASON_LABELS.get(lead.last_result)
            if lead.last_result
            else None
        )
        return LeadRow(
            lead_id=lead.id,
            revision=lead.revision,
            name=lead.name,
            company=lead.company,
            city=lead.city,
            language=lead.language,
            interest=lead.interest,
            phone_last4=lead.phone[-4:] if lead.phone else None,
            stage=lead.stage,
            stage_label=STAGE_LABELS[lead.stage],
            source=lead.source,
            source_label=lead.source_label or SOURCE_LABELS.get(lead.source, lead.source),
            owner_person_id=lead.owner_person_id,
            owner_name=names.get(lead.owner_person_id) if lead.owner_person_id else None,
            why=why,
            why_kind=kind,  # type: ignore[arg-type]
            next_action_at=lead.next_action_at,
            created_at=lead.created_at,
            attempts=lead.attempts,
            calls=lead.calls,
            last_result=lead.last_result,
            last_result_label=result_label,
            test_data=lead.test_data,
        )

    async def _rows(self, leads: Sequence[Lead]) -> tuple[LeadRow, ...]:
        names = await self._names(lead.owner_person_id for lead in leads)
        day_end = self._day_start() + timedelta(days=1)
        return tuple(self._row(lead, names, day_end) for lead in leads)

    # ----- the desk --------------------------------------------------------------

    async def desk(self) -> Desk:
        me = self.viewer.person_id
        day_start = self._day_start()
        day_end = day_start + timedelta(days=1)
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
        )
        due = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.next_action_at <= self.now)
                .order_by(Lead.next_action_at, Lead.created_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        fresh = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.stage == "new", Lead.next_action_at.is_(None))
                .order_by(Lead.created_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        later = (
            await self.db.scalars(
                select(Lead)
                .where(mine, Lead.next_action_at > self.now, Lead.next_action_at < day_end)
                .order_by(Lead.next_action_at)
                .limit(QUEUE_LIMIT)
            )
        ).all()
        queue = [*due, *fresh, *later][:QUEUE_LIMIT]

        counts_row = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count().filter(Lead.stage == "new", Lead.next_action_at.is_(None)),
                    func.count().filter(
                        Lead.stage.in_(NEEDS_FOLLOW_UP), Lead.next_action_at <= self.now
                    ),
                    func.count().filter(Lead.stage == "not_connected"),
                    func.count().filter(
                        Lead.next_action_at > self.now, Lead.next_action_at < day_end
                    ),
                ).where(mine)
            )
        ).one()
        unassigned = None
        if self.viewer.can_manage:
            unassigned = int(
                await self.db.scalar(
                    select(func.count()).where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.owner_person_id.is_(None),
                        Lead.stage.in_(OPEN_STAGES),
                    )
                )
                or 0
            )

        today = (
            await self.db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.actor_person_id == me,
                    LeadEvent.created_at >= day_start,
                    LeadEvent.kind.in_(("result", "call")),
                )
                .limit(5000)
            )
        ).all()
        results = [event for event in today if event.kind == "result"]
        talk = sum(
            int(event.data.get("duration_seconds") or 0) for event in today if event.kind == "call"
        )
        new_assigned = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id == me,
                    Lead.assigned_at >= day_start,
                )
            )
            or 0
        )
        return Desk(
            me=Me(
                person_id=me,
                name=self.viewer.name,
                role=self.viewer.role,
                can_manage=self.viewer.can_manage,
            ),
            numbers=Numbers(
                calls=len(results),
                connected=sum(1 for event in results if event.data.get("connected")),
                talk_seconds=talk,
                follow_ups_done=sum(1 for event in results if event.data.get("was_due")),
                new_assigned=new_assigned,
            ),
            counts=Counts(
                open=int(counts_row[0]),
                new=int(counts_row[1]),
                follow_up_due=int(counts_row[2]),
                not_connected=int(counts_row[3]),
                later_today=int(counts_row[4]),
                unassigned=unassigned,
            ),
            queue=await self._rows(queue),
            call_mode=self.call_mode,
            sandbox=self.sandbox,
            generated_at=self.now,
        )

    async def next_lead(self, skip: UUID | None = None) -> LeadDetail | None:
        """'Start calling': the one lead to call now (follow-ups due, then new leads)."""
        me = self.viewer.person_id
        mine = and_(
            Lead.tenant_id == self.tenant_id,
            Lead.owner_person_id == me,
            Lead.stage.in_(OPEN_STAGES),
        )
        if skip is not None:
            mine = and_(mine, Lead.id != skip)
        lead = await self.db.scalar(
            select(Lead)
            .where(mine, Lead.next_action_at <= self.now)
            .order_by(Lead.next_action_at, Lead.created_at)
            .limit(1)
        ) or await self.db.scalar(
            select(Lead)
            .where(mine, Lead.stage == "new", Lead.next_action_at.is_(None))
            .order_by(Lead.created_at)
            .limit(1)
        )
        return None if lead is None else await self.detail(lead.id)

    async def leads(
        self,
        *,
        scope: Literal["mine", "team", "unassigned"],
        stage: str | None,
        search: str | None,
        offset: int,
    ) -> LeadPage:
        if scope != "mine" and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins see the whole team's leads.")
        where: list[Any] = [self._visible()]
        if scope == "mine":
            where.append(Lead.owner_person_id == self.viewer.person_id)
        elif scope == "unassigned":
            where.append(Lead.owner_person_id.is_(None))
        if stage == "open":
            where.append(Lead.stage.in_(OPEN_STAGES))
        elif stage is not None:
            where.append(Lead.stage == stage)
        if search:
            needle = f"%{search.strip()[:80]}%"
            digits = "".join(ch for ch in search if ch.isdigit())
            terms = [Lead.name.ilike(needle), Lead.company.ilike(needle), Lead.city.ilike(needle)]
            if len(digits) >= 4:
                terms.append(Lead.phone.like(f"%{digits}%"))
            where.append(or_(*terms))
        total = int(await self.db.scalar(select(func.count()).where(*where)) or 0)
        order = (
            (func.coalesce(Lead.next_action_at, Lead.created_at), Lead.created_at)
            if stage == "open" or stage in OPEN_STAGES
            else (Lead.updated_at.desc(),)
        )
        leads = (
            await self.db.scalars(
                select(Lead).where(*where).order_by(*order).offset(offset).limit(PAGE_SIZE)
            )
        ).all()
        rows = await self._rows(leads)
        return LeadPage(
            leads=rows,
            total=total,
            next_offset=offset + PAGE_SIZE if offset + PAGE_SIZE < total else None,
        )

    async def detail(self, lead_id: UUID) -> LeadDetail:
        lead = await self._lead(lead_id)
        events = (
            await self.db.scalars(
                select(LeadEvent)
                .where(LeadEvent.tenant_id == self.tenant_id, LeadEvent.lead_id == lead.id)
                .order_by(LeadEvent.created_at.desc(), LeadEvent.id)
                .limit(100)
            )
        ).all()
        people: set[UUID | None] = {lead.owner_person_id}
        for event in events:
            people.add(event.actor_person_id)
            for key in ("to", "from"):
                value = event.data.get(key)
                if isinstance(value, str):
                    try:
                        people.add(UUID(value))
                    except ValueError:
                        pass
        names = await self._names(people)
        day_end = self._day_start() + timedelta(days=1)
        can_edit = self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id
        reps: tuple[RepOption, ...] = ()
        if self.viewer.can_manage:
            reps = tuple(
                RepOption(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    open_leads=rep.state.open_leads,
                    available=rep.state.available,
                )
                for rep in await self._reps()
            )
        fields = tuple(
            FieldValue(label=label, value=value)
            for label, value in (
                ("Phone", lead.phone),
                ("Email", lead.email),
                ("Company", lead.company),
                ("City", lead.city),
                ("Language", lead.language),
                ("Interested in", lead.interest),
            )
            if value
        )
        return LeadDetail(
            lead=self._row(lead, names, day_end),
            phone=lead.phone,
            email=lead.email,
            owner_reason=lead.owner_reason,
            next_action_note=lead.next_action_note,
            fields=fields,
            source_fields=self._source_fields(lead.payload),
            events=tuple(self._event_view(event, names) for event in events),
            can_edit=can_edit,
            can_assign=self.viewer.can_manage,
            reps=reps,
            call_mode=self.call_mode,
        )

    @staticmethod
    def _source_fields(payload: Mapping[str, Any]) -> tuple[FieldValue, ...]:
        values: list[FieldValue] = []
        for name, value in flatten(payload).items():
            if value is None or isinstance(value, (dict, list)) or str(name).startswith("_"):
                continue
            text = " ".join(str(value).split())
            if text:
                label = str(name).replace("_", " ").strip()
                values.append(FieldValue(label=label[:1].upper() + label[1:120], value=text[:500]))
            if len(values) >= 60:
                break
        return tuple(values)

    @staticmethod
    def _uuid(value: Any) -> UUID | None:
        try:
            return UUID(str(value)) if value else None
        except ValueError:
            return None

    def _event_view(self, event: LeadEvent, names: Mapping[UUID, str]) -> LeadEventView:
        data = event.data
        to, previous = self._uuid(data.get("to")), self._uuid(data.get("from"))
        stage = data.get("stage") if isinstance(data.get("stage"), str) else None
        reason = data.get("reason") if isinstance(data.get("reason"), str) else None
        follow = data.get("follow_up_at")
        return LeadEventView(
            kind=event.kind,
            at=event.created_at,
            actor_name=names.get(event.actor_person_id) if event.actor_person_id else None,
            stage=stage,
            stage_label=STAGE_LABELS.get(stage) if stage else None,
            reason=reason,
            reason_label=REASON_LABELS.get(reason) if reason else None,
            connected=data.get("connected") if isinstance(data.get("connected"), bool) else None,
            note=data.get("remark") or data.get("note") or None,
            next_action_at=datetime.fromisoformat(follow) if isinstance(follow, str) else None,
            owner_name=names.get(to) if to else None,
            previous_owner_name=names.get(previous) if previous else None,
            allocation_reason=data.get("reason_text"),
            source_label=data.get("source_label"),
            submission_id=self._uuid(data.get("submission_id")),
            simulated=data.get("simulated") if isinstance(data.get("simulated"), bool) else None,
            duration_seconds=int(data["duration_seconds"])
            if isinstance(data.get("duration_seconds"), (int, float))
            else None,
        )

    # ----- capture ---------------------------------------------------------------

    async def ingest(
        self,
        record: Mapping[str, Any],
        *,
        source: str,
        source_label: str | None = None,
        source_ref: str | None = None,
        mapping: Mapping[str, str] | None = None,
        assign: Literal["rules", "me", "person"] = "rules",
        person_id: UUID | None = None,
        actor: UUID | None = None,
        test_data: bool = False,
        reps: list[_Rep] | None = None,
        command_id: UUID | None = None,
    ) -> tuple[Lead | None, Literal["created", "repeat", "known", "skipped"]]:
        """Store one record as a lead. The same record again (same source id) is "known"
        and changes nothing; another record with the same phone is a "repeat"."""
        _, config = await self.settings()
        found = extract(record, mapping, default_country=config["default_country"])
        if not (found.name or found.phone or found.email):
            return None, "skipped"
        payload = bounded_payload(record)
        if source_ref:
            known = await self.db.scalar(
                select(Lead).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.source == source,
                    Lead.source_ref == source_ref,
                )
            )
            if known is not None:
                return known, "known"
        existing = None
        if found.phone:
            existing = await self.db.scalar(
                select(Lead)
                .where(Lead.tenant_id == self.tenant_id, Lead.phone == found.phone)
                .with_for_update()
            )
        if existing is not None:
            await self._repeat(
                existing, found, payload, source, source_label, actor, reps, command_id
            )
            return existing, "repeat"

        lead = Lead(
            id=uuid4(),
            tenant_id=self.tenant_id,
            revision=1,
            source=source,
            source_ref=source_ref,
            source_label=source_label,
            payload=payload,
            name=display_name(found),
            phone=found.phone,
            email=found.email,
            company=found.company,
            city=found.city,
            language=found.language,
            interest=found.interest,
            stage="new",
            attempts=0,
            calls=0,
            repeats=0,
            test_data=test_data,
            created_by_person_id=actor,
            created_at=self.now,
            updated_at=self.now,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(lead)
                await self.db.flush()
        except IntegrityError:
            # Another delivery of the same lead won the race: count it as a repeat.
            clash = await self.db.scalar(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    or_(
                        and_(Lead.source == source, Lead.source_ref == source_ref)
                        if source_ref
                        else Lead.id.is_(None),
                        Lead.phone == found.phone if found.phone else Lead.id.is_(None),
                    ),
                )
                .with_for_update()
            )
            if clash is None:
                raise
            await self._repeat(clash, found, payload, source, source_label, actor, reps, command_id)
            return clash, "repeat"
        self._event(
            lead,
            "captured",
            {
                "source": source,
                "source_label": source_label or SOURCE_LABELS.get(source, source),
                "used": found.used,
            },
            actor=actor,
            command_id=command_id,
        )
        if assign == "me" and actor is not None:
            await self._set_owner(lead, actor, f"Added by {await self._name(actor)}", "self")
        elif assign == "person" and person_id is not None:
            await self._require_seller(person_id)
            await self._set_owner(
                lead, person_id, f"Chosen by {await self._name(actor)}", "manual", actor=actor
            )
        else:
            await self._allocate(lead, reps=reps)
        return lead, "created"

    async def _name(self, person_id: UUID | None) -> str:
        if person_id is None:
            return "the desk"
        if person_id == self.viewer.person_id:
            return self.viewer.name
        return (await self._names([person_id])).get(person_id, "a teammate")

    async def _repeat(
        self,
        lead: Lead,
        found: Any,
        payload: dict[str, Any],
        source: str,
        source_label: str | None,
        actor: UUID | None,
        reps: list[_Rep] | None,
        command_id: UUID | None = None,
    ) -> None:
        reopened = lead.stage in CLOSED_STAGES
        lead.repeats += 1
        lead.revision += 1
        lead.updated_at = self.now
        for name in ("email", "company", "city", "language", "interest"):
            if getattr(lead, name) is None and getattr(found, name) is not None:
                setattr(lead, name, getattr(found, name))
        if reopened:
            lead.stage = "new"
        if lead.next_action_at is None or lead.next_action_at > self.now:
            lead.next_action_at = self.now
        self._event(
            lead,
            "repeat",
            {
                "source": source,
                "source_label": source_label or SOURCE_LABELS.get(source, source),
                "reopened": reopened,
                "payload": payload,
            },
            actor=actor,
            command_id=command_id,
        )
        if reopened or lead.owner_person_id is None:
            previous = lead.owner_person_id
            await self._allocate(lead, previous_owner=previous, reps=reps)

    async def _require_seller(self, person_id: UUID) -> None:
        member = await self.db.scalar(
            select(Membership.person_id).where(
                Membership.tenant_id == self.tenant_id,
                Membership.person_id == person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Membership.role.in_(SELLER_ROLES),
            )
        )
        if member is None:
            raise DeskError(422, "Choose someone who is an active member of this workspace.")

    async def _set_owner(
        self,
        lead: Lead,
        person_id: UUID | None,
        reason: str,
        rule: str,
        *,
        actor: UUID | None = None,
        kind: str = "assigned",
        command_id: UUID | None = None,
    ) -> None:
        previous = lead.owner_person_id
        lead.owner_person_id = person_id
        lead.assigned_at = self.now if person_id is not None else None
        lead.owner_reason = reason[:300]
        lead.revision += 1 if kind == "reassigned" else 0
        lead.updated_at = self.now
        self._event(
            lead,
            kind,
            {
                "to": str(person_id) if person_id else None,
                "from": str(previous) if previous else None,
                "reason_text": reason[:300],
                "rule": rule,
            },
            actor=actor,
            command_id=command_id,
        )

    async def _allocate(
        self,
        lead: Lead,
        *,
        previous_owner: UUID | None = None,
        exclude: frozenset[UUID] = frozenset(),
        reps: list[_Rep] | None = None,
        kind: str = "assigned",
        actor: UUID | None = None,
        prefix: str = "",
        command_id: UUID | None = None,
    ) -> allocation.Allocation:
        team = reps if reps is not None else await self._reps()
        decision = allocation.allocate(
            allocation.LeadFacts(
                language=lead.language,
                city=lead.city,
                interest=lead.interest,
                previous_owner=previous_owner,
                exclude=exclude,
            ),
            [rep.state for rep in team],
        )
        await self._set_owner(
            lead,
            decision.person_id,
            prefix + decision.reason,
            decision.rule,
            actor=actor,
            kind=kind,
            command_id=command_id,
        )
        if reps is not None and decision.person_id is not None:
            # Keep the caller's load counts current inside a batch import.
            for index, rep in enumerate(reps):
                if rep.state.person_id == decision.person_id:
                    state = rep.state
                    reps[index] = _Rep(
                        allocation.RepState(
                            person_id=state.person_id,
                            name=state.name,
                            available=state.available,
                            max_open=state.max_open,
                            open_leads=state.open_leads + 1,
                            languages=state.languages,
                            areas=state.areas,
                            interests=state.interests,
                            last_assigned_at=self.now,
                        ),
                        rep.role,
                        rep.row,
                    )
        return decision

    async def add(self, command: NewLead) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        if command.assign == "person" and not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins choose who gets a lead.")
        record: dict[str, Any] = {
            key: value
            for key, value in {
                "name": command.name,
                "phone": command.phone,
                "email": command.email,
                "company": command.company,
                "city": command.city,
                "language": command.language,
                "interest": command.interest,
                "referred_by": command.referred_by,
                "note": command.note,
            }.items()
            if value
        }
        if command.phone and extract({"phone": command.phone}).phone is None:
            raise DeskError(422, "Enter a phone number with 10 digits, or with its country code.")
        assign = command.assign if self.viewer.can_manage or command.assign != "rules" else "me"
        try:
            lead, outcome = await self.ingest(
                record,
                source=command.source,
                assign=assign,
                person_id=command.person_id,
                actor=self.viewer.person_id,
                test_data=self.sandbox,
                command_id=command.command_id,
            )
        except CaptureError as error:
            raise DeskError(422, str(error)) from None
        if lead is None:
            raise DeskError(422, "Add a name or a phone number.")
        await self.db.flush()
        if outcome == "repeat" and not (
            self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id
        ):
            # The whole request rolls back: the lead stays with its owner, unchanged.
            raise DeskError(409, "This number is already a lead on a teammate's desk.")
        return await self.detail(lead.id)

    # ----- dispose ---------------------------------------------------------------

    async def dispose(self, lead_id: UUID, command: Disposition) -> LeadDetail:
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            if seen.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            return await self.detail(lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can record this call.")
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed while you were on it. Check it and try again.")
        was_due = lead.next_action_at is not None and lead.next_action_at <= self.now
        previous_stage = lead.stage
        lead.attempts += 1
        follow = command.follow_up_at
        if follow is not None and follow < self.now - timedelta(minutes=5):
            raise DeskError(422, "Pick a follow-up time that's still ahead.")
        if command.connected:
            if command.stage is None:
                raise DeskError(422, "Choose the lead's stage: Follow-up, Interested, Won or Lost.")
            stage = stage_after_connected(command.stage)
            if stage in NEEDS_FOLLOW_UP and follow is None:
                raise DeskError(422, "Pick when to follow up: in one hour, tomorrow or next week.")
            lead.stage = stage
            lead.last_result = stage
            lead.next_action_at = follow if stage in NEEDS_FOLLOW_UP else None
            lead.next_action_note = command.remark if stage in NEEDS_FOLLOW_UP else None
        else:
            if command.reason is None:
                raise DeskError(422, "Choose why the call didn't connect.")
            lead.stage = stage_after_not_connected(lead.stage)
            lead.last_result = command.reason
            gap = retry_after(command.reason, lead.attempts)
            lead.next_action_at = follow or (self.now + gap if gap else None)
            lead.next_action_note = command.remark
        lead.last_contact_at = self.now
        lead.first_contact_at = lead.first_contact_at or self.now
        lead.revision += 1
        lead.updated_at = self.now
        self._event(
            lead,
            "result",
            {
                "connected": command.connected,
                "stage": lead.stage,
                "from_stage": previous_stage,
                "reason": command.reason,
                "follow_up_at": lead.next_action_at.isoformat() if lead.next_action_at else None,
                "remark": command.remark,
                "deal_value": command.deal_value,
                "was_due": was_due,
            },
            actor=self.viewer.person_id,
            command_id=command.command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    async def reassign(self, lead_id: UUID, command: Reassign) -> LeadDetail:
        if not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins move leads between people.")
        seen = await self._command_seen(command.command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if lead.revision != command.expected_revision:
            raise DeskError(409, "This lead changed. Check it and try again.")
        if command.person_id is not None:
            await self._require_seller(command.person_id)
            if command.person_id == lead.owner_person_id:
                return await self.detail(lead.id)
            await self._set_owner(
                lead,
                command.person_id,
                f"Moved by {self.viewer.name}",
                "manual",
                actor=self.viewer.person_id,
                kind="reassigned",
                command_id=command.command_id,
            )
        else:
            exclude = frozenset({lead.owner_person_id}) if lead.owner_person_id else frozenset()
            await self._allocate(
                lead,
                exclude=exclude,
                kind="reassigned",
                actor=self.viewer.person_id,
                command_id=command.command_id,
            )
        await self.db.flush()
        return await self.detail(lead.id)

    async def simulation_target(self, lead_id: UUID) -> tuple[Lead, str | None, str]:
        """The lead, its test-data business (if any) and its owner's name, for a simulated call."""
        lead = await self._lead(lead_id)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can call this lead.")
        if lead.owner_person_id is None:
            raise DeskError(409, "Give this lead an owner first: the call becomes theirs.")
        business = lead.payload.get("business") if isinstance(lead.payload, dict) else None
        return (
            lead,
            business if isinstance(business, str) else None,
            await self._name(lead.owner_person_id),
        )

    async def record_call(
        self,
        lead_id: UUID,
        *,
        command_id: UUID,
        submission_id: UUID | None,
        simulated: bool,
        duration_seconds: int | None,
        sample: str | None = None,
    ) -> LeadDetail:
        seen = await self._command_seen(command_id)
        if seen is not None:
            return await self.detail(seen.lead_id)
        lead = await self._lead(lead_id, lock=True)
        if not (self.viewer.can_manage or lead.owner_person_id == self.viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can call this lead.")
        lead.calls += 1
        lead.revision += 1
        lead.updated_at = self.now
        if submission_id is not None:
            lead.last_submission_id = submission_id
        self._event(
            lead,
            "call",
            {
                "submission_id": str(submission_id) if submission_id else None,
                "simulated": simulated,
                "duration_seconds": duration_seconds,
                "sample": sample,
            },
            actor=self.viewer.person_id,
            command_id=command_id,
        )
        await self.db.flush()
        return await self.detail(lead.id)

    # ----- team, rules and settings ------------------------------------------------

    def _require_manager(self) -> None:
        if not self.viewer.can_manage:
            raise DeskError(403, "Only owners and admins manage the team's lead rules.")

    async def team(self) -> Team:
        self._require_manager()
        reps = await self._reps()
        day_start = self._day_start()
        due = dict(
            (
                await self.db.execute(
                    select(Lead.owner_person_id, func.count())
                    .where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.stage.in_(OPEN_STAGES),
                        Lead.next_action_at <= self.now,
                    )
                    .group_by(Lead.owner_person_id)
                )
            ).all()
        )
        activity = (
            await self.db.execute(
                select(LeadEvent.actor_person_id, LeadEvent.data)
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "result",
                    LeadEvent.created_at >= day_start,
                )
                .limit(20000)
            )
        ).all()
        calls: dict[UUID, int] = {}
        connected: dict[UUID, int] = {}
        for actor, data in activity:
            if actor is None:
                continue
            calls[actor] = calls.get(actor, 0) + 1
            if isinstance(data, dict) and data.get("connected"):
                connected[actor] = connected.get(actor, 0) + 1
        by_stage = dict(
            (
                await self.db.execute(
                    select(Lead.stage, func.count())
                    .where(Lead.tenant_id == self.tenant_id)
                    .group_by(Lead.stage)
                )
            ).all()
        )
        by_source = dict(
            (
                await self.db.execute(
                    select(Lead.source, func.count())
                    .where(Lead.tenant_id == self.tenant_id)
                    .group_by(Lead.source)
                )
            ).all()
        )
        unassigned = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.owner_person_id.is_(None),
                    Lead.stage.in_(OPEN_STAGES),
                )
            )
            or 0
        )
        waiting = int(
            await self.db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == self.tenant_id, Lead.stage == "new", Lead.attempts == 0
                )
            )
            or 0
        )
        revision, config = await self.settings()
        return Team(
            reps=tuple(
                RepView(
                    person_id=rep.state.person_id,
                    name=rep.state.name,
                    role=rep.role,
                    revision=rep.row.revision if rep.row else 0,
                    available=rep.state.available,
                    max_open=rep.state.max_open,
                    languages=rep.state.languages,
                    areas=rep.state.areas,
                    interests=rep.state.interests,
                    open_leads=rep.state.open_leads,
                    due_now=int(due.get(rep.state.person_id, 0)),
                    calls_today=calls.get(rep.state.person_id, 0),
                    connected_today=connected.get(rep.state.person_id, 0),
                )
                for rep in reps
            ),
            settings=SettingsView(
                revision=revision,
                auto_reassign=bool(config["auto_reassign"]),
                reassign_minutes=int(config["reassign_minutes"]),
                default_country=str(config["default_country"]),
            ),
            by_stage={stage: int(count) for stage, count in by_stage.items()},
            by_source={source: int(count) for source, count in by_source.items()},
            unassigned=unassigned,
            waiting_first_call=waiting,
        )

    async def save_rep(self, person_id: UUID, command: RepRules) -> Team:
        self._require_manager()
        await self._require_seller(person_id)
        row = await self.db.get(LeadRep, (self.tenant_id, person_id), with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these rules. Reload and try again.")
        if row is None:
            row = LeadRep(tenant_id=self.tenant_id, person_id=person_id, revision=0)
            self.db.add(row)
        row.revision = current + 1
        row.available = command.available
        row.max_open = command.max_open
        row.languages = list(command.languages)
        row.areas = list(command.areas)
        row.interests = list(command.interests)
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        return await self.team()

    async def save_settings(self, command: SettingsCommand) -> Team:
        self._require_manager()
        row = await self.db.get(LeadDeskSettings, self.tenant_id, with_for_update=True)
        current = row.revision if row else 0
        if current != command.expected_revision:
            raise DeskError(409, "Someone changed these settings. Reload and try again.")
        config = {**DEFAULT_SETTINGS, **(row.config if row else {})}
        config.update(
            auto_reassign=command.auto_reassign, reassign_minutes=command.reassign_minutes
        )
        if row is None:
            row = LeadDeskSettings(tenant_id=self.tenant_id, revision=0, config={})
            self.db.add(row)
        row.revision = current + 1
        row.config = config
        row.updated_by_person_id = self.viewer.person_id
        row.updated_at = self.now
        await self.db.flush()
        return await self.team()

    async def sweep(self, *, limit: int = 200) -> int:
        """Move new leads nobody called in time to someone else (when switched on)."""
        _, config = await self.settings()
        if not config["auto_reassign"]:
            return 0
        minutes = int(config["reassign_minutes"])
        stale = (
            await self.db.scalars(
                select(Lead)
                .where(
                    Lead.tenant_id == self.tenant_id,
                    Lead.stage == "new",
                    Lead.attempts == 0,
                    Lead.owner_person_id.is_not(None),
                    Lead.assigned_at < self.now - timedelta(minutes=minutes),
                    Lead.test_data.is_(False),
                )
                .order_by(Lead.assigned_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not stale:
            return 0
        reps = await self._reps()
        moved = 0
        for lead in stale:
            owner = lead.owner_person_id
            decision = await self._allocate(
                lead,
                exclude=frozenset({owner}) if owner else frozenset(),
                reps=reps,
                kind="reassigned",
                prefix=f"No call in {minutes} minutes. ",
            )
            moved += decision.person_id is not None
        await self.db.flush()
        return moved
