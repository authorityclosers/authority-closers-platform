"""Onboard a business in one go: its organisation, its people and its lead sheet, each lead
given to the seller its "called by" column names (approved data change).

Owner, 25 Oct 2026 (the client demo, through the orchestrator): "done-for-you onboarding: we
collect details on WhatsApp, Claude Code sets up her org, adds the sellers as Play testers,
imports her leads and assigns them by called by". In one transaction, through the app's own code:
  1. an account for the owner and each seller, by their Google email, verified, with no consent
     recorded (they accept the terms at their first sign-in, and Sign in with Google joins the
     account its verified email names), and their Sales X-Ray profile: the name and phone from
     the input (+91), so a first call goes straight to review instead of "A few details before
     we review your call" (orchestrator, 25 Oct 2026). A name or phone the person set
     themselves is kept; a number another person's profile has is flagged for review, as the
     app's own profile does;
  2. the organisation, as an operator creates one (``OrganisationService.create``, idempotent by
     command id), the owner as its Owner, the sellers as members; calls are made from their own
     phones (an organisation is never a sandbox here, so the desk never simulates calls);
  3. the sheet, read as the app reads a CSV: every original column kept on the lead, numbers to
     +91, a row repeated exactly in the sheet dropped, a known phone a repeat (one history line)
     and never a second lead, a row with no name, phone or email skipped;
  4. each lead given to the person its "called by" value names: a seller's name or one of the
     variants listed for them, compared without case, spaces or dots, never by a guess; a blank
     or unlisted value goes to the owner, and the map is printed for confirmation first; a
     follow-up date in the sheet (26/10/2026, 27-10-2026, 28 Oct) today or later becomes the
     lead's next call at 10:00 IST, as Set follow-up sets it (a past one stays as written);
  5. one audit event naming the approver and the issue (none when a rerun changes nothing).
Nothing is sent to any lead; the source is "csv", so nothing reaches Meta or Google.

A dry run (the default) makes the whole change in its transaction, prints the map and the
assignment preview, and rolls it back. ``--apply`` commits. A rerun with the same command id is
safe: the organisation, accounts and members are found again, a row seen before is not taken
again, a changed row of a known phone is a repeat on its lead (whose owner stays), and new rows
are added, so the same input with tonight's sheet re-syncs it. ``--read`` reads the result back.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < onboard-organisation.py
input: {"command_id", "organisation", "approver_email", "issue",
        "owner": {"name", "phone"?, "email", "called_by": [variant, ...]?},
        "sellers": [{"name", "phone"?, "email", "called_by": [variant, ...]?}, ...],
        "csv": "<the sheet as CSV text>", "label"?, "called_by_column"?,
        "mapping": {"name": header, "phone": header, "email": header, ...}?,
        "follow_up_column"?, "seller_limit": int | null?, "play_optin_url"?}
Prints counts and the people's own names; a lead's name, number or email never. The Google
emails to add as Play testers are printed in full, once, for the operator.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.sales_xray_profile import normalize_profile_name, validate_e164
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.identity.services import PersonSnapshot
from ac_platform.lead_desk.capture import key, normalise_phone, read_csv, suggest_mapping
from ac_platform.lead_desk.contracts import FollowUp, RepRules
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadRep
from ac_platform.lead_desk.store import LeadDesk, Viewer, content_ref
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

Mode = Literal["dry-run", "apply", "read"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "lead_desk.onboarding_data_change"
LABEL: Final = "Imported sheet"
PLAY_OPTIN: Final = "https://play.google.com/apps/testing/com.authorityclosers.salesxray"
# Headers a sheet names its "called by" column with, after ``capture.key``.
CALLED_BY: Final = (
    "called_by",
    "calledby",
    "called_by_name",
    "caller",
    "caller_name",
    "assigned_to",
    "salesperson",
    "sales_person",
    "telecaller",
)
FOLLOW_UP: Final = (
    "follow_up_date",
    "follow_up",
    "followup_date",
    "followup",
    "next_follow_up",
    "next_follow_up_date",
    "next_call",
    "next_call_date",
    "call_back_date",
    "callback_date",
    "reminder_date",
)
MONTHS: Final = {
    name: number
    for number, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}


class Member(NamedTuple):
    """One of the business's people. A named tuple: the script also loads as a plain file."""

    role: Literal["owner", "member"]
    name: str
    email: str
    phone: str | None
    variants: tuple[str, ...]


