"""Where each Sales X-Ray Play tester stands (owner, 13 Nov 2026).

Testers could not install: Play says "Item not found" unless the Google account that opens
the opt-in link is in the closed test's Google Group and taps "Become a tester". Our own
list is the one source of truth (never a guess at Google Group membership at sign-in):

    applied -> approved -> in_group -> emailed -> installed -> active      (or declined)

- applied: the person signed in at /testers with their Google account and gave their phone,
  role and business. The 47 group members when the list began are "listed" instead, and are
  in the group already.
- approved / declined: the team, in Admin -> Testers.
- in_group: the team added the account to salesxray-testers@ (and pressed "Added").
- emailed: the branded welcome email was sent (the app's mail, through the outbox).
- installed: the account's first Sales X-Ray app session (user agent SalesXrayApp/<version>).
- active: an app session in the last 7 days. Play needs 12 testers opted in for 14 days.

Installs, activity, versions and bug reports are read from sessions and bug reports when the
list is read, never stored as tester state. A listed tester's starting facts (what production
showed when the list began) stand in where this environment has no sessions of its own.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports.models import BugReport
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import Job, JobStatus, OutboxEvent, OutboxEventStatus
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.testers.models import ROLES, SalesXrayTesterEvent

OPT_IN_URL = "https://play.google.com/apps/testing/com.authorityclosers.salesxray"
PLAY_URL = "https://play.google.com/store/apps/details?id=com.authorityclosers.salesxray"
GROUP_EMAIL = "salesxray-testers@authorityclosers.com"
GROUP_MEMBERS_URL = "https://groups.google.com/a/authorityclosers.com/g/salesxray-testers/members"
ACTIVE_DAYS = 7
PLAY_NEEDS = 12
#: Two clicks on "Send email" this close together send one email.
EMAIL_REPEAT_GUARD = timedelta(minutes=2)

WELCOME_EVENT = "sales_xray.tester.welcome.requested.v1"
WELCOME_JOB = "email.sales_xray_tester_welcome.v1"

APP_AGENT = re.compile(r"\bSalesXrayApp/(\d[0-9A-Za-z.\-]{0,23})")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}")

Stage = Literal["applied", "approved", "in_group", "emailed", "installed", "active", "declined"]
STAGES: tuple[Stage, ...] = (
    "applied",
    "approved",
    "in_group",
    "emailed",
    "installed",
    "active",
    "declined",
)
PublicState = Literal["none", "waiting", "approved", "ready", "declined"]


class TesterRefused(ValueError):
    """A step this tester's history does not allow; its words are shown to the team."""


class TesterNotFound(LookupError):
    pass


def normal_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or EMAIL.fullmatch(email) is None:
        raise ValueError("That is not an email address.")
    return email


def welcome_key(event_id: UUID) -> str:
    return f"sales-xray-tester-welcome:{event_id}"


def first_name(name: str | None) -> str:
    words = (name or "").split()
    return words[0][:60] if words else "there"


@dataclass
class Standing:
    """A tester's rows folded: the newest of each kind of step stands."""

    id: UUID
    email: str
    source: str
    created_at: datetime
    name: str | None = None
    phone_model: str | None = None
    role: str | None = None
    business: str | None = None
    applied_at: datetime | None = None
    listed_at: datetime | None = None
    decision: str | None = None
    decided_at: datetime | None = None
    in_group_at: datetime | None = None
    in_group_via: str | None = None
    emailed_at: datetime | None = None
    emailed_via: str | None = None
    email_event_id: UUID | None = None
    note: str | None = None
    facts: dict[str, Any] | None = None

    @property
    def public_state(self) -> PublicState:
        if self.decision == "declined":
            return "declined"
        if self.in_group_at is not None:
            return "ready"
        if self.decision == "approved" or self.listed_at is not None:
            return "approved"
        return "waiting"


