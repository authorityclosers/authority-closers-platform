"""Create the AI-directory reviewer account and its fictional test organisation (approved
data change).

Owner, 25 Oct 2026 (AUT-2222, through the orchestrator): "approve data change: create one
directory reviewer account with fictional calls and leads in its own test organisation, for
the Claude and ChatGPT directory reviews, production". ChatGPT's reviewers sign in with a
password (no email codes or MFA). In one transaction, through the app's own code:
  1. the reviewer: a new person with a verified email and a password. The password comes on
     standard input (generated into Infisical, never shown) and is stored only as the app's
     own hash. An existing person with that email is refused, never taken over;
  2. the organisation, as an operator creates one (``OrganisationService.create``, idempotent
     by command id), owned by the approving owner's account, with the reviewer as Admin (an
     owner or admin sees the team's calls and leads);
  3. the sandbox mark (``conversation_sandbox_organisations``, set only by an approved data
     change), so its leads are test data and the synthetic call loader may then fill it with
     fictional analysed calls held by the reviewer: ``load-sales-xray-sandbox-hosted.py
     --target-tenant <it> --target-name <its name> --seller-person-id <the reviewer>``;
  4. the template's stages, and ten fictional leads held by the reviewer, every one test
     data, a few moved on as a seller would (one history line each);
  5. one audit event naming the approver and the issue.
No real person, company or number: the names are made up, and the leads have no phone or email.

A dry run (the default) makes the whole change in its transaction, reports it and rolls it
back. A rerun after apply finds the organisation by its command id and changes nothing.
``--read`` reads the result back in a read-only transaction (no password needed).

Run inside the API container with the deployed settings. Standard input carries the
password, so the script goes in first (the container's /tmp is writable):
    docker exec -i <api> sh -c 'cat > /tmp/directory-reviewer.py' < directory-reviewer.py
    <password> | docker exec -i <api> python /tmp/directory-reviewer.py '<input JSON>' [--apply]
input: {"command_id", "reviewer_email", "display_name", "org_name", "owner_email",
        "approver_email", "issue", "template": "inside_sales_demos"}
Prints masked emails, ids, the fictional leads' names, stage keys and counts only.
"""

from __future__ import annotations

import asyncio
import json
import sys
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
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.password_auth import hash_password, validate_password
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import PersonSnapshot
from ac_platform.lead_desk.contracts import NewLead, StageMove
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.templates import TEMPLATES
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

