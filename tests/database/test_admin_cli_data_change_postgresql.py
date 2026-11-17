"""The admin CLI (scripts/data-changes/admin.py) on PostgreSQL, every command group through the
app's own services: a dry run makes the change and rolls it back (nothing stays, no audit); an
apply commits once with one ``admin.data_change_applied`` event naming the approver and the
issue; the same command again replays and changes nothing. Made-up people and leads only
(owner, 17 Nov 2026: "every base-level primitive", not just adding people)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadRep
from ac_platform.lead_desk.store import DEFAULT_SETTINGS, default_cap
from ac_platform.tenancy.models import Membership, OrganisationInvite, Tenant
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/admin.py"
LOADER = importlib.util.spec_from_file_location("admin_cli_db", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


class Cli:
    """Runs admin.py commands in the test database as a named operator."""

    def __init__(self, here: Any, settings: Any, operator: UUID) -> None:
        self.here, self.settings, self.operator = here, settings, operator
        self.sessions = here.setup.sessions

    async def __call__(self, *argv: str, apply: bool = False, write: bool = True) -> Any:
        given = [*argv, "--environment", "development"]
        if "--tenant-id" not in argv and argv[:2] not in (
            ("workspaces", "list"),
            ("workspaces", "create"),
        ):
            given += ["--tenant-id", str(self.here.tenant_id)]
        if write:
            given += [
                "--actor-person-id",
                str(self.operator),
                "--approver",
                "owner-chat-20261117",
                "--issue",
                "orch:admin-cli-20261117",
            ]
        if apply:
            given.append("--apply")
        return await tool.execute(self.sessions, self.settings, tool.parse(given))

    async def audits(self) -> int:
        async with self.sessions() as db:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
                or 0
            )

    async def twice(self, *argv: str) -> tuple[Any, Any, Any]:
        """Dry run, apply, then the same again: nothing, one change, a replay."""
        audits = await self.audits()
        dry = await self(*argv)
        assert dry["mode"] == "dry_run" and dry.get("rolled_back") is True, dry
        assert await self.audits() == audits
        done = await self(*argv, apply=True)
        assert done["status"] == "applied" and done["audit"] == "written", done
        assert await self.audits() == audits + 1
        again = await self(*argv, apply=True)
        assert again["status"] == "replayed", again
        assert await self.audits() == audits + 1
        return dry, done, again


async def _cli(here: Any) -> Cli:
    sessions = here.setup.sessions
    async with sessions() as db, db.begin():
        # The world's admin is the workspace's owner here; the operator is a verified person.
        await db.execute(
            update(Membership)
            .where(Membership.person_id == here.setup.state.person_id)
            .values(role="owner")
        )
        await db.execute(
            update(Person)
            .where(Person.id == here.setup.state.person_id)
            .values(email_verified_at=datetime.now(UTC))
        )
    settings = here.setup.settings.model_copy(
        update={"public_learner_tenant_id": uuid4(), "operations_tenant_id": uuid4()}
    )
    return Cli(here, settings, here.setup.state.person_id)


def test_people_and_workspaces(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            cli = await _cli(here)
            seller = str(here.seller.person_id)

            listed = await cli("people", "list", write=False)
            assert listed["mode"] == "read"
            roles = {row["person_id"]: row["role"] for row in listed["people"]}
            assert roles[seller] == "member"
            assert all("***@" in (row["email"] or "***@") for row in listed["people"])

            # Team's "Taking new leads" switch: a seller takes leads until switched off; only
            # the switch changes (the limit stays the workspace's default).
            async with cli.sessions() as db:
                had = await db.get(LeadRep, (here.tenant_id, here.seller.person_id))
                start = had.revision if had else 0
                limit = had.max_open if had else None
            dry, done, _ = await cli.twice(
                "people", "taking-leads", "--person-id", seller, "--taking", "off"
            )
            assert dry["before"] == {"taking": True} and done["after"] == {"taking": False}
            async with cli.sessions() as db:
                rules = await db.get(LeadRep, (here.tenant_id, here.seller.person_id))
                assert rules is not None and rules.available is False
                assert rules.revision == start + 1
                desk = await db.get(LeadDeskSettings, here.tenant_id)
                default = default_cap(desk.config if desk else DEFAULT_SETTINGS)
                assert rules.max_open == (limit if had else default)
            idle = await cli(
                "people",
                "taking-leads",
                "--person-id",
                seller,
                "--taking",
                "off",
                "--command-id",
                str(uuid4()),
                apply=True,
            )
            assert idle["status"] == "already_off" and idle["before"] == {"taking": False}
            _, back, _ = await cli.twice(
                "people", "taking-leads", "--person-id", seller, "--taking", "on"
            )
            assert back["after"] == {"taking": True}
            async with cli.sessions() as db:
                rules = await db.get(LeadRep, (here.tenant_id, here.seller.person_id))
                assert rules is not None and rules.available is True
                assert rules.revision == start + 2

            dry, done, _ = await cli.twice(
                "people", "set-role", "--person-id", seller, "--role", "manager"
            )
            assert dry["before"] == {"role": "member"} and done["after"] == {"role": "manager"}
            shown = await cli("people", "show", "--person-id", seller, write=False)
            assert shown["person"]["role"] == "manager"

            _, renamed, _ = await cli.twice(
                "people", "rename", "--person-id", seller, "--name", " Fictional  Seller Two "
            )
            assert renamed["after"] == {"name": "Fictional Seller Two"}

            await cli.twice("people", "invite", "--email", "new.fictional@example.com")
            async with cli.sessions() as db:
                first = await db.scalar(
                    select(OrganisationInvite).where(
                        OrganisationInvite.email_normalized == "new.fictional@example.com",
                        OrganisationInvite.status == "pending",
                    )
                )
            assert first is not None and first.role == "member"
            _, resent, _ = await cli.twice(
                "people", "resend-invite", "--email", "new.fictional@example.com"
            )
            assert resent["after"]["revoked"] == str(first.id)
            assert resent["after"]["invite_id"] != str(first.id)

            # A verified account joins at once.
            other = await seed(here.setup.engine, role="learner")
            async with cli.sessions() as db, db.begin():
                person = await db.get(Person, other.person_id)
                assert person is not None and person.email
                email = person.email
                person.email_verified_at = datetime.now(UTC)
            _, joined, _ = await cli.twice("people", "invite", "--email", email, "--role", "admin")
            assert joined["after"] == {"role": "admin", "status": "active"}

            await cli.twice("people", "transfer-owner", "--person-id", str(other.person_id))
            _, removed, _ = await cli.twice("people", "remove-member", "--person-id", seller)
            assert removed["after"]["status"] == "inactive"
            with pytest.raises(tool.OrganisationCommandError, match="never removed"):
                await cli("people", "remove-member", "--person-id", str(other.person_id))

            # Workspaces.
            everyone = await cli("workspaces", "list", write=False)
            assert str(here.tenant_id) in {row["tenant_id"] for row in everyone["workspaces"]}
            _, named, _ = await cli.twice("workspaces", "rename", "--name", "Fictional Works")
            async with cli.sessions() as db:
                tenant = await db.get(Tenant, here.tenant_id)
                assert tenant is not None and tenant.name == "Fictional Works"
            assert named["after"] == {"name": "Fictional Works"}

            _, switched, _ = await cli.twice("workspaces", "switches", "--stage", "on")
            assert switched["before"]["stage"] is False and switched["after"]["stage"] is True
            looked = await cli("workspaces", "switches", write=False)
            assert looked["mode"] == "read" and looked["ai_apps_switch"]["stage"] is True

            _, domains, _ = await cli.twice(
                "workspaces", "domains", "--domain", "fictional-works.example", "--auto-join"
            )
            assert domains["after"] == {
                "verified_domains": ["fictional-works.example"],
                "auto_join": True,
            }
            show = await cli("workspaces", "show", write=False)
            assert show["workspace"]["name"] == "Fictional Works"
            assert show["workspace"]["verified_domains"] == ["fictional-works.example"]
            assert show["workspace"]["owner_person_id"] == str(other.person_id)

            _, made, _ = await cli.twice(
                "workspaces",
                "create",
                "--name",
                "Fictional New Works",
                "--owner-person-id",
                str(cli.operator),
            )
            async with cli.sessions() as db:
                owner = await db.get(Membership, (UUID(made["tenant_id"]), cli.operator))
                assert owner is not None and owner.role == "owner"

            # A different change under a used command id is refused.
            with pytest.raises(tool.OrganisationCommandError, match="different intent"):
                await cli(
                    "workspaces",
                    "rename",
                    "--name",
                    "Another Name",
                    "--command-id",
                    made["command_id"],
                )

    run(exercise())


def test_leads(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            cli = await _cli(here)
            seller = str(here.seller.person_id)
            owner = str(cli.operator)
            first = await here.add("Fictional Lead One", "98760 88001")
            second = await here.add("Fictional Lead Two", "98760 88002")

            listed = await cli("leads", "list", write=False)
            assert listed["total"] == 2
            assert {row["lead_id"] for row in listed["leads"]} == {first, second}
            assert all("Fictional" not in row["name"] for row in listed["leads"])
            named = await cli("leads", "list", "--names", write=False)
            assert {row["name"] for row in named["leads"]} == {
                "Fictional Lead One",
                "Fictional Lead Two",
            }

            _, added, _ = await cli.twice(
                "leads",
                "add",
                "--name",
                "Fictional Lead Three",
                "--phone",
                "98760 88003",
                "--owner-person-id",
                owner,
            )
            third = added["lead_id"]
            async with cli.sessions() as db:
                lead = await db.get(Lead, UUID(third))
                assert lead is not None and str(lead.owner_person_id) == owner

            _, given, _ = await cli.twice(
                "leads", "assign", "--lead-id", third, "--to-person-id", seller
            )
            assert given["after"]["changed"] == 1

            later = (datetime.now(UTC) + timedelta(hours=6)).isoformat()
            _, staged, _ = await cli.twice(
                "leads",
                "stage",
                "--lead-id",
                first,
                "--step",
                "interested",
                "--next-action-at",
                later,
            )
            assert staged["after"]["changed"] == 1
            async with cli.sessions() as db:
                lead = await db.get(Lead, UUID(first))
                assert lead is not None and lead.step == "interested"

            # By filter: every lead the seller owns goes to the owner, and back.
            _, moved, _ = await cli.twice(
                "leads", "reassign", "--person-id", seller, "--to-person-id", owner
            )
            assert moved["before"] == {"leads_of_person": 3} and moved["after"]["moved"] == 3
            _, back, _ = await cli.twice(
                "leads",
                "reassign",
                "--person-id",
                owner,
                "--to-person-id",
                seller,
                "--where-side",
                "inbound",
            )
            assert back["after"]["changed"] == 3

            for action, column in (
                ("archive", Lead.archived_at),
                ("restore-archive", Lead.archived_at),
                ("bin", Lead.binned_at),
                ("restore-bin", Lead.binned_at),
            ):
                _, shelved, _ = await cli.twice("leads", action, "--lead-id", second)
                assert shelved["after"]["changed"] == 1, (action, shelved)
                async with cli.sessions() as db:
                    value = await db.scalar(select(column).where(Lead.id == UUID(second)))
                assert (value is None) == action.startswith("restore"), action
            # Nothing left to restore: the change is "unchanged" and audits nothing.
            audits = await cli.audits()
            idle = await cli(
                "leads",
                "restore-bin",
                "--lead-id",
                second,
                "--command-id",
                str(uuid4()),
                apply=True,
            )
            assert idle["status"] == "unchanged" and await cli.audits() == audits

    run(exercise())