def _input(path: str) -> dict[str, Any]:
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def fold(value: str) -> str:
    """A "called by" value compared as people mean it: no case, dots or extra spaces."""
    return " ".join(re.sub(r"[.​]", " ", value).lower().split())


def members(spec: dict[str, Any]) -> list[Member]:
    def one(item: dict[str, Any], role: Literal["owner", "member"]) -> Member:
        name = " ".join(str(item.get("name") or "").split())
        email = str(item.get("email") or "").strip().lower()
        if not name or "@" not in email:
            raise SystemExit(json.dumps({"refused": "person_needs_name_and_email", "role": role}))
        variants = tuple(" ".join(str(v).split()) for v in item.get("called_by") or () if v)
        phone = str(item["phone"]).strip() if item.get("phone") else None
        return Member(role, name, email, phone, variants)

    people = [one(dict(spec["owner"]), "owner")]
    people += [one(dict(item), "member") for item in spec.get("sellers") or ()]
    emails = [person.email for person in people]
    if len(set(emails)) != len(emails):
        raise SystemExit(json.dumps({"refused": "an_email_twice"}))
    return people


def name_map(people: list[Member]) -> dict[str, Member]:
    """Each folded name or listed variant, to its person. A spelling two people share is
    refused: it must be settled by the operator, never guessed."""
    found: dict[str, Member] = {}
    for person in people:
        for spelling in (person.name, *person.variants):
            folded = fold(spelling)
            if not folded:
                continue
            other = found.get(folded)
            if other is not None and other.email != person.email:
                raise SystemExit(
                    json.dumps({"refused": "a_spelling_names_two_people", "spelling": spelling})
                )
            found[folded] = person
    return found


def column(
    headers: tuple[str, ...], given: str | None, names: tuple[str, ...], what: str
) -> str | None:
    if given:
        if given not in headers:
            raise SystemExit(json.dumps({"refused": f"{what}_column_not_in_sheet"}))
        return given
    by_key = {key(header): header for header in headers}
    return next((by_key[name] for name in names if name in by_key), None)


def follow_up_day(text: str, today: date) -> date | None:
    """A follow-up date as Indian sheets write it, day first: 26/10/2026, 27-10-26,
    2026-10-28, 28 Oct, 28 October 2026. A day and month without a year is this year's."""
    words = text.strip().lower().replace(",", " ")
    try:
        found = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", words)
        if found:
            return date(int(found[1]), int(found[2]), int(found[3]))
        found = re.fullmatch(r"(\d{1,2})\s*[/.-]\s*(\d{1,2})(?:\s*[/.-]\s*(\d{2,4}))?", words)
        if found:
            year = int(found[3]) if found[3] else today.year
            return date(year + 2000 if year < 100 else year, int(found[2]), int(found[1]))
        found = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:\s+(\d{4}))?", words)
        if found and found[2] in MONTHS:
            year = int(found[3]) if found[3] else today.year
            return date(year, MONTHS[found[2]], int(found[1]))
    except ValueError:
        return None
    return None


def follow_up_at(day: date, now: datetime) -> datetime | None:
    """The next call on that day: 10:00 IST, or half an hour from now when today's 10:00 has
    passed; None for a day already gone."""
    at = datetime.combine(day, time(10, 0), tzinfo=IST)
    if day < now.astimezone(IST).date():
        return None
    return max(at, now + timedelta(minutes=30))


