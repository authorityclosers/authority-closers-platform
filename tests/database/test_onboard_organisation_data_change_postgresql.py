"""The done-for-you onboarding (scripts/data-changes/onboard-organisation.py) on PostgreSQL:
- the dry run rehearses everything and leaves nothing (no organisation, no account);
- the apply makes the accounts, the organisation and its members, and imports the sheet: an
  exact repeat row dropped, +91 numbers, every column kept, each lead with the person its
  "called by" names (a variant as listed, without case or dots), a blank or unlisted value
  with the owner, a follow-up date today or later as the next call at 10:00 IST and a past
  one left as written; one audit event;
- a rerun changes nothing and is not audited; tonight's sheet adds its new row and makes a
  changed row a repeat on its lead, whose owner stays;
- a spelling listed for two people is refused;
- each person's Sales X-Ray profile has their name and phone from the input, so a first call
  goes to review without "A few details before we review your call"; a phone the person set
  themselves is kept, and a rerun changes no profile.
Made-up people only."""

from __future__ import annotations

import csv
import importlib.util
import io
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.sales_xray_profile import require_sales_xray_profile_complete
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.identity.services import PersonSnapshot
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/onboard-organisation.py"
LOADER = importlib.util.spec_from_file_location("onboard_organisation", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)

IST = ZoneInfo("Asia/Kolkata")
HEADERS = ("Sr No", "Name", "Mobile No", "Email", "Called By", "Follow up date", "Remarks")


