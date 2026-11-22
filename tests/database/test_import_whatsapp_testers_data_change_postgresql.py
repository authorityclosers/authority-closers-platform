"""The approved data change that brings the testers in as leads with what we sent them
(scripts/data-changes/import-whatsapp-testers.py), on PostgreSQL: the input is checked before
anything is read; production refuses --apply without a snapshot; the dry run (also through the
command line, from a file) rehearses and leaves nothing; the apply makes one no-owner lead per
new person (a person with no name goes in by number), leaves a number already a lead as it is
but tags it and adds its messages, puts the tags on, and writes each message as a WhatsApp line
at its own time; one audit event; a rerun with another command id adds nothing. Made-up people
only."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadTag, LeadTagLink
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_os_acceptance_postgresql import ROOT, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/import-whatsapp-testers.py"
LOADER = importlib.util.spec_from_file_location("import_whatsapp_testers", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)

LABEL = "Testers: fictional group"


def touch(at: str, message_id: str, where: str = "dm", kind: str = "video") -> dict[str, str]:
    return {
        "at": at,
        "message_id": message_id,
        "where": where,
        "kind": kind,
        "summary": "Fictional welcome video",
    }


def spec_for(tenant: UUID, approver: str) -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "tenant": str(tenant)[:8],
        "approver_email": approver,
        "approver": "Fictional owner, in chat",
        "issue": "AUT-test",
        "label": LABEL,
        "people": [
            {
                # Already a lead here (added by hand): kept as it is, tagged, messages added.
                "key": "+919876075001",
                "name": "Fictional Already Again",
                "phone": "+919876075001",
                "tags": ["Alpha tester", "WhatsApp: Insiders group"],
                "touches": [touch("2026-11-21T20:56:43Z", "FICT-A1")],
            },
            {
                "key": "+919876075002",
                "name": "Fictional Tester",
                "phone": "+919876075002",
                "email": "tester@example.com",
                "other_phones": ["+919876075009"],
                "referred_by": "Fictional Partner",
                "tags": ["Alpha tester", "Referred by Dipak", "Buyer intent", "Tester: active"],
                "touches": [
                    touch("2026-11-22T07:28:50Z", "FICT-B2", kind="text"),
                    touch("2026-11-22T07:27:05Z", "FICT-B1"),
                    touch("2026-11-22T11:42:53Z", "FICT-G1", where="group"),
                ],
            },
            {
                # No name known: the lead is its number.
                "key": "+919876075003",
                "phone": "+919876075003",
                "tags": ["Alpha tester", "Tester: invited"],
                "touches": [touch("2026-11-22T11:42:53Z", "FICT-G1", where="group")],
            },
            {
                # Email only, no messages.
                "key": "nobody@example.com",
                "email": "nobody@example.com",
                "tags": ["Alpha tester", "Client team: EA", "Tester: has access"],
            },
        ],
    }


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_checks_refuse_before_reading() -> None:
    spec = spec_for(uuid4(), "a@example.com")
    with pytest.raises(SystemExit, match="production_needs_snapshot_sha256"):
        tool.guard("production", "apply", None)
    tool.guard("production", "apply", "a" * 64)
    tool.guard("production", "dry-run", None)
    bad = json.loads(json.dumps(spec))
    bad["people"][1]["touches"][0]["at"] = "2026-11-22T07:28:50"
    with pytest.raises(SystemExit, match="touch_time"):
        tool.check(bad)
    bad = json.loads(json.dumps(spec))
    bad["people"][2]["key"] = bad["people"][1]["key"]
    with pytest.raises(SystemExit, match="key_twice"):
        tool.check(bad)
    bad = json.loads(json.dumps(spec))
    bad["people"][1]["touches"][0]["summary"] = "x" * 81
    with pytest.raises(SystemExit, match="touch_fields"):
        tool.check(bad)
    assert tool.parse(["in.json", "--apply", "--production-snapshot-sha256", "A" * 64]) == (
        "in.json",
        "apply",
        "a" * 64,
    )


def test_dry_run_apply_dedupe_and_rerun(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        async with world(postgres_harness, tmp_path) as here:
            sessions = here.setup.sessions
            async with sessions() as db:
                admin = await db.scalar(
                    select(Person.email).where(Person.id == here.setup.state.person_id)
                )
            assert admin
            already = await here.add("Fictional Already", "98760 75001")
            before = await here.stored(already)
            spec = spec_for(here.tenant_id, admin)
            now = datetime.now(UTC)

            async def ours() -> list[Lead]:
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

            with pytest.raises(SystemExit, match="production_needs_snapshot_sha256"):
                await tool.execute(sessions, spec, mode="apply", now=now, environment="production")

            dry = await tool.execute(sessions, spec, mode="dry-run", now=now, environment="test")
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["counts"]["created"] == 3 and dry["counts"]["repeat"] == 1
            assert dry["counts"]["touches"] == 5
            assert await ours() == []

            # The command line: the input from a file, a dry run against this database.
            path = tmp_path / "testers.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            url = postgres_harness.url.set(drivername="postgresql+psycopg")
            monkeypatch.setattr(
                tool,
                "get_settings",
                lambda: SimpleNamespace(
                    database_url=url.render_as_string(hide_password=False), environment="test"
                ),
            )
            assert await tool.main([str(path)]) == 0
            assert await ours() == []

            done = await tool.execute(sessions, spec, mode="apply", now=now, environment="test")
            assert done["counts"] == dry["counts"] and done["audited"] is True
            leads = {lead.phone or lead.email: lead for lead in await ours()}
            assert set(leads) == {"+919876075002", "+919876075003", "nobody@example.com"}
            fresh = leads["+919876075002"]
            assert fresh.name == "Fictional Tester" and fresh.owner_person_id is None
            assert fresh.source == "manual" and fresh.source_ref == "tester:+919876075002"
            assert fresh.payload["referred_by"] == "Fictional Partner"
            assert fresh.payload["Other phone"] == "+919876075009"
            assert fresh.received_at == datetime(2026, 11, 22, 7, 27, 5, tzinfo=UTC)
            assert fresh.first_contact_at == fresh.received_at
            # No name: the number is what the lead shows.
            assert "75003" in leads["+919876075003"].name.replace(" ", "")
            kept = await here.stored(already)
            assert kept.name == before.name and kept.owner_person_id == before.owner_person_id
            assert kept.repeats == before.repeats and kept.source_label != LABEL
            async with sessions() as db:
                lines = (
                    await db.scalars(
                        select(LeadEvent)
                        .where(LeadEvent.tenant_id == here.tenant_id, LeadEvent.kind == "message")
                        .order_by(LeadEvent.created_at)
                    )
                ).all()
                assert len(lines) == 5
                assert {line.data["channel"] for line in lines} == {"whatsapp"}
                assert all(line.actor_person_id is None for line in lines)
                mine = [line for line in lines if line.lead_id == fresh.id]
                assert [line.data["wa_message_id"] for line in mine] == [
                    "FICT-B1",
                    "FICT-B2",
                    "FICT-G1",
                ]
                assert mine[0].created_at.replace(microsecond=0) == datetime(
                    2026, 11, 22, 7, 27, 5, tzinfo=UTC
                )
                assert any(line.lead_id == kept.id for line in lines)
                names = {
                    lead_id: name
                    for lead_id, name in (
                        await db.execute(
                            select(LeadTagLink.lead_id, LeadTag.name).join(
                                LeadTag, LeadTag.id == LeadTagLink.tag_id
                            )
                        )
                    ).all()
                    if lead_id == fresh.id
                }
                tagged = (
                    await db.scalars(
                        select(LeadTag.name)
                        .join(LeadTagLink, LeadTag.id == LeadTagLink.tag_id)
                        .where(LeadTagLink.lead_id == fresh.id)
                    )
                ).all()
                assert names and set(tagged) == {
                    "Alpha tester",
                    "Referred by Dipak",
                    "Buyer intent",
                    "Tester: active",
                }
                on_kept = (
                    await db.scalars(
                        select(LeadTag.name)
                        .join(LeadTagLink, LeadTag.id == LeadTagLink.tag_id)
                        .where(LeadTagLink.lead_id == kept.id)
                    )
                ).all()
                assert set(on_kept) == {"Alpha tester", "WhatsApp: Insiders group"}
                one_each = await db.scalar(
                    select(func.count())
                    .select_from(LeadTag)
                    .where(LeadTag.tenant_id == here.tenant_id, LeadTag.name == "Alpha tester")
                )
                assert one_each == 1
                audits = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == tool.ACTION)
                )
                assert audits == 1

            # A rerun, even with a new command id, adds nothing.
            again = await tool.execute(
                sessions,
                {**spec, "command_id": str(uuid4())},
                mode="apply",
                now=now,
                environment="test",
            )
            assert again["audited"] is False
            assert again["counts"].get("created", 0) == 0
            assert again["counts"]["touches_before"] == 5
            assert again["counts"].get("tags_added", 0) == 0
            assert len(await ours()) == 3
            read = await tool.execute(sessions, spec, mode="read", now=now, environment="test")
            assert read["after"]["touch_lines"] == 5 and read["after"]["leads_made_here"] == 3

    run(exercise())


def test_runs_as_a_script_without_arguments() -> None:
    with pytest.raises(SystemExit, match="usage"):
        asyncio.run(tool.main([]))