def rows_of(sheet_rows: tuple[dict[str, str], ...]) -> tuple[list[dict[str, str]], list[int]]:
    """The sheet's rows as leads keep them (every non-empty column, as written), and the row
    numbers dropped as exact repeats of an earlier row."""
    kept: list[dict[str, str]] = []
    dropped: list[int] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for number, raw in enumerate(sheet_rows, start=2):  # row 1 is the header
        record = {
            str(header).strip(): " ".join(str(value).split())
            for header, value in raw.items()
            if header and str(value or "").strip()
        }
        if not record:
            continue
        same = tuple(sorted(record.items()))
        if same in seen:
            dropped.append(number)
            continue
        seen.add(same)
        kept.append(record)
    return kept, dropped


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _account(
    db: AsyncSession, person: Member, command_id: UUID, now: datetime
) -> tuple[UUID, str]:
    """The person's account by their Google email: found, or made verified."""
    found = await _person(db, person.email)
    if found is not None:
        return found.id, "found"
    person_id = uuid5(command_id, f"person:{person.email}")
    await AsyncSqlAlchemyIdentityRepository(db).save_person(
        PersonSnapshot(
            id=person_id, email=person.email, display_name=person.name, email_verified_at=now
        )
    )
    return person_id, "made"


async def _profile(db: AsyncSession, person_id: UUID, person: Member) -> str:
    """The person's Sales X-Ray profile, from the input where it is empty: their name and
    their phone (+91). Never over what they set themselves. What happened, in a word."""
    row = await db.get(Person, person_id)
    if row is None:
        return "no_account"
    said: list[str] = []
    if not (row.display_name or row.first_name or "").strip():
        row.display_name = normalize_profile_name(person.name)
        row.revision += 1
        said.append("name")
    phone = normalise_phone(person.phone, default_country="91") if person.phone else None
    try:
        phone = validate_e164(phone)
    except ValueError:
        phone = None  # not a number a profile can keep; said below as no phone given
    profile: SalesXrayProfile | None = await db.scalar(
        select(SalesXrayProfile).where(SalesXrayProfile.person_id == person_id)
    )
    if phone is not None and (profile is None or profile.phone_number_e164 is None):
        # A number another person's profile has stays for an admin to review.
        shared = await db.scalar(
            select(SalesXrayProfile.person_id)
            .where(
                SalesXrayProfile.phone_number_e164 == phone,
                SalesXrayProfile.person_id != person_id,
            )
            .limit(1)
        )
        if profile is None:
            db.add(
                SalesXrayProfile(
                    person_id=person_id,
                    phone_number_e164=phone,
                    admin_collision_review_required=shared is not None,
                    revision=1,
                )
            )
        else:
            profile.phone_number_e164 = phone
            profile.admin_collision_review_required = shared is not None
            profile.revision += 1
        said.append("phone")
    elif profile is not None and profile.phone_number_e164:
        said.append("phone_kept")
    else:
        said.append("no_phone_given")
    await db.flush()
    return "+".join(said)