def sheet(rows: list[tuple[str, ...]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return out.getvalue()


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_rehearse_apply_map_follow_ups_rerun_and_resync(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                approver = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            now = datetime.now(UTC)
            tomorrow = now.astimezone(IST).date() + timedelta(days=1)
            past = now.astimezone(IST).date() - timedelta(days=3)
            rows = [
                ("1", "Fictional One", "9876081001", "", "Asha", f"{tomorrow:%d/%m/%Y}", "Call"),
                ("2", "Fictional Two", "+91 98760 81002", "", "ASHA S.", "", ""),
                ("3", "Fictional Three", "098760-81003", "", "ravi", f"{past:%d/%m/%Y}", ""),
                ("4", "काल्पनिक चार", "9876081004", "", "", "", "Blank caller"),
                ("5", "Fictional Five", "9876081005", "", "Asha/Ravi", "", ""),
                ("6", "Fictional Six", "9876081006", "", "Manager", "", ""),
                ("1", "Fictional One", "9876081001", "", "Asha", f"{tomorrow:%d/%m/%Y}", "Call"),
            ]
            spec: dict[str, Any] = {
                "command_id": str(uuid4()),
                "organisation": "Fictional Onboarded Business",
                "approver_email": approver,
                "issue": "AUT-test",
                "owner": {
                    "name": "Kavya Owner",
                    "phone": "9876090001",
                    "email": "kavya.owner@example.com",
                    "called_by": ["Manager"],
                },
                "sellers": [
                    {
                        "name": "Asha Sample",
                        "phone": "+91 98760 90002",
                        "email": "asha.s@example.com",
                        "called_by": ["Asha", "Asha S"],
                    },
                    {
                        "name": "Ravi Demo",
                        "phone": "098760-90003",
                        "email": "ravi.d@example.com",
                        "called_by": ["Ravi"],
                    },
                ],
                "csv": sheet(rows),
                "seller_limit": None,
            }
            options: dict[str, Any] = {"now": now, "boundaries": (uuid4(), uuid4())}
            # Ravi signed in before and set his own phone: it stays.
            ravi = uuid4()
            async with sessions() as db, db.begin():
                await AsyncSqlAlchemyIdentityRepository(db).save_person(
                    PersonSnapshot(
                        id=ravi,
                        email="ravi.d@example.com",
                        display_name="Ravi Demo",
                        email_verified_at=now,
                    )
                )
                db.add(
                    SalesXrayProfile(person_id=ravi, phone_number_e164="+919999990003", revision=1)
                )

            async def count(model: Any, *where: Any) -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(select(func.count()).select_from(model).where(*where)) or 0
                    )

            dry = await tool.execute(sessions, spec, mode="dry-run", **options)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["sheet"]["exact_repeats_dropped"] == 1
            assert dry["counts"] == {"created": 6}
            assert dry["unlisted"] == ["Asha/Ravi"]
            goes = {item["called_by"]: item["goes_to"] for item in dry["called_by_map"]}
            assert goes["Asha"] == goes["ASHA S."] == "Asha Sample"
            assert goes["ravi"] == "Ravi Demo" and goes["Manager"] == "Kavya Owner"
            assert goes["(blank)"].startswith("Kavya Owner (the owner")
            assert dry["play"]["add_as_testers"] == [
                "kavya.owner@example.com",
                "asha.s@example.com",
                "ravi.d@example.com",
            ]
            assert await count(Tenant, Tenant.name == spec["organisation"]) == 0
            assert await count(Person, Person.email == "asha.s@example.com") == 0

            done = await tool.execute(sessions, spec, mode="apply", **options)
            assert done["status"] == "applied" and done["organisation_is"] == "made"
            assert done["follow_ups"] == {"later": 1, "past": 1}
            assert done["over_limit"] == []
            tenant = UUID(done["after"]["tenant_id"])
            assert done["after"]["calls"] == "from their own phones"
            assert sorted(m["role"] for m in done["after"]["members"]) == [
                "member",
                "member",
                "owner",
            ]
            assert done["after"]["leads_by_person"] == {
                "Asha Sample": 2,
                "Ravi Demo": 1,
                "Kavya Owner": 3,
            }
            async with sessions() as db:
                leads = {
                    lead.phone: lead
                    for lead in (await db.scalars(select(Lead).where(Lead.tenant_id == tenant)))
                }
                verified = await db.scalar(
                    select(Person.email_verified_at).where(Person.email == "ravi.d@example.com")
                )
            assert set(leads) == {f"+91987608100{n}" for n in range(1, 7)}
            first = leads["+919876081001"]
            assert first.payload["Remarks"] == "Call" and first.payload["Sr No"] == "1"
            assert first.next_action_at == datetime.combine(tomorrow, time(10), tzinfo=IST)
            assert leads["+919876081003"].next_action_at is None
            assert verified is not None
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 1
            # A new organisation starts on the sales team's eight stages.
            async with sessions() as db:
                journey = await journeys.read(db, tenant)
            assert journey.industry == "inside_sales_demos" and journey.junk_in_lost
            assert [stage.label for stage in journey.live][0] == "New lead"

            # Profiles: name and phone from the input; Ravi's own kept; complete, so no
            # details form before the terms box on a first call.
            assert [a["profile"] for a in done["accounts"]] == [
                "phone",
                "phone",
                "phone_kept",
            ]
            async with sessions() as db:
                profiles = {
                    row.person_id: row for row in (await db.scalars(select(SalesXrayProfile))).all()
                }
                for email in (
                    "kavya.owner@example.com",
                    "asha.s@example.com",
                    "ravi.d@example.com",
                ):
                    person_id = await db.scalar(select(Person.id).where(Person.email == email))
                    assert person_id is not None
                    complete = await require_sales_xray_profile_complete(db, person_id=person_id)
                    assert complete.profile_complete
                asha_id = await db.scalar(
                    select(Person.id).where(Person.email == "asha.s@example.com")
                )
            assert asha_id is not None
            assert profiles[asha_id].phone_number_e164 == "+919876090002"
            assert profiles[ravi].phone_number_e164 == "+919999990003"
            asha_revision = profiles[asha_id].revision

            again = await tool.execute(sessions, spec, mode="apply", **options)
            assert again["organisation_is"] == "found" and again["audited"] is False
            assert [a["profile"] for a in again["accounts"]] == ["phone_kept"] * 3
            async with sessions() as db:
                kept = await db.scalar(
                    select(SalesXrayProfile.revision).where(SalesXrayProfile.person_id == asha_id)
                )
            assert kept == asha_revision
            assert again["counts"] == {"done_before": 6}
            assert await count(Lead, Lead.tenant_id == tenant) == 6
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 1

            # Tonight's sheet: row 2 changed (and now says Ravi), and a new row 7.
            tonight = [*rows[:6]]
            tonight[1] = ("2", "Fictional Two", "+91 98760 81002", "", "Ravi", "", "Called back")
            tonight.append(("7", "Fictional Seven", "9876081007", "", "Ravi", "", ""))
            synced = await tool.execute(
                sessions, {**spec, "csv": sheet(tonight)}, mode="apply", **options
            )
            assert synced["counts"] == {"done_before": 5, "repeat": 1, "created": 1}
            async with sessions() as db:
                kept = await db.scalar(
                    select(Lead.owner_person_id).where(
                        Lead.tenant_id == tenant, Lead.phone == "+919876081002"
                    )
                )
                asha = await db.scalar(
                    select(Membership.person_id)
                    .join(Person, Person.id == Membership.person_id)
                    .where(Membership.tenant_id == tenant, Person.email == "asha.s@example.com")
                )
            assert kept == asha  # a repeat keeps its owner

            read = await tool.execute(sessions, spec, mode="read", **options)
            assert read["status"] == "read" and read["after"]["tenant_id"] == str(tenant)

            twice = {**spec, "command_id": str(uuid4()), "organisation": "Fictional Other"}
            twice["sellers"] = [
                {"name": "Asha Sample", "email": "asha.s@example.com", "called_by": ["AS"]},
                {"name": "Arun Sample", "email": "arun.s@example.com", "called_by": ["as"]},
            ]
            with pytest.raises(SystemExit, match="a_spelling_names_two_people"):
                await tool.execute(sessions, twice, mode="dry-run", **options)

    run(exercise())