def fold(rows: Sequence[SalesXrayTesterEvent]) -> Standing:
    """Rows of one email, oldest first."""

    if not rows:
        raise TesterNotFound("No tester has that reference.")
    # The tester's reference is their application or listing (an email sent by hand before
    # the list began can be older than either).
    first = next((row for row in rows if row.kind in ("applied", "listed")), rows[0])
    standing = Standing(
        id=first.id, email=first.email, source=first.kind, created_at=first.created_at
    )
    for row in rows:
        for field in ("name", "phone_model", "role", "business", "note"):
            value = getattr(row, field)
            if value:
                setattr(standing, field, value)
        if row.kind == "applied":
            standing.applied_at = standing.applied_at or row.created_at
        elif row.kind == "listed":
            standing.listed_at = standing.listed_at or row.created_at
            if row.facts:
                standing.facts = dict(row.facts)
        elif row.kind in ("approved", "declined"):
            standing.decision, standing.decided_at = row.kind, row.created_at
        elif row.kind == "added_to_group":
            if standing.in_group_at is None:
                standing.in_group_at, standing.in_group_via = row.created_at, row.via
        elif row.kind == "emailed":
            standing.emailed_at, standing.emailed_via = row.created_at, row.via
            standing.email_event_id = row.id if row.via == "app" else None
    return standing


async def _rows_for(db: AsyncSession, email: str) -> list[SalesXrayTesterEvent]:
    return list(
        (
            await db.scalars(
                select(SalesXrayTesterEvent)
                .where(SalesXrayTesterEvent.email == email)
                .order_by(SalesXrayTesterEvent.created_at, SalesXrayTesterEvent.id)
            )
        ).all()
    )


async def _email_of(db: AsyncSession, tester_id: UUID) -> str:
    email: str | None = await db.scalar(
        select(SalesXrayTesterEvent.email).where(SalesXrayTesterEvent.id == tester_id)
    )
    if email is None:
        raise TesterNotFound("No tester has that reference.")
    return email


async def standing_for_email(db: AsyncSession, email: str) -> Standing | None:
    rows = await _rows_for(db, email)
    return fold(rows) if rows else None


async def standing_for(db: AsyncSession, tester_id: UUID) -> Standing:
    return fold(await _rows_for(db, await _email_of(db, tester_id)))


def _clean(value: str | None, maximum: int) -> str | None:
    text = " ".join((value or "").split())
    return text[:maximum] or None


# ---------- The person, at /testers ----------