Mode = Literal["dry-run", "apply", "read"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "identity.directory_reviewer_data_change"
ROLE: Final = "admin"


class Spot(NamedTuple):
    """A fictional lead and the step it ends at ("new" stays where it lands). A named
    tuple: the script also loads as a plain file."""

    name: str
    company: str | None
    city: str
    interest: str
    language: str
    step: str


# Made up: no real person, company or number. Four in Pune, for the directories' test
# prompt "find my leads from Pune".
LEADS: Final[tuple[Spot, ...]] = (
    Spot(
        "Anita Sample",
        "Sample Interiors",
        "Pune",
        "Office interiors quote",
        "English",
        "interested",
    ),
    Spot("Vikram Example", "Example Logistics", "Pune", "Fleet tracking demo", "Hindi", "new"),
    Spot("Neha Demo", None, "Mumbai", "Home loan advice", "Marathi", "not_connected"),
    Spot(
        "Arjun Sample",
        "Sample Academy",
        "Nashik",
        "Sales coaching for 20 sellers",
        "English",
        "interested",
    ),
    Spot("Kavya Example", "Example Clinics", "Pune", "Clinic booking software", "English", "new"),
    Spot("Rahul Demo", "Demo Textiles", "Surat", "Bulk order pricing", "Hindi", "lost"),
    Spot("Pooja Sample", None, "Nagpur", "Weekend course enquiry", "Marathi", "new"),
    Spot(
        "Sameer Example",
        "Example Builders",
        "Pune",
        "Site visit next week",
        "Marathi",
        "interested",
    ),
    Spot("Divya Demo", "Demo Bakery", "Bengaluru", "Office catering enquiry", "English", "new"),
    Spot(
        "Imran Sample", "Sample Hardware", "Hyderabad", "Dealer enquiry", "Hindi", "not_connected"
    ),
)
STEPS: Final[frozenset[str]] = frozenset({"new", "not_connected", "interested", "lost"})
FICTIONAL: Final[tuple[str, ...]] = (" Sample", " Example", " Demo")


def _input(path: str) -> dict[str, Any]:
    """The input, inline JSON or a file."""
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _at(now: datetime, days: int, hour: int) -> datetime:
    """A time of day in India, some days from now's date there."""
    day: date = now.astimezone(IST).date() + timedelta(days=days)
    return datetime.combine(day, time(hour), tzinfo=IST)


def refusal(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def read_password(stream: Any) -> str:
    """One line from standard input, checked by the app's own password rules; never echoed."""
    line = stream.readline() if stream is not None and not stream.isatty() else ""
    password = line.rstrip("\r\n")
    try:
        return validate_password(password)
    except Exception:
        raise refusal("password_missing_or_invalid") from None


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


async def _created(db: AsyncSession, command_id: UUID) -> Organisation | None:
    found: Organisation | None = await db.scalar(
        select(Organisation).where(Organisation.creation_command_id == command_id)
    )
    return found


async def _readback(db: AsyncSession, tenant_id: UUID, reviewer_id: UUID) -> dict[str, Any]:
    """What the reviewer will see: the organisation, its people, the stages and the leads."""
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    members = (
        await db.execute(
            select(Membership.role, Membership.status, Person.email, Person.id)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id, Membership.ended_at.is_(None))
            .order_by(Membership.role)
        )
    ).all()
    journey = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    leads = (
        await db.execute(
            select(Lead.name, Lead.stage, Lead.step, Lead.test_data)
            .where(Lead.tenant_id == tenant_id, Lead.owner_person_id == reviewer_id)
            .order_by(Lead.created_at, Lead.name)
        )
    ).all()
    reviewer = await db.get(Person, reviewer_id)
    return {
        "tenant_id": str(tenant_id),
        "name": tenant.name,
        "sandbox": await db.get(ConversationSandboxOrganisation, tenant_id) is not None,
        "reviewer": {
            "person_id": str(reviewer_id),
            "email": _mask(reviewer.email if reviewer else None),
            "email_verified": bool(reviewer and reviewer.email_verified_at),
            "password_set": await db.scalar(
                select(func.count())
                .select_from(PasswordCredential)
                .where(PasswordCredential.person_id == reviewer_id)
            )
            == 1,
        },
        "members": [
            {"role": role, "status": status, "email": _mask(email), "reviewer": pid == reviewer_id}
            for role, status, email, pid in members
        ],
        "leads": [
            {
                "name": name,
                "stage": found.key if (found := journey.resolve(stage, step)) else stage,
                "test_data": test_data,
            }
            for name, stage, step, test_data in leads
        ],
    }


async def _place(desk: LeadDesk, lead: Lead, spot: Spot, command_id: UUID, now: datetime) -> None:
    """Moves the lead to its step as a seller would; "new" stays."""
    if spot.step == "new":
        return
    given: dict[str, Any] = {}
    if spot.step == "not_connected":
        given = {"nc_reason": "did_not_pick", "next_action_at": _at(now, 1, 11)}
    elif spot.step == "interested":
        given = {"next_action_at": _at(now, 2, 12)}
    elif spot.step == "lost":
        given = {"outcome_reason": "price"}
    await desk.move(
        lead.id,
        StageMove(
            command_id=uuid5(command_id, f"{spot.name}:{spot.step}"),
            expected_revision=lead.revision,
            step=spot.step,
            via="api",
            **given,
        ),
    )


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
    password: str | None,
) -> dict[str, Any]:
    """The change, its rehearsal, or its read-back, inside the caller's transaction."""
    command_id = UUID(spec["command_id"])
    name = str(spec["org_name"]).strip()
    reviewer_email = str(spec["reviewer_email"]).strip().lower()
    template_id = str(spec.get("template") or "inside_sales_demos")
    profile = next((item for item in TEMPLATES if item.id == template_id), None)
    if profile is None or not STEPS - {"new"} <= {stage.key for stage in profile.stages}:
        raise refusal("template_lacks_the_fixture_steps", template=template_id)
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    owner = await _person(db, str(spec["owner_email"]))
    approver = await _person(db, str(spec["approver_email"]))
    reviewer_id = uuid5(command_id, "person")
    report: dict[str, Any] = {
        "mode": mode,
        "organisation": name,
        "reviewer": _mask(reviewer_email),
        "owner_found": owner is not None,
        "approver_found": approver is not None,
    }
    prior = await _created(db, command_id)
    if prior is not None:
        report["status"] = "already_applied" if mode != "read" else "read"
        report["result"] = await _readback(db, prior.tenant_id, reviewer_id)
        return report
    if mode == "read":
        report["status"] = "not_found"
        return report
    if owner is None or approver is None:
        raise refusal("person_not_found", **report)
    if await _person(db, reviewer_email) is not None:
        # Never take over an account someone (or an earlier run) already has.
        raise refusal("reviewer_email_already_has_an_account", **report)
    if password is None:
        raise refusal("password_missing_or_invalid")

    repo = AsyncSqlAlchemyIdentityRepository(db)
    await repo.save_person(
        PersonSnapshot(
            id=reviewer_id,
            email=reviewer_email,
            display_name=str(spec.get("display_name") or "Directory Reviewer")[:120],
            email_verified_at=now,
        )
    )
    db.add(PasswordCredential(person_id=reviewer_id, password_hash=hash_password(password)))
    await db.flush()

    service = OrganisationService(
        db, operations_tenant_id=boundaries[0], public_learner_tenant_id=boundaries[1]
    )
    created = await service.create(
        name,
        owner.id,
        command_id,
        f"approved-data-change:{spec.get('issue')}",
        reason=f"Fictional organisation for the AI-directory reviewers ({spec.get('issue')})",
    )
    tenant_id = created.tenant_id
    await service.add_member(
        tenant_id,
        reviewer_id,
        ROLE,
        uuid5(command_id, "member"),
        operator_reference=f"approved-data-change:{spec.get('issue')}",
        reason=f"AI-directory reviewer ({spec.get('issue')})",
    )
    db.add(
        ConversationSandboxOrganisation(
            tenant_id=tenant_id,
            approved_by_person_id=approver.id,
            approval_reference=f"approve data change ({spec.get('issue')})"[:160],
            created_at=now,
        )
    )
    before = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    saved = await journeys.save(
        db,
        tenant_id,
        stages=journeys.from_template(template_id, before, {}),
        industry=template_id,
        expected_version=before.version,
        note=f"Used the {profile.name} stages (approved data change, {spec.get('issue')})",
        by=owner.id,
        now=now,
        pipeline=journeys.MAIN_PIPELINE,
    )
    desk = LeadDesk(
        db,
        Viewer(person_id=reviewer_id, tenant_id=tenant_id, role=ROLE, name="Test data"),
        sandbox=True,
        now=now,
    )
    for index, spot in enumerate(LEADS):
        detail = await desk.add(
            NewLead(
                command_id=uuid5(command_id, f"lead:{index}"),
                name=spot.name,
                company=spot.company,
                city=spot.city,
                interest=spot.interest,
                language=spot.language,
                assign="me",
            )
        )
        lead = await db.get(Lead, detail.lead.lead_id)
        assert lead is not None
        await _place(desk, lead, spot, command_id, now)
    await db.flush()
    await append_audit_event(
        db,
        tenant_id=tenant_id,
        actor_person_id=approver.id,
        actor_type="operator",
        action=ACTION,
        resource_type="tenant",
        resource_id=tenant_id,
        request_id=str(uuid5(command_id, "audit")),
        reason="Owner approval: one directory reviewer account with fictional data",
        payload={
            "issue": spec.get("issue"),
            "command_id": str(command_id),
            "reviewer_person_id": str(reviewer_id),
            "role": ROLE,
            "template": template_id,
            "version": saved.version,
            "leads": len(LEADS),
            "sandbox": True,
            "test_data": True,
        },
    )
    report["result"] = await _readback(db, tenant_id, reviewer_id)
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    boundaries: tuple[UUID, UUID],
    password: str | None,
) -> dict[str, Any]:
    """One transaction: committed on apply, rolled back otherwise."""
    async with sessions() as db:
        try:
            report = await run(
                db, spec, mode=mode, now=now, boundaries=boundaries, password=password
            )
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
    password = None if mode == "read" else read_password(sys.stdin)
    engine = create_async_engine(settings.database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
            boundaries=(settings.operations_tenant_id, settings.public_learner_tenant_id),
            password=password,
        )
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