async def _readback(db: AsyncSession, tenant_id: UUID, label: str) -> dict[str, Any]:
    tenant = await db.get(Tenant, tenant_id)
    team = (
        await db.execute(
            select(Membership.person_id, Membership.role, Person.display_name, Person.email)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
            .order_by(Membership.role, Person.display_name)
        )
    ).all()
    names = {person_id: name or _mask(email) for person_id, _, name, email in team}
    held = Counter(
        (
            await db.scalars(
                select(Lead.owner_person_id).where(
                    Lead.tenant_id == tenant_id, Lead.source_label == label
                )
            )
        ).all()
    )
    sandbox = await db.scalar(
        select(ConversationSandboxOrganisation.tenant_id).where(
            ConversationSandboxOrganisation.tenant_id == tenant_id
        )
    )
    return {
        "tenant_id": str(tenant_id),
        "name": tenant.name if tenant else None,
        "calls": "simulated (a sandbox)" if sandbox is not None else "from their own phones",
        "members": [
            {"role": role, "name": name, "email": _mask(email)} for _, role, name, email in team
        ],
        "leads_by_person": {
            names.get(owner, "nobody") if owner else "nobody": count
            for owner, count in held.items()
        },
    }


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    name = " ".join(str(spec["organisation"]).split())
    label = str(spec.get("label") or LABEL)[:120]
    people = members(spec)
    spellings = name_map(people)
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    approver = await _person(db, str(spec["approver_email"]))
    report: dict[str, Any] = {"mode": mode, "organisation": name, "label": label}
    prior: Organisation | None = await db.scalar(
        select(Organisation).where(Organisation.creation_command_id == command_id)
    )
    if mode == "read":
        report["status"] = "read" if prior is not None else "not_found"
        if prior is not None:
            report["after"] = await _readback(db, prior.tenant_id, label)
        return report
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found"}))

    # 1. The accounts.
    ids: dict[str, UUID] = {}
    accounts: list[dict[str, str]] = []
    for person in people:
        ids[person.email], state = await _account(db, person, command_id, now)
        accounts.append(
            {
                "role": person.role,
                "name": person.name,
                "email": _mask(person.email),
                "is": state,
                "profile": await _profile(db, ids[person.email], person),
            }
        )
    report["accounts"] = accounts
    owner = people[0]

    # 2. The organisation and its members.
    service = OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    )
    reference = f"approved-data-change:{spec.get('issue')}"
    if prior is None:
        twin = await db.scalar(
            select(Tenant.id)
            .join(Membership, Membership.tenant_id == Tenant.id)
            .where(
                Membership.person_id == ids[owner.email],
                Membership.ended_at.is_(None),
                func.lower(Tenant.name) == name.lower(),
            )
            .limit(1)
        )
        if twin is not None:
            raise SystemExit(json.dumps({"refused": "owner_has_one_by_this_name"}))
        created = await service.create(
            name,
            ids[owner.email],
            command_id,
            reference,
            reason=f"Done-for-you onboarding ({spec.get('issue')})",
        )
        tenant_id = created.tenant_id
        report["organisation_is"] = "made"
        # Its leads start on the sales team's stages, as an organisation made in the app does.
        await journeys.start_organisation(db, tenant_id, approver.id, now)
    else:
        tenant_id = prior.tenant_id
        report["organisation_is"] = "found"
    for person in people[1:]:
        current = await db.get(Membership, (tenant_id, ids[person.email]))
        if current is not None and current.ended_at is None and current.status == "active":
            continue
        await service.add_member(
            tenant_id,
            ids[person.email],
            "member",
            uuid5(command_id, f"member:{person.email}"),
            operator_reference=reference,
            reason=f"Done-for-you onboarding ({spec.get('issue')})",
        )
    if (
        await db.scalar(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == tenant_id
            )
        )
        is not None
    ):
        raise SystemExit(json.dumps({"refused": "organisation_is_a_sandbox"}))
    desk = LeadDesk(
        db,
        # The operator, for the owner: every history line names the approved data change's
        # approver, as the file import does.
        Viewer(person_id=approver.id, tenant_id=tenant_id, role="owner", name="Onboarding"),
        call_mode="phone",
        now=now,
    )
    if "seller_limit" in spec:
        for person in people[1:]:
            row = await db.get(LeadRep, (tenant_id, ids[person.email]))
            if row is None or row.max_open != spec["seller_limit"]:
                await desk.save_rep(
                    ids[person.email],
                    RepRules(
                        expected_revision=row.revision if row else 0,
                        available=row.available if row else True,
                        max_open=spec["seller_limit"],
                        languages=tuple(row.languages or ()) if row else (),
                        areas=tuple(row.areas or ()) if row else (),
                        interests=tuple(row.interests or ()) if row else (),
                    ),
                )

    # 3 and 4. The sheet, each row to the person its "called by" names.
    sheet = read_csv(str(spec["csv"]).encode("utf-8"))
    mapping = {str(k): str(v) for k, v in dict(spec.get("mapping") or {}).items()} or (
        suggest_mapping(sheet.headers)
    )
    caller = column(sheet.headers, spec.get("called_by_column"), CALLED_BY, "called_by")
    due = column(sheet.headers, spec.get("follow_up_column"), FOLLOW_UP, "follow_up")
    today = now.astimezone(IST).date()
    follow: Counter[str] = Counter()
    records, dropped = rows_of(sheet.rows)
    _, config = await desk.settings()
    values: Counter[str] = Counter()
    given: dict[str, str] = {}
    preview: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for record in records:
        said = record.get(caller, "") if caller else ""
        values[said] += 1
        person = spellings.get(fold(said)) if said else None
        target = person or owner
        why = "blank" if not said else "not listed"
        given[said] = target.name if person else f"{owner.name} (the owner: {why})"
        step = uuid5(command_id, f"row:{content_ref(record)}")
        if await desk._command_seen(step) is not None:
            counts["done_before"] += 1
            continue
        lead, outcome = await desk.ingest(
            record,
            source="csv",
            source_label=label,
            source_ref=content_ref(record),
            mapping=mapping,
            assign="person",
            person_id=ids[target.email],
            actor=approver.id,
            command_id=step,
        )
        counts[outcome] += 1
        if outcome == "created":
            preview[target.name] += 1
        written = record.get(due, "") if due else ""
        if outcome != "created" or lead is None or not written:
            continue
        day = follow_up_day(written, today)
        at = follow_up_at(day, now) if day else None
        if at is None:
            follow["past" if day else "unreadable"] += 1
            continue
        await desk.follow_up(
            lead.id,
            FollowUp(command_id=uuid5(step, "follow-up"), expected_revision=lead.revision, at=at),
        )
        follow["today" if day == today else "later"] += 1
    await db.flush()
    report["sheet"] = {
        "rows": len(sheet.rows),
        "truncated": sheet.truncated,
        "exact_repeats_dropped": len(dropped),
        "dropped_rows": dropped[:50],
        "mapping": mapping,
        "called_by_column": caller,
        "follow_up_column": due,
        "default_country": config.get("default_country"),
    }
    # The map as the sheet writes it: these are the business's own people, not leads.
    report["called_by_map"] = [
        {"called_by": said or "(blank)", "rows": rows, "goes_to": given[said]}
        for said, rows in sorted(values.items(), key=lambda item: (-item[1], item[0]))
    ]
    report["unlisted"] = sorted(said for said in values if said and fold(said) not in spellings)
    report["new_leads_by_person"] = dict(preview)
    report["counts"] = dict(counts)
    report["follow_ups"] = dict(follow)
    report["over_limit"] = await desk.over_limit(ids[person.email] for person in people[1:])
    if report["over_limit"]:
        report["hint"] = (
            'Add "seller_limit": null (no limit) or a number to the input to lift them.'
        )

    # 5. The audit event, when anything changed.
    changed = report["organisation_is"] == "made" or counts["created"] + counts["repeat"] > 0
    report["audited"] = changed
    if changed:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, f"audit:{now.isoformat()}")),
            reason=f"Owner approval: done-for-you onboarding, {spec.get('issue')}",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "organisation": report["organisation_is"],
                "people": len(people),
                "counts": dict(counts),
                "exact_repeats_dropped": len(dropped),
                "by_person": {str(ids[p.email]): preview.get(p.name, 0) for p in people},
            },
        )
    report["play"] = {
        "opt_in_link": str(spec.get("play_optin_url") or PLAY_OPTIN),
        "add_as_testers": [person.email for person in people],
    }
    report["after"] = await _readback(db, tenant_id, label)
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
) -> dict[str, Any]:
    """One transaction: committed on apply, rolled back otherwise."""
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, now=now, boundaries=boundaries)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(path: str, mode: Mode) -> int:
    settings = get_settings()
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise SystemExit(json.dumps({"refused": "tenant_boundaries_not_configured"}))
    engine = create_async_engine(settings.database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
            boundaries=(settings.operations_tenant_id, settings.public_learner_tenant_id),
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