async def apply(
    db: AsyncSession,
    *,
    person_id: UUID,
    email: str,
    name: str | None,
    phone_model: str,
    role: str,
    business: str,
    now: datetime,
) -> Standing:
    """Joins the waitlist once; applying again (or as a listed tester) changes nothing more."""

    email = normal_email(email)
    if role not in ROLES:
        raise TesterRefused("Choose your role from the list.")
    phone, work = _clean(phone_model, 80), _clean(business, 120)
    if phone is None or len(phone) < 2:
        raise TesterRefused("Say which Android phone you use.")
    if work is None or len(work) < 2:
        raise TesterRefused("Say what your business is.")
    rows = await _rows_for(db, email)
    if any(row.kind == "applied" for row in rows):
        return fold(rows)
    row = SalesXrayTesterEvent(
        id=uuid4(),
        email=email,
        kind="applied",
        person_id=person_id,
        actor_person_id=person_id,
        name=_clean(name, 120),
        phone_model=phone,
        role=role,
        business=work,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return fold([*rows, row])


# ---------- The team, in Admin -> Testers ----------


async def decide(
    db: AsyncSession,
    tester_id: UUID,
    *,
    decision: Literal["approve", "decline"],
    actor_person_id: UUID,
    actor_email: str | None,
    note: str | None,
    now: datetime,
) -> Standing:
    rows = await _rows_for(db, await _email_of(db, tester_id))
    standing = fold(rows)
    if actor_email and actor_email.strip().lower() == standing.email:
        raise TesterRefused("Someone else decides for you.")
    kind = "approved" if decision == "approve" else "declined"
    if standing.decision == kind:
        return standing
    row = SalesXrayTesterEvent(
        id=uuid4(),
        email=standing.email,
        kind=kind,
        actor_person_id=actor_person_id,
        note=_clean(note, 500),
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return fold([*rows, row])


async def mark_added(
    db: AsyncSession,
    tester_id: UUID,
    *,
    actor_person_id: UUID,
    send_email: bool,
    now: datetime,
) -> Standing:
    """The team added the account to the Google Group; the welcome email can follow at once."""

    rows = await _rows_for(db, await _email_of(db, tester_id))
    standing = fold(rows)
    if standing.decision == "declined":
        raise TesterRefused("They were declined. Approve them first.")
    if standing.decision != "approved" and standing.listed_at is None:
        raise TesterRefused("Approve them first.")
    if standing.in_group_at is None:
        row = SalesXrayTesterEvent(
            id=uuid4(),
            email=standing.email,
            kind="added_to_group",
            via="admin",
            actor_person_id=actor_person_id,
            created_at=now,
        )
        db.add(row)
        await db.flush()
        rows.append(row)
    if send_email:
        return await request_welcome(db, tester_id, actor_person_id=actor_person_id, now=now)
    return fold(rows)


async def request_welcome(
    db: AsyncSession, tester_id: UUID, *, actor_person_id: UUID, now: datetime
) -> Standing:
    """Queues the branded welcome email (outbox), only for a tester in the Google Group."""

    rows = await _rows_for(db, await _email_of(db, tester_id))
    standing = fold(rows)
    if standing.decision == "declined":
        raise TesterRefused("They were declined. Approve them first.")
    if standing.in_group_at is None:
        raise TesterRefused(
            "Add them to the Google Group first: Play's link works only for its members."
        )
    if (
        standing.emailed_via == "app"
        and standing.emailed_at is not None
        and now - standing.emailed_at < EMAIL_REPEAT_GUARD
    ):
        return standing
    row = SalesXrayTesterEvent(
        id=uuid4(),
        email=standing.email,
        kind="emailed",
        via="app",
        actor_person_id=actor_person_id,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    await OutboxRepository(db).enqueue(
        EventEnvelope(
            name=WELCOME_EVENT,
            category=EventCategory.OPERATIONAL,
            aggregate_type="sales_xray_tester",
            aggregate_id=row.id,
            tenant_id=None,
            payload={"tester_event_id": str(row.id)},
            occurred_at=now,
        ),
        dedupe_key=welcome_key(row.id),
    )
    return fold([*rows, row])


# ---------- Reading the list ----------


@dataclass
class Activity:
    has_account: bool = False
    app_sessions: int = 0
    first_app_at: datetime | None = None
    last_app_at: datetime | None = None
    app_version: str | None = None
    web_last_at: datetime | None = None
    bugs: int = 0


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _earliest(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _latest(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def with_facts(live: Activity, facts: dict[str, Any] | None) -> Activity:
    """This environment's own sessions, with a listed tester's starting facts beside them."""

    if not facts:
        return live
    count = facts.get("app_sessions")
    bugs = facts.get("bugs")
    return Activity(
        has_account=live.has_account or bool(facts.get("has_account")),
        app_sessions=max(live.app_sessions, count if isinstance(count, int) else 0),
        first_app_at=_earliest(live.first_app_at, _when(facts.get("first_app_at"))),
        last_app_at=_latest(live.last_app_at, _when(facts.get("last_app_at"))),
        app_version=live.app_version
        or (str(facts["app_version"])[:24] if facts.get("app_version") else None),
        web_last_at=_latest(live.web_last_at, _when(facts.get("web_last_at"))),
        bugs=max(live.bugs, bugs if isinstance(bugs, int) else 0),
    )


async def activity_for(db: AsyncSession, emails: Iterable[str]) -> dict[str, Activity]:
    """Each email's account, app and web sessions and bug reports (counts and times only)."""

    wanted = sorted(set(emails))
    found: dict[str, Activity] = {email: Activity() for email in wanted}
    if not wanted:
        return found
    people = (
        await db.execute(
            select(Person.id, func.lower(Person.email)).where(func.lower(Person.email).in_(wanted))
        )
    ).all()
    owner = {person_id: email for person_id, email in people}
    for email in owner.values():
        found[email].has_account = True
    if not owner:
        return found
    newest_agent: dict[str, tuple[datetime, str]] = {}
    for person_id, created, seen, agent in (
        await db.execute(
            select(
                IdentitySession.person_id,
                IdentitySession.created_at,
                IdentitySession.last_seen_at,
                IdentitySession.user_agent,
            ).where(IdentitySession.person_id.in_(owner))
        )
    ).all():
        item = found[owner[person_id]]
        created = _when(created)
        last = _latest(created, _when(seen))
        version = APP_AGENT.search(agent or "")
        if version is None:
            item.web_last_at = _latest(item.web_last_at, last)
            continue
        item.app_sessions += 1
        item.first_app_at = _earliest(item.first_app_at, created)
        item.last_app_at = _latest(item.last_app_at, last)
        email = owner[person_id]
        if created is not None and (email not in newest_agent or created > newest_agent[email][0]):
            newest_agent[email] = (created, version.group(1))
    for email, (_, version_text) in newest_agent.items():
        found[email].app_version = version_text
    for person_id, count in (
        await db.execute(
            select(BugReport.person_id, func.count())
            .where(BugReport.person_id.in_(owner))
            .group_by(BugReport.person_id)
        )
    ).all():
        found[owner[person_id]].bugs = int(count)
    return found


async def email_statuses(db: AsyncSession, event_ids: Iterable[UUID]) -> dict[UUID, str]:
    """queued, sent or failed for each app welcome email, from the outbox and its job."""

    keys = {welcome_key(event_id): event_id for event_id in event_ids}
    if not keys:
        return {}
    events = (
        await db.execute(
            select(OutboxEvent.id, OutboxEvent.dedupe_key, OutboxEvent.status).where(
                OutboxEvent.dedupe_key.in_(keys)
            )
        )
    ).all()
    statuses = {keys[key]: "queued" for _, key, _ in events}
    by_job = {f"outbox:{outbox_id}": keys[key] for outbox_id, key, _ in events}
    for _, key, status in events:
        if status == OutboxEventStatus.DEAD_LETTER.value:
            statuses[keys[key]] = "failed"
    if by_job:
        for job_key, status in (
            await db.execute(select(Job.dedupe_key, Job.status).where(Job.dedupe_key.in_(by_job)))
        ).all():
            if status == JobStatus.SUCCEEDED.value:
                statuses[by_job[job_key]] = "sent"
            elif status == JobStatus.DEAD_LETTER.value:
                statuses[by_job[job_key]] = "failed"
    return {event_id: statuses.get(event_id, "queued") for event_id in keys.values()}


def stage_of(
    standing: Standing, activity: Activity, email_status: str | None, now: datetime
) -> Stage:
    if standing.decision == "declined":
        return "declined"
    if activity.last_app_at is not None and activity.last_app_at >= now - timedelta(
        days=ACTIVE_DAYS
    ):
        return "active"
    if activity.first_app_at is not None:
        return "installed"
    if standing.emailed_at is not None and email_status != "failed":
        return "emailed"
    if standing.in_group_at is not None:
        return "in_group"
    if standing.decision == "approved" or standing.listed_at is not None:
        return "approved"
    return "applied"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


async def listing(db: AsyncSession, *, now: datetime) -> dict[str, Any]:
    """Every tester with their stage, newest applications waiting first, then the furthest."""

    rows = (
        await db.scalars(
            select(SalesXrayTesterEvent).order_by(
                SalesXrayTesterEvent.email,
                SalesXrayTesterEvent.created_at,
                SalesXrayTesterEvent.id,
            )
        )
    ).all()
    grouped: dict[str, list[SalesXrayTesterEvent]] = {}
    for row in rows:
        grouped.setdefault(row.email, []).append(row)
    standings = [fold(items) for items in grouped.values()]
    activity = await activity_for(db, grouped)
    statuses = await email_statuses(
        db, [s.email_event_id for s in standings if s.email_event_id is not None]
    )
    items: list[dict[str, Any]] = []
    for standing in standings:
        act = with_facts(activity[standing.email], standing.facts)
        status = (
            statuses.get(standing.email_event_id)
            if standing.email_event_id is not None
            else ("sent" if standing.emailed_via == "gmail" else None)
        )
        items.append(
            {
                "id": str(standing.id),
                "email": standing.email,
                "name": standing.name,
                "source": standing.source,
                "stage": stage_of(standing, act, status, now),
                "phone_model": standing.phone_model,
                "role": standing.role,
                "business": standing.business,
                "applied_at": _iso(standing.applied_at),
                "listed_at": _iso(standing.listed_at),
                "decision": standing.decision,
                "decided_at": _iso(standing.decided_at),
                "in_group_at": _iso(standing.in_group_at),
                "in_group_via": standing.in_group_via,
                "emailed_at": _iso(standing.emailed_at),
                "emailed_via": standing.emailed_via,
                "email_status": status,
                "has_account": act.has_account,
                "app_sessions": act.app_sessions,
                "first_app_at": _iso(act.first_app_at),
                "last_app_at": _iso(act.last_app_at),
                "app_version": act.app_version,
                "web_last_at": _iso(act.web_last_at),
                "bugs": act.bugs,
                "note": standing.note,
            }
        )
    rank = {stage: index for index, stage in enumerate(STAGES)}
    items.sort(
        key=lambda item: (
            item["stage"] != "applied",
            item["stage"] == "declined",
            -rank[item["stage"]] if item["stage"] != "applied" else 0,
            item["applied_at"] or "" if item["stage"] == "applied" else item["email"],
        )
    )
    counts = {stage: 0 for stage in STAGES}
    for item in items:
        counts[item["stage"]] += 1
    return {
        "items": items,
        "counts": counts,
        "feedback": sum(1 for item in items if item["bugs"]),
        "active": counts["active"],
        "play_needs": PLAY_NEEDS,
        "active_days": ACTIVE_DAYS,
        "group": {"email": GROUP_EMAIL, "members_url": GROUP_MEMBERS_URL},
        "links": {"opt_in": OPT_IN_URL, "play": PLAY_URL},
        "read_at": _iso(now),
    }


CSV_COLUMNS = (
    "email",
    "name",
    "stage",
    "source",
    "phone_model",
    "role",
    "business",
    "applied_at",
    "decision",
    "decided_at",
    "in_group_at",
    "emailed_at",
    "email_status",
    "has_account",
    "app_sessions",
    "first_app_at",
    "last_app_at",
    "app_version",
    "web_last_at",
    "bugs",
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    # A spreadsheet never runs a cell as a formula.
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(items: Sequence[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for item in items:
        writer.writerow([_cell(item.get(column)) for column in CSV_COLUMNS])
    return output.getvalue()


__all__ = [
    "ACTIVE_DAYS",
    "CSV_COLUMNS",
    "GROUP_EMAIL",
    "GROUP_MEMBERS_URL",
    "OPT_IN_URL",
    "PLAY_NEEDS",
    "PLAY_URL",
    "STAGES",
    "WELCOME_EVENT",
    "WELCOME_JOB",
    "Activity",
    "Standing",
    "TesterNotFound",
    "TesterRefused",
    "activity_for",
    "apply",
    "decide",
    "email_statuses",
    "first_name",
    "fold",
    "listing",
    "mark_added",
    "normal_email",
    "request_welcome",
    "stage_of",
    "standing_for",
    "standing_for_email",
    "to_csv",
    "welcome_key",
    "with_facts",
]
