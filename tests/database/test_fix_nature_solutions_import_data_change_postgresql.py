"""The approved correction of the 16 Nov 2026 Nature Solutions import
(scripts/data-changes/fix-nature-solutions-import-20261116.py), on PostgreSQL, with leads of
the same shape: a header row made a lead goes to history, Lost, given to nobody, by nobody's
move; a number written with +1 before an Indian mobile is saved as +91 and an email typed
into the name as the email, through the app's edit, each with a note; a lead whose row holds
neither is left as it is; a number already on another lead is never set twice; a lead that is
not a header row is refused; the dry run leaves nothing; one audit event; a rerun changes
nothing. Made-up people only."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

HERE = Path(__file__).resolve().parents[2] / "scripts/data-changes"


def _load(name: str, file: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


importer = _load("import_leads_file_for_fix", "import-leads-file.py")
fix = _load("fix_nature_solutions_import", "fix-nature-solutions-import-20261116.py")
LABEL = "Meta (fictional sheet)"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_plus_one_mobile() -> None:
    assert fix.plus_one_mobile("p:+19876075002") == "+919876075002"
    assert fix.plus_one_mobile("P:+19876075002") == "+919876075002"
    assert fix.plus_one_mobile("+1 98760 75002") == "+919876075002"
    assert fix.plus_one_mobile("p:+12025550100") is None
    assert fix.plus_one_mobile("89876075") is None
    assert fix.plus_one_mobile("p:+911987607500") is None
    assert fix.plus_one_mobile(None) is None


def test_correction_of_an_import(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
                seller = await db.scalar(
                    select(Person.email).where(Person.id == here.seller.person_id)
                )
            assert admin and seller
            rows = [
                {"Full Name": "Sr.No", "_stage": "interested"},
                {
                    "Full Name": "Fictional Plus",
                    "Phone as written": "p:+19876075002",
                    "Email": "Nil",
                },
                {
                    "Full Name": "fictional.mail@example.co",
                    "Phone as written": "p:+19876075003",
                    "Email": "Nil",
                },
                {"Full Name": "Fictional Hot", "City": "Pune", "_stage": "interested"},
                {"Full Name": "Fictional Twin", "Phone as written": "p:+19876075004"},
                {"Full Name": "Fictional Twin Main", "Phone": "+919876075004"},
                {"Full Name": "Fictional Short", "Phone as written": "89876075"},
            ]
            # The import as it ran before its header-row guard: the same shape as production.
            monkeypatch.setattr(importer, "header_row", lambda record: False)
            made = await importer.execute(
                sessions,
                {
                    "command_id": str(uuid4()),
                    "tenant": str(here.tenant_id)[:8],
                    "seller_email": seller,
                    "approver_email": admin,
                    "actor_email": seller,
                    "issue": "AUT-test",
                    "mapping": {"name": "Full Name", "phone": "Phone", "email": "Email"},
                    "batches": [{"label": LABEL, "rows": rows}],
                },
                mode="apply",
                now=datetime.now(UTC),
            )
            assert made["counts"]["created"] == 7
            async with sessions() as db:
                by_name = {
                    lead.name: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
            header = by_name["Sr.No"]
            assert header.stage == "interested" and header.phone is None
            ids = {name: str(lead.id)[:8] for name, lead in by_name.items()}
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "header_rows": [ids["Sr.No"]],
                "contacts": [
                    ids[name]
                    for name in (
                        "Fictional Plus",
                        "fictional.mail@example.co",
                        "Fictional Hot",
                        "Fictional Twin",
                        "Fictional Short",
                    )
                ],
            }
            now = datetime.now(UTC)
            with pytest.raises(SystemExit, match="not_a_header_row"):
                await fix.execute(
                    sessions,
                    {**spec, "header_rows": [ids["Fictional Hot"]]},
                    mode="dry-run",
                    now=now,
                )

            dry = await fix.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["counts"] == {
                "header_closed": 1,
                "phone_set": 2,
                "email_set": 1,
                "set": 2,
                "sheet_has_none": 2,
                "phone_on_another_lead": 1,
                "left_for_merge": 1,
            }
            assert dry["before"]["live_header_rows"] == 1
            assert dry["after"]["live_header_rows"] == 0
            async with sessions() as db:
                still = await db.get(Lead, header.id)
                assert still is not None and still.stage == "interested"

            done = await fix.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == dry["counts"]
            async with sessions() as db:
                leads = {
                    lead.name: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                closed = leads["Sr.No"]
                assert closed.pipeline == "history" and closed.stage == "lost"
                assert closed.owner_person_id is None
                assert closed.outcome_reason in ("not_a_lead", "other")
                moves = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.lead_id == closed.id, LeadEvent.kind == "stage"
                        )
                    )
                ).all()
                last = max(moves, key=lambda event: event.created_at)
                assert last.actor_person_id is None
                assert last.data["reason_note"] == fix.HEADER_WORDS
                plus = leads["Fictional Plus"]
                assert plus.phone == "+919876075002" and plus.email is None
                assert plus.payload["Phone as written"] == "P:+19876075002"
                mailed = leads["fictional.mail@example.co"]
                assert mailed.email == "fictional.mail@example.co"
                assert mailed.phone == "+919876075003"
                assert leads["Fictional Hot"].phone is None
                assert leads["Fictional Hot"].stage == "interested"
                assert leads["Fictional Twin"].phone is None
                assert leads["Fictional Short"].phone is None
                notes = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == here.tenant_id,
                            LeadEvent.kind == "note",
                            LeadEvent.lead_id.in_([plus.id, mailed.id]),
                        )
                    )
                ).all()
                assert len(notes) == 2
                audits = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.action == fix.ACTION))
                ).all()
                assert len(audits) == 1
                assert audits[0].payload["approver"] == "Fictional owner, in chat"

            again = await fix.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False
            assert again["counts"] == {
                "header_already_closed": 1,
                "already_has_contact": 2,
                "sheet_has_none": 2,
                "phone_on_another_lead": 1,
                "left_for_merge": 1,
            }
            async with sessions() as db:
                count = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == fix.ACTION)
                )
            assert count == 1
            read = await fix.execute(sessions, spec, mode="read", now=now)
            assert read["after"]["live_header_rows"] == 0

    run(exercise())
