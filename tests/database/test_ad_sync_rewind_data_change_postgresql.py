"""The approved data change that rewinds one workspace's ad-platform collector
(scripts/data-changes/ad-sync-rewind.py), on PostgreSQL: a stage move the old collector passed
by (16 Nov 2026, Wise Life) is previewed by the dry run, which leaves nothing; the apply moves
the cursor back with one audit event, and the sender's next pass freezes exactly the previewed
events, never a second "Lead"; a rerun changes nothing; a rewind past the platforms' window or
onto an engine without the fix is refused. Made-up leads only; nothing calls Meta."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.lead_desk.journey import engine, mapping
from ac_platform.lead_desk.models import LeadDeskSettings
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_lead_desk_journey_collect_postgresql import (
    conversions,
    meta_lead,
    switch_meta_on,
)
from tests.database.test_lead_os_acceptance_postgresql import ROOT, World, later, world

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/ad-sync-rewind.py"
LOADER = importlib.util.spec_from_file_location("ad_sync_rewind", SCRIPT)
assert LOADER is not None and LOADER.loader is not None
tool = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(tool)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


async def cursor(here: World) -> tuple[datetime, Any] | None:
    async with here.setup.sessions() as db:
        row = await db.get(LeadDeskSettings, here.tenant_id)
        assert row is not None
        found: tuple[datetime, Any] | None = mapping.cursor(dict(row.config))
        return found


async def audits(here: World) -> int:
    async with here.setup.sessions() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == tool.ACTION, AuditEvent.tenant_id == here.tenant_id)
            )
            or 0
        )


def test_a_rewind_sends_the_passed_by_moves_once(
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
            since = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
            await switch_meta_on(here, since)
            lead = await meta_lead(here, "Fictional Rewind", "98760 82001", "120000000082001")
            answered = await here.dispose(
                lead, connected=True, step="interested", follow_up_at=later(days=1)
            )
            assert answered.status_code == 200, answered.text

            # The sender before the fix: every line naming a pipeline was passed by.
            with monkeypatch.context() as old:
                old.setattr(engine, "between_pipelines", lambda data: "pipeline" in data)
                now = datetime.now(UTC) + engine.SETTLE + timedelta(minutes=1)
                assert await engine.collect(sessions, environment="test", now=now) == 1
            [lead_event] = await conversions(here, lead)
            passed = await cursor(here)
            assert passed is not None and passed[0] > since

            spec = {
                "command_id": str(uuid4()),
                "tenant": str(here.tenant_id)[:8],
                "rewind_to": since.isoformat(),
                "approver_email": admin,
                "approver": "Fictional owner, in chat",
                "issue": "AUT-test",
            }
            now = datetime.now(UTC) + engine.SETTLE + timedelta(minutes=2)
            dry = await tool.execute(sessions, spec, mode="dry-run", environment="test", now=now)
            assert dry["status"] == "rehearsed_and_rolled_back"
            assert dry["platforms_on"] == ["meta"]
            assert dry["cursor_before"] == passed[0].isoformat()
            assert dry["cursor_after"] == since.isoformat()
            preview = dry["preview"]
            assert preview["would_freeze"] >= 1
            assert preview["by_event_name"]["meta:interested"] == 1
            # "Lead" went before: never a second one.
            assert f"meta:{lead_event.event_name}" not in preview["by_event_name"]
            assert set(preview["by_history_line"]) == {"result"}
            # The dry run leaves nothing: cursor, events and audit as they were.
            assert await cursor(here) == passed
            assert len(await conversions(here, lead)) == 1
            assert await audits(here) == 0

            applied = await tool.execute(sessions, spec, mode="apply", environment="test", now=now)
            assert applied["status"] == "applied"
            assert applied["preview"] == preview
            rewound = await cursor(here)
            assert rewound is not None and rewound[0] == since
            assert await audits(here) == 1

            # The sender's next pass freezes exactly what the preview said.
            made = await engine.collect(sessions, environment="test", now=now)
            assert made == preview["would_freeze"]
            sent = await conversions(here, lead)
            assert len(sent) == 1 + made
            assert [c.event_name for c in sent].count(lead_event.event_name) == 1

            # A rerun of the same command changes nothing.
            again = await tool.execute(sessions, spec, mode="apply", environment="test", now=now)
            assert again["status"] == "done_before"
            assert await audits(here) == 1

            # Refused: past the platforms' window, no zone, and an engine without the fix.
            for bad, reason in (
                (
                    {"rewind_to": (now - timedelta(days=7)).isoformat()},
                    "rewind_to_older_than_the_platform_window",
                ),
                ({"rewind_to": "2026-11-16T19:38:16"}, "rewind_to_needs_a_zone"),
            ):
                with pytest.raises(SystemExit) as refused:
                    await tool.execute(
                        sessions,
                        {**spec, "command_id": str(uuid4()), **bad},
                        mode="dry-run",
                        environment="test",
                        now=now,
                    )
                assert reason in str(refused.value)
            with monkeypatch.context() as old:
                old.delattr(engine, "between_pipelines")
                with pytest.raises(SystemExit) as refused:
                    await tool.execute(
                        sessions,
                        {**spec, "command_id": str(uuid4())},
                        mode="dry-run",
                        environment="test",
                        now=now,
                    )
                assert "engine_without_the_stage_move_fix" in str(refused.value)
            assert await audits(here) == 1

    run(exercise())
