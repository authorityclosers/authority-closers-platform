"""The approved data change that cleans a sheet import's notes down to the seller's words
(scripts/data-changes/clean-import-notes.py), on PostgreSQL: the dry run rehearses and leaves
nothing; the apply supersedes every importer-labelled note through the app's undo marker (the
lead page shows the seller's words, dated by the day they name, and no label), hides a
"From the sheet" note whose values the lead already holds and an "Also in" note, keeps a
person's own note and the lead's revision and "last updated"; one audit event; a rerun changes
nothing. Made-up leads only (Shivam Patil's review of Wise Life and iSolar, 17 Nov 2026, C1)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/clean-import-notes.py"
LOADER = importlib.util.spec_from_file_location("clean_import_notes", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)

IMPORTED = datetime(2026, 11, 16, 19, 38, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_named_day_reads_the_sellers_date() -> None:
    assert tool.named_day("didn't answer 17 sep", before=IMPORTED) == datetime(
        2026, 9, 17, 6, 30, tzinfo=UTC
    )
    assert tool.named_day("details sent Nov16-Dheeraj sir", before=IMPORTED).day == 16
    # The latest day named; never one after the note.
    assert tool.named_day("quote 3kwh 20 oct, again 2 nov", before=IMPORTED).month == 11
    assert tool.named_day("call on 30 nov", before=IMPORTED).year == 2025
    assert tool.named_day("3 kw ongrid, 5 market", before=IMPORTED) is None


def test_import_notes_keep_the_sellers_words(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            held = await here.add("Fictional Held", "98760 78001")
            merged = await here.add("Fictional Merged", "98760 78002")
            notes = {
                held: [
                    "Call notes in the sheet (Camp tab): didn't answer 17 sep",
                    "From the sheet (Camp tab): Pipeline Stage: Connected · Quoted Amount: 90000",
                    "Also in the Book sheet's Old tab (the same details)",
                    "Remark in the EPC outbound sheet: details shared 7 nov",
                ],
                merged: [
                    "From the sheet (Nov tab): Call Outcome: Busy · Seller in the sheet:"
                    " Fictional (not a member of this workspace)",
                    "Call status in the EPC outbound sheet: NOT ANSWERED",
                ],
            }
            async with sessions() as db:
                lead = await db.get(Lead, UUID(held))
                assert lead is not None
                lead.payload = {
                    **(lead.payload or {}),
                    "Pipeline Stage (sheet)": "Connected",
                    "Quoted Amount (₹, sheet)": "90000",
                }
                for lead_id, texts in notes.items():
                    for place, words in enumerate(texts):
                        db.add(
                            LeadEvent(
                                id=uuid4(),
                                tenant_id=here.tenant_id,
                                lead_id=UUID(lead_id),
                                kind="note",
                                actor_person_id=here.setup.state.person_id,
                                command_id=uuid4(),
                                data={"note": words, "source": "import"},
                                created_at=IMPORTED + timedelta(microseconds=place),
                            )
                        )
                # A person's own note, also under a label-like start: never touched.
                db.add(
                    LeadEvent(
                        id=uuid4(),
                        tenant_id=here.tenant_id,
                        lead_id=UUID(held),
                        kind="note",
                        actor_person_id=here.setup.state.person_id,
                        command_id=uuid4(),
                        data={"note": "Call notes in the sheet (mine): keep"},
                        created_at=IMPORTED,
                    )
                )
                await db.commit()
            before = await here.stored(held)
            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
                "examples": 3,
            }
            now = datetime.now(UTC)
            read = await tool.execute(sessions, spec, mode="read", now=now)
            assert read["before"]["imported_notes_showing"] == 6
            dry = await tool.execute(sessions, spec, mode="dry-run", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back" and dry["superseded"] == 6
            assert dry["counts"] == {
                "call_notes:words_kept": 1,
                "call_notes:dated_by_words": 1,
                "from_sheet:hidden": 1,
                "also_in:hidden": 1,
                "epc_remark:words_kept": 1,
                "from_sheet:words_kept": 1,
                "epc_status:words_kept": 1,
            }
            assert dry["after"]["importer_labels_showing"] == 0
            assert len(dry["examples"]) == 3
            assert "<e-mail>" not in str(dry["examples"])
            async with sessions() as db:
                markers = await db.scalar(
                    select(func.count())
                    .select_from(LeadEvent)
                    .where(LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "edited")
                )
            assert markers == 0

            done = await tool.execute(sessions, spec, mode="apply", now=now)
            assert done["counts"] == dry["counts"] and done["audited"] is True

            here.as_admin()
            shown = {
                lead_id: [
                    (e["note"], e["at"][:10])
                    for e in (await here.detail(lead_id))["events"]
                    if e["kind"] == "note"
                ]
                for lead_id in (held, merged)
            }
            assert sorted(shown[held]) == sorted(
                [
                    ("didn't answer 17 sep", "2026-09-17"),
                    ("details shared 7 nov", "2026-11-16"),
                    ("Call notes in the sheet (mine): keep", "2026-11-16"),
                ]
            )
            assert sorted(shown[merged]) == sorted(
                [
                    ("Call Outcome: Busy · Seller in the sheet: Fictional", "2026-11-16"),
                    ("NOT ANSWERED", "2026-11-16"),
                ]
            )
            after = await here.stored(held)
            assert after.revision == before.revision and after.updated_at == before.updated_at
            async with sessions() as db:
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
                assert audits == 1
                kept = await db.scalar(
                    select(func.count())
                    .select_from(LeadEvent)
                    .where(LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "note")
                )
                # Nothing deleted: 7 notes before, 4 new ones beside them.
                assert kept == 11

            again = await tool.execute(sessions, spec, mode="apply", now=now)
            assert again["audited"] is False and again["superseded"] == 0
            last = await tool.execute(sessions, spec, mode="read", now=now)
            assert last["before"]["by_kind"] == {"keep": 4}

    run(exercise())
