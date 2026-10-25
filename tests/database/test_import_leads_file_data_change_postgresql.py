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
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead
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
