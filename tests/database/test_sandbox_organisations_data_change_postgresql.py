"""The approved data change that builds the fictional sandbox organisations
(scripts/data-changes/sandbox-organisations.py), on PostgreSQL, at a small scale: a dry run
that simulates everything and leaves nothing; the apply through the app's own code (the
owner as Owner, the coach as Admin, five verified sellers who sign in with their password,
a sandbox flag, live and cold test-data leads given out by the team's rules, calls as the
phone logs them inside work hours, stage moves, follow-up tasks and meetings); one audit
event; a rerun that changes nothing; and the read-back."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.password_auth import hash_password, verify_password
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMeeting, LeadTask
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/sandbox-organisations.py"
LOADER = importlib.util.spec_from_file_location("sandbox_organisations_db", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
sys.modules["sandbox_organisations_db"] = tool
LOADER.loader.exec_module(tool)
IST = ZoneInfo("Asia/Kolkata")
PASSWORD = "fictional-sandbox-login-1"  # noqa: S105 - a test-only password


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_rehearse_apply_once_audited_rerun_and_read_back(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                owner = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
                coach = await db.scalar(
                    select(Person.email).where(Person.id == here.seller.person_id)
                )
            assert owner and coach
            mailbox = "owner@example.test"
            raw = {
                # A fixed command id: the same simulated month on every run.
                "command_id": "5a9d0e2c-3b1f-4c7a-9e60-30a10c2026aa",
                "approver_email": owner,
                "issue": "owner chat 30 Oct 2026",
                "owner_email": owner,
                "admin_email": coach,
                "seller_mailbox": mailbox,
                "organisations": ["ac"],
                "days": 10,
                "scale": 0.3,
                "require_pipeline": False,
            }
            emails = tool.logins(tool.spec_of(json.dumps(raw)))["ac"]
            verifier = hash_password(PASSWORD)
            raw["password_hashes"] = {email: verifier for email in emails}
            spec = tool.spec_of(json.dumps(raw))
            options: dict[str, Any] = {"now": datetime.now(UTC), "boundaries": (uuid4(), uuid4())}
            name = tool.ORGS["ac"].name

            async def count(model: Any, *where: Any) -> int:
                async with sessions() as db:
                    return int(
                        await db.scalar(select(func.count()).select_from(model).where(*where)) or 0
                    )

            # The dry run simulates it all, reports it, and leaves nothing.
            [dry] = await tool.execute(sessions, spec, mode="dry-run", **options)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["after"]["leads"]["total"] > 0
            assert await count(Tenant, Tenant.name == name) == 0
            assert await count(Person, Person.email.in_(emails)) == 0
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 0

            [done] = await tool.execute(sessions, spec, mode="apply", **options)
            assert done["status"] == "applied"
            made = done["after"]
            tenant = UUID(made["tenant_id"])
            assert made["sandbox"] is True
            assert (
                await count(
                    ConversationSandboxOrganisation,
                    ConversationSandboxOrganisation.tenant_id == tenant,
                )
                == 1
            )
            roles = sorted(member["role"] for member in made["members"])
            assert roles == ["admin", "member", "member", "member", "member", "member", "owner"]
            assert sorted(m["email"] for m in made["members"] if m["role"] == "member") == sorted(
                emails
            )
            # Each seller is verified and signs in with the password the verifier came from.
            async with sessions() as db:
                for email in emails:
                    person = await db.scalar(select(Person).where(Person.email == email))
                    assert person is not None and person.email_verified_at is not None
                    credential = await db.scalar(
                        select(PasswordCredential).where(PasswordCredential.person_id == person.id)
                    )
                    assert credential is not None
                    assert verify_password(PASSWORD, credential.password_hash)
                    member = await db.get(Membership, (tenant, person.id))
                    assert member is not None and member.role == "member"

            # Inbound and Cold leads, all test data, none held by the owner or the coach; the
            # big Cold list came in two days before the end, so most of it is still Unworked.
            leads = made["leads"]
            assert leads["test_data"] == leads["total"] > 0
            assert leads["source:csv"] > 0
            assert leads.get("source:meta", 0) + leads.get("source:webhook", 0) > 0
            assert leads.get("unassigned", 0) == 0
            assert leads["cold_unworked"] > 0.7 * leads["source:csv"]
            assert made["template"] in (tool.RECOMMENDED, "inside_sales_demos")
            assert set(made["by_side"]) == {"Inbound", "Cold"}
            # The Inbound-only seller holds no Cold lead; the Cold-only seller no Inbound one.
            for seller in tool.ORGS["ac"].sellers:
                held = made["leads_by_seller"].get(f"{seller.first} {seller.last}", {})
                if seller.sides == "inbound":
                    assert held.get("Cold", 0) == 0
                if seller.sides == "cold":
                    assert held.get("Inbound", 0) == 0 and held.get("Cold", 0) > 0
            if hasattr(Lead, "pipeline"):
                # The uploaded list is Cold; every live source stays Live (migration 0146).
                assert leads["pipeline:cold"] == leads["source:csv"]
                assert leads["pipeline:live"] == leads["total"] - leads["source:csv"]
            async with sessions() as db:
                holders = set(
                    (
                        await db.scalars(
                            select(Lead.owner_person_id).where(Lead.tenant_id == tenant)
                        )
                    ).all()
                )
            assert here.setup.state.person_id not in holders
            assert here.seller.person_id not in holders

            # Calls with real starts inside work hours, most of them not connected.
            calls = made["calls"]
            assert calls["calls"] > 20
            assert 0.3 < calls["not_connected"] / calls["calls"] < 0.8
            assert calls["talk_minutes"] > 0
            async with sessions() as db:
                starts = (
                    await db.scalars(
                        select(LeadEvent.created_at).where(
                            LeadEvent.tenant_id == tenant, LeadEvent.kind == "call"
                        )
                    )
                ).all()
                stages = set(
                    (await db.scalars(select(Lead.stage).where(Lead.tenant_id == tenant))).all()
                )
            for start in starts:
                local = start.astimezone(IST)
                assert local.weekday() != 6
                assert time(10, 30) <= local.time() < time(19, 0)
            assert {"new", "not_connected"} <= stages
            assert stages & {"interested", "won", "lost"}
            assert made["tasks"]
            assert await count(LeadTask, LeadTask.tenant_id == tenant) == sum(
                v for k, v in made["tasks"].items() if k in ("open", "done", "cancelled")
            )
            assert await count(LeadMeeting, LeadMeeting.tenant_id == tenant) == sum(
                made["meetings"].values()
            )
            assert await count(AuditEvent, AuditEvent.action == tool.ACTION) == 1

            # A rerun changes nothing; the read-back sees what the apply made.
            [again] = await tool.execute(sessions, spec, mode="apply", **options)
            assert again["status"] == "already_applied"
            assert await count(Lead, Lead.tenant_id == tenant) == leads["total"]
            assert await count(Tenant, Tenant.name == name) == 1
            [read] = await tool.execute(sessions, spec, mode="read", **options)
            assert read["status"] == "read" and read["after"] == made

    run(exercise())
