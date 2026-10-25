"""The bug-status data change (scripts/data-changes/bug-status.py) on PostgreSQL:
- the dry run makes the change and rolls it back, with no event and no audit left;
- the apply sets each report's status through Admin's own BugReportStore.change, by the
  approver as staff, with the note; one audit event per report naming the approver, the issue
  and the actor "Claude (orchestrator)";
- a rerun changes nothing and is not audited;
- an unknown number, or an approver who is not an operations owner or admin, changes nothing;
- --read prints statuses only, never a report's words.
Made-up people only."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.bug_reports.models import BugReportEvent
from ac_platform.bug_reports.store import BugReportStore
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership
from tests.database.test_bug_reports_postgresql import _new
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/bug-status.py"
LOADER = importlib.util.spec_from_file_location("bug_status", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_rehearse_apply_rerun_and_refusals(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            operations = setup.state.tenant_id
            approver_email = f"approver-{uuid4().hex[:8]}@example.test"
            async with setup.sessions() as db, db.begin():
                approver = Person(
                    id=uuid4(),
                    email=approver_email,
                    display_name="Fictional Approver",
                    email_verified_at=datetime.now(UTC),
                )
                db.add(approver)
                await db.flush()
                db.add(Membership(tenant_id=operations, person_id=approver.id, role="admin"))
                store = BugReportStore(db)
                rows = [
                    await store.create(
                        _new(setup.state.person_id, setup.state.tenant_id),
                        bug_id=uuid4(),
                        now=setup.state.now,
                    )
                    for _ in range(2)
                ]
            numbers = [row.number for row in rows]
            spec = tool.spec_from(
                json.dumps(
                    {
                        "numbers": numbers,
                        "status": "fixed",
                        "note": "Fixed in v0.92.",
                        "approver_email": approver_email.upper(),
                        "issue": "demo P0",
                    }
                ),
                "dry-run",
            )

            async def go(mode: str, which: dict[str, Any] = spec) -> dict[str, Any]:
                return await tool.execute(
                    setup.sessions,
                    which,
                    mode=mode,
                    now=datetime.now(UTC),
                    operations_tenant_id=operations,
                )

            async def audits() -> list[AuditEvent]:
                async with setup.sessions() as db:
                    return list(
                        (
                            await db.scalars(
                                select(AuditEvent).where(AuditEvent.action == "bug_report.changed")
                            )
                        ).all()
                    )

            rehearsed = await go("dry-run")
            assert rehearsed["status"] == "rehearsed_and_rolled_back"
            assert rehearsed["changed"] == numbers
            assert set(rehearsed["after"].values()) == {"fixed"}
            assert "Leads list" not in json.dumps(rehearsed)
            async with setup.sessions() as db:
                assert {(await BugReportStore(db).state(row.id))["status"] for row in rows} == {
                    "new"
                }
            assert await audits() == []

            applied = await go("apply")
            assert applied["status"] == "applied" and applied["audit_events"] == 2
            async with setup.sessions() as db:
                for row in rows:
                    assert (await BugReportStore(db).state(row.id))["status"] == "fixed"
                    events = (
                        await db.scalars(
                            select(BugReportEvent).where(
                                BugReportEvent.bug_id == row.id, BugReportEvent.actor == "staff"
                            )
                        )
                    ).all()
                    assert sorted(event.kind for event in events) == ["note", "status"]
                    assert {event.actor_person_id for event in events} == {approver.id}
            written = await audits()
            assert len(written) == 2
            assert {event.payload["actor"] for event in written} == {"Claude (orchestrator)"}
            assert {event.payload["approver_email"] for event in written} == {approver_email}
            assert {event.payload["issue"] for event in written} == {"demo P0"}

            again = await go("apply")
            assert again["changed"] == [] and again["unchanged"] == numbers
            assert len(await audits()) == 2

            with pytest.raises(tool.Refused):
                await go("apply", {**spec, "numbers": [*numbers, 999_999]})
            with pytest.raises(tool.Refused):
                await go(
                    "apply",
                    {**spec, "status": "verified", "approver_email": "nobody@example.test"},
                )
            async with setup.sessions() as db:
                assert {(await BugReportStore(db).state(row.id))["status"] for row in rows} == {
                    "fixed"
                }

            read = await go("read", tool.spec_from(json.dumps({"numbers": numbers}), "read"))
            assert read == {
                "numbers": numbers,
                "missing": [],
                "before": {str(n): "fixed" for n in numbers},
                "status": "read",
            }
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_the_input_is_checked_before_anything_runs() -> None:
    for bad in (
        "not json",
        json.dumps({"numbers": []}),
        json.dumps({"numbers": [0]}),
        json.dumps({"numbers": [1], "status": "done", "approver_email": "a@example.test"}),
        json.dumps({"numbers": [1], "status": "fixed"}),
    ):
        with pytest.raises(tool.Refused):
            tool.spec_from(bad, "dry-run")
    assert tool.spec_from(json.dumps({"numbers": [3, 3, 1]}), "read") == {"numbers": [1, 3]}
