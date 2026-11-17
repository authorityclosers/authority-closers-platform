"""The approved data change that imports a workbook's leads for one seller
(scripts/data-changes/import-leads-file.py), on PostgreSQL: the dry run rehearses and leaves
nothing; the apply gives the new leads to the seller in the pipeline named, with the form's
answers readable and its time kept; a known phone is a repeat and a known email is left out;
the email typo is pointed out; a second tab goes in date order, so a phone in both tabs is one
lead and its later row a repeat; numbers stored as numbers, a typed date and a city's spelling
are read; one audit event; a rerun adds nothing. Made-up people only."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import BASE, ROOT, WRITE, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/import-leads-file.py"
LOADER = importlib.util.spec_from_file_location("import_leads_file", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)

LABEL = "File: Fictional form leads"
SECOND = "File: Fictional form leads / owners"


def row(phone: str, name: str, email: str) -> dict[str, str]:
    return {
        "created_time": "2026-05-19T14:46:53.000Z",
        "what_do_you_currently_do?": "business_owner_/_startup",
        "what_is_your_current_monthly_income?": "₹15,000_–_₹30,000",
        "phone_number": phone,
        "full_name": name,
        "email": email,
        "lead_status": "",
    }


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_dry_run_apply_dedupe_and_rerun(postgres_harness: Any, tmp_path: Path) -> None:
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
            await here.add("Fictional Already", "98760 73001")
            here.as_admin()
            known = await here.client.post(
                f"{BASE}/leads",
                json={
                    "command_id": str(uuid4()),
                    "name": "Fictional Mailed",
                    "email": "known@example.com",
                },
                headers=WRITE,
            )
            assert known.status_code == 201, known.text
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "seller_email": seller,
                "approver_email": admin,
                "issue": "AUT-test",
                "pipeline": "main",
                "label": LABEL,
                "mapping": {
                    "name": "full_name",
                    "phone": "phone_number",
                    "email": "email",
                    "city": "city",
                },
                "batches": [
                    {
                        "label": LABEL,
                        "pipeline": "main",
                        "rows": [
                            row("919876073001", "Fictional Again", "again@example.com"),
                            row("919876073002", "Fictional New", "new@example.com"),
                            row("919876073003", "Fictional Mailed Again", "known@example.com"),
                            row("919876073004", "Fictional Typo", "typo@gamil.com"),
                        ],
                    },
                    {
                        "label": SECOND,
                        "pipeline": "main",
                        "add": {"Lead type": "Business owner"},
                        "rows": [
                            # Typed into the sheet: an Excel date number (1 Sep 2026); the
                            # phone a number without its code; the city as written.
                            {
                                **row("0", "Fictional Owner", "owner@example.com"),
                                "created_time": 46266.0,
                                "phone_number": 9876073005.0,
                                "city": "pune Maharashtra",
                                "what_would_you_like_to_improve?": (
                                    "reduce_wasted_leads,\xa0scale_my_sales_process"
                                ),
                            },
                            # Already in the first tab (May): a repeat of that lead.
                            {
                                **row("919876073002", "Fictional New", "new@example.com"),
                                "created_time": "2026-09-02T10:00:00.000Z",
                            },
                        ],
                    },
                ],
            }
            now = datetime.now(UTC)

            async def labelled() -> list[Lead]:
                async with sessions() as db:
                    return list(
                        (
                            await db.scalars(
                                select(Lead).where(
                                    Lead.tenant_id == here.tenant_id, Lead.source_label == LABEL
                                )
                            )
                        ).all()
                    )

            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["counts"] == {"repeat": 2, "created": 3, "repeat_by_email": 1}
            first, second = dry["batches"]
            assert first["repeat_by_email"] == [3] and first["email_hint"] == [4]
            assert second["counts"] == {"created": 1, "repeat": 1}
            assert second["date_typed"] == [1]
            assert await labelled() == []

            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == dry["counts"]
            async with sessions() as db:
                owner = await db.scalar(
                    select(Lead).where(
                        Lead.tenant_id == here.tenant_id, Lead.phone == "+919876073005"
                    )
                )
            assert owner is not None and owner.source_label == SECOND
            assert owner.city == "Pune" and owner.payload["City as written"] == "pune Maharashtra"
            assert owner.payload["Lead type"] == "Business owner"
            assert (
                owner.payload["What would you like to improve?"]
                == "Reduce wasted leads, scale my sales process"
            )
            assert owner.payload["Received on the form"] == "1 Sep 2026"
            assert owner.payload["Received date typed into the sheet"] == "yes"
            leads = await labelled()
            assert len(leads) == 2
            assert {lead.owner_person_id for lead in leads} == {here.seller.person_id}
            assert {lead.stage for lead in leads} == {"new"}
            fresh = next(lead for lead in leads if lead.phone == "+919876073002")
            assert fresh.payload["What do you currently do?"] == "Business owner / startup"
            assert fresh.payload["What is your current monthly income?"] == "₹15,000 – ₹30,000"
            assert fresh.payload["Received on the form"] == "19 May 2026, 20:16 IST"
            # The later row from the second tab is a repeat of this lead, not a second one.
            assert fresh.repeats == 1
            assert "lead_status" not in fresh.payload
            async with sessions() as db:
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
            assert audits == 1

            again = await tool.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False
            assert "created" not in again["counts"] and "repeat" not in again["counts"]
            assert again["counts"]["repeat_by_email"] == 1
            assert len(await labelled()) == 2
            read = await tool.execute(sessions, spec, mode="read", now=now)
            assert read["after"][LABEL]["leads"] == 2 and read["after"][SECOND]["leads"] == 1

    run(exercise())


HISTORY_LABEL = "File: Fictional sheet / history"


def test_history_side_stages_and_dated_notes(postgres_harness: Any, tmp_path: Path) -> None:
    """A batch kept as history goes to nobody and stays out of the work lists, at the stage
    the sheet gives it (Lost reads "Imported", nobody's move); a live row may name its own
    stage; a row's dated remarks become notes on that day, on a repeat too; the history names
    the actor; an unknown stage refuses the whole run; a rerun adds no note twice."""

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
            dated = {
                "text": "Remark of 11 Aug 2025: called, will think",
                "at": "2025-08-11T12:00:00+05:30",
            }
            spec: dict[str, Any] = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "seller_email": seller,
                "approver_email": admin,
                "actor_email": seller,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "mapping": {"name": "full_name", "phone": "phone_number", "email": "email"},
                "batches": [
                    {
                        "label": LABEL,
                        "rows": [
                            {
                                **row("919876074001", "Fictional Live", "live@example.com"),
                                "_notes": [dated, {"text": "Status in the sheet: Hot"}],
                            },
                            {
                                **row("919876074002", "Fictional Hot", "hot@example.com"),
                                "_stage": "interested",
                            },
                        ],
                    },
                    {
                        "label": HISTORY_LABEL,
                        "side": "history",
                        "stage": "lost",
                        "rows": [
                            {
                                **row("919876074003", "Fictional Old", "old@example.com"),
                                "_notes": [dated],
                            },
                            {
                                **row("919876074004", "Fictional Customer", "cust@example.com"),
                                "_stage": "won",
                            },
                            # The same number as a live lead: a repeat, its note still kept.
                            {
                                **row("919876074001", "Fictional Live", "live@example.com"),
                                "created_time": "2026-06-01T10:00:00.000Z",
                                "_notes": [{"text": "Also in the old sheet"}],
                            },
                        ],
                    },
                ],
            }
            now = datetime.now(UTC)
            bad = {**spec, "batches": [{**spec["batches"][0], "stage": "no_such_stage"}]}
            with pytest.raises(SystemExit, match="stage_not_on_list"):
                await tool.execute(sessions, bad, mode="dry-run", now=now)

            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["counts"] == {"created": 4, "repeat": 1, "notes": 4, "staged": 3}
            assert dry["after"][HISTORY_LABEL]["by_side"] == {"history": 2}
            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == dry["counts"]
            async with sessions() as db:
                leads = {
                    lead.phone: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                live, hot = leads["+919876074001"], leads["+919876074002"]
                old, customer = leads["+919876074003"], leads["+919876074004"]
                assert live.pipeline == "live" and live.stage == "new"
                assert live.owner_person_id == here.seller.person_id and live.repeats == 1
                assert hot.stage == "interested" and hot.owner_person_id == here.seller.person_id
                assert old.pipeline == "history" and old.owner_person_id is None
                assert old.stage == "lost" and old.outcome_reason == "imported"
                assert customer.pipeline == "history" and customer.stage == "won"
                assert "_notes" not in live.payload and "_stage" not in hot.payload
                notes = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "note"
                        )
                    )
                ).all()
                assert len(notes) == 4
                assert {n.actor_person_id for n in notes} == {here.seller.person_id}
                on_day = [n for n in notes if n.lead_id == old.id]
                assert on_day[0].created_at.date().isoformat() == "2025-08-11"
                assert sum(1 for n in notes if n.lead_id == live.id) == 3
                stages = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.lead_id == old.id, LeadEvent.kind == "stage"
                        )
                    )
                ).all()
                assert stages and all(s.actor_person_id is None for s in stages)
                audit = await db.scalar(
                    select(AuditEvent).where(
                        AuditEvent.action == tool.ACTION, AuditEvent.tenant_id == here.tenant_id
                    )
                )
                assert audit is not None and audit.payload["approver"] == "Fictional owner, in chat"
            again = await tool.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False and "notes" not in again["counts"]

    run(exercise())


def test_header_rows_left_out_and_a_mobile_no_column_read(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """A tab whose header sits under a title row: a header row is the sheet's own, never a
    lead ("Sr.No", Nature Solutions, 16 Nov 2026), counted and left out. A tab that keeps its
    phones under "Mobile No " has them read even when the mapping names another column."""

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
            spec: dict[str, Any] = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "seller_email": seller,
                "approver_email": admin,
                "issue": "AUT-test",
                "mapping": {"name": "Customer Name ", "phone": "Phone"},
                "batches": [
                    {
                        "label": LABEL,
                        "rows": [
                            {"Customer Name ": "Sr.No"},
                            {
                                "Sr.No ": "Sr.No ",
                                "Customer Name ": "Customer Name ",
                                "Mobile No ": "Mobile No ",
                                "City ": "City ",
                            },
                            {"Customer Name ": "Fictional Hot", "Mobile No ": "98760 75101"},
                        ],
                    }
                ],
            }
            done = await tool.execute(sessions, spec, mode="apply", now=datetime.now(UTC))
            assert done["counts"] == {"header_row": 2, "created": 1}
            assert done["batches"][0]["header_row"] == [1, 2]
            async with sessions() as db:
                leads = (
                    await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                ).all()
            assert [(lead.name, lead.phone) for lead in leads] == [
                ("Fictional Hot", "+919876075101")
            ]

    run(exercise())


NEW_LABEL = "File: Fictional sheet / new campaign"
MERGE_LABEL = "File: Fictional sheet / already here"


def test_no_owner_batch_and_merge_into_leads_already_here(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Wise Life and iSolar, 17 Nov 2026: a sheet that names no seller on the team. With no
    seller at all, a no-owner batch's new leads wait in the pool at the sheet's stage, with
    their form time as received; a merge batch touches only leads already here, as they are
    (no repeat, same owner), adds the sheet's notes and sets its stage only on a lead still
    New; a worked lead keeps its stage; a row with no lead here is left out; a rerun adds
    nothing and writes nothing twice."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            fresh_id = await here.add("Fictional Meta", "98760 76001")
            worked_id = await here.add("Fictional Worked", "98760 76002")
            async with sessions() as db:
                worked = await db.get(Lead, UUID(worked_id))
                assert worked is not None
                worked.stage = "interested"
                await db.commit()
            spec: dict[str, Any] = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "mapping": {"name": "full_name", "phone": "phone_number", "email": "email"},
                "batches": [
                    {
                        "label": NEW_LABEL,
                        "assign": "none",
                        "rows": [
                            {
                                **row("919876076003", "Fictional Pool", "pool@example.com"),
                                "created_time": "2026-11-10T09:00:00+05:30",
                                "_stage": "not_connected",
                            }
                        ],
                    },
                    {
                        "label": MERGE_LABEL,
                        "merge": "existing",
                        "rows": [
                            {
                                **row("919876076001", "Fictional Meta", "meta@example.com"),
                                "_stage": "interested",
                                "_notes": [{"text": "From the sheet: Connected"}],
                            },
                            {
                                **row("919876076002", "Fictional Worked", "w@example.com"),
                                "_stage": "interested",
                                "_notes": [{"text": "From the sheet: Hot"}],
                            },
                            row("919876076009", "Fictional Elsewhere", "else@example.com"),
                        ],
                    },
                ],
            }
            bad = {**spec, "batches": [{**spec["batches"][0], "assign": "everyone"}]}
            with pytest.raises(SystemExit, match="assign_or_merge_not_known"):
                await tool.execute(sessions, bad, mode="dry-run", now=datetime.now(UTC))
            now = datetime.now(UTC)
            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["counts"] == {
                "created": 1,
                "staged": 2,
                "merged": 2,
                "not_here": 1,
                "stage_kept": 1,
                "notes": 2,
            }
            assert dry["batches"][1]["not_here"] == [3]
            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == dry["counts"] and done["audited"] is True
            async with sessions() as db:
                leads = {
                    lead.phone: lead
                    for lead in (
                        await db.scalars(select(Lead).where(Lead.tenant_id == here.tenant_id))
                    ).all()
                }
                assert "+919876076009" not in leads
                pool = leads["+919876076003"]
                assert pool.owner_person_id is None and pool.stage == "not_connected"
                assert pool.pipeline == "live" and pool.source_label == NEW_LABEL
                assert pool.received_at is not None
                assert pool.received_at.isoformat().startswith("2026-11-10T03:30")
                meta, worked = leads["+919876076001"], leads["+919876076002"]
                assert str(meta.id) == fresh_id and meta.stage == "interested"
                assert meta.owner_person_id == here.seller.person_id and meta.repeats == 0
                assert meta.source_label != MERGE_LABEL
                assert worked.stage == "interested" and worked.repeats == 0
                notes = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "note"
                        )
                    )
                ).all()
                assert sorted(str(n.lead_id) for n in notes) == sorted([fresh_id, worked_id])
                repeats = await db.scalar(
                    select(func.count())
                    .select_from(LeadEvent)
                    .where(LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "repeat")
                )
                assert repeats == 0
            again = await tool.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False
            assert again["counts"]["notes_before"] == 2 and "notes" not in again["counts"]
            assert "staged" not in again["counts"]

    run(exercise())


def test_a_merge_batch_adds_notes_and_stage_to_a_row_imported_before(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """A row a first file brought in as a new lead comes back in a merge batch with its stage
    and notes (they aren't part of the row's source reference, so the lead is "known"): it
    is merged like any lead already here, its notes and stage go in once, and a rerun adds
    nothing (PR review, 17 Nov 2026)."""

    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            base: dict[str, Any] = {
                "tenant": str(here.tenant_id)[:8],
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "mapping": {"name": "full_name", "phone": "phone_number", "email": "email"},
            }
            first = {
                **base,
                "command_id": str(uuid4()),
                "batches": [
                    {
                        "label": NEW_LABEL,
                        "assign": "none",
                        "rows": [row("919876076101", "Fictional Known", "known@example.com")],
                    }
                ],
            }
            now = datetime.now(UTC)
            made = await tool.execute(sessions, first, mode="apply", now=now)
            assert made["counts"]["created"] == 1
            merge = {
                **base,
                "command_id": str(uuid4()),
                "batches": [
                    {
                        "label": MERGE_LABEL,
                        "merge": "existing",
                        "rows": [
                            {
                                **row("919876076101", "Fictional Known", "known@example.com"),
                                "_stage": "not_connected",
                                "_notes": [{"text": "From the sheet: call after 6"}],
                            }
                        ],
                    }
                ],
            }
            done = await tool.execute(sessions, merge, mode="apply", now=now)
            assert done["counts"]["merged"] == 1 and "known" not in done["counts"]
            assert done["counts"]["notes"] == 1 and done["counts"]["staged"] == 1
            async with sessions() as db:
                lead = await db.scalar(
                    select(Lead).where(
                        Lead.tenant_id == here.tenant_id, Lead.phone == "+919876076101"
                    )
                )
                assert lead is not None and lead.stage == "not_connected"
                notes = (
                    await db.scalars(
                        select(LeadEvent).where(
                            LeadEvent.lead_id == lead.id, LeadEvent.kind == "note"
                        )
                    )
                ).all()
                assert [note.data["note"] for note in notes] == ["From the sheet: call after 6"]
            again = await tool.execute(sessions, merge, mode="apply", now=now)
            assert again["audited"] is False
            assert again["counts"]["notes_before"] == 1 and "notes" not in again["counts"]

    run(exercise())
