"""Bug issues on PostgreSQL (owner, 25 Oct 2026; v0.93): reports that look like one problem
join one issue; a report on a solved issue reopens it; a status change reaches every report on
the issue, and solving it tells each reporter once in the bell; the agents' CLI lists, shows
and sets issues by name; history is append-only; the migration passes the gate and refuses a
rollback once issues exist."""

from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports import issues_cli
from ac_platform.bug_reports.issues import BugIssueRefused, IssueStore
from ac_platform.bug_reports.models import (
    BugIssue,
    BugIssueEvent,
    BugReportEvent,
    BugReportHistoryError,
)
from ac_platform.bug_reports.store import BugReportStore, NewReport
from ac_platform.product_updates.models import Notification
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261025_0138_bug_issues.py"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("bug_issues_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert module.revision == "20261025_0138"
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Any,
) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ac_platform.db.models import model_metadata

    module = migration()
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _report(setup: Any, words: str, route: str = "/leads") -> NewReport:
    return NewReport(
        person_id=setup.state.person_id,
        tenant_id=setup.state.tenant_id,
        command_id=uuid4(),
        words=words,
        blocks_work=False,
        area="leads",
        route=route,
        context={
            "app": {"channel": "android", "native_version": "1.0.34"},
            "device": {"os": "Android 13", "model": "IV2201"},
        },
        client_errors=[],
        user_agent="test",
    )


def test_reports_join_issues_and_solving_tells_the_reporter_once(
    postgres_harness: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    async def exercise() -> Any:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # ac-bugs below reads the real clock, so this story happens before it.
            now = setup.state.now - timedelta(minutes=30)
            async with setup.sessions() as db, db.begin():
                store, issues = BugReportStore(db), IssueStore(db)
                one = await store.create(
                    _report(setup, "The taking leads switch needs a better icon"),
                    bug_id=uuid4(),
                    now=now,
                )
                two = await store.create(
                    _report(setup, "Better icon needed for the taking leads switch", "/leads?x=1"),
                    bug_id=uuid4(),
                    now=now + timedelta(seconds=1),
                )
                other = await store.create(
                    _report(setup, "Pipelines sit on the left, the right side is empty"),
                    bug_id=uuid4(),
                    now=now + timedelta(seconds=2),
                )
                first, outcome_one = await issues.assign(one, now=now)
                second, outcome_two = await issues.assign(two, now=now)
                third, _ = await issues.assign(other, now=now)
                assert (outcome_one, outcome_two) == ("new", "joined")
                assert first.id == second.id != third.id
                # Assigning again changes nothing.
                assert (await issues.assign(one, now=now))[1] == "joined"
                listed = await issues.issues(which="new")
                mine = next(item for item in listed if item["id"] == str(first.id))
                assert mine["count"] == 2 and mine["screen"] == "/leads"
                assert mine["devices"] == {"IV2201": 2} and mine["android"] == {"Android 13": 2}
                assert mine["orgs"] == 1 and "words" not in json.dumps(mine)
                with pytest.raises(BugIssueRefused):
                    await issues.set_status(first.number, status="done", now=now, actor="agent")
                solved = await issues.set_status(
                    str(first.number),
                    status="solved",
                    now=now + timedelta(minutes=1),
                    actor="agent",
                    actor_name="orchestrator",
                    note="The switch has its icon",
                    commit="a572dd29f",
                    release="v0.93.0",
                )
                assert solved["status"] == "solved" and solved["reporters_told"] == 2
                assert solved["release"] == "v0.93.0" and solved["commit"] == "a572dd29f"
                assert solved["history"][-2]["actor_name"] == "orchestrator"
                # Every report on it is fixed, with the issue's note.
                states = (
                    await db.scalars(
                        select(BugReportEvent.status).where(
                            BugReportEvent.bug_id.in_([one.id, two.id]),
                            BugReportEvent.kind == "status",
                            BugReportEvent.actor == "board",
                        )
                    )
                ).all()
                assert sorted(states) == ["fixed", "fixed"]
                told = (
                    await db.scalars(select(Notification).where(Notification.kind == "bug_solved"))
                ).all()
                assert len(told) == 2
                assert told[0].title.startswith("Fixed: ") and told[0].href == "/"
                assert "latest update" in told[0].body
                # Solved again: nobody is told twice.
                again = await issues.set_status(
                    first.id,
                    status="solved",
                    now=now + timedelta(minutes=2),
                    actor="agent",
                    actor_name="orchestrator",
                )
                assert again["reporters_told"] == 0
                # A new report like it reopens the issue: "came back after the fix".
                back = await store.create(
                    _report(setup, "Taking leads switch better icon"),
                    bug_id=uuid4(),
                    now=now + timedelta(minutes=3),
                )
                issue, outcome = await issues.assign(back, now=now + timedelta(minutes=3))
                assert outcome == "reopened" and issue.id == first.id
                reopened = await issues.detail(first.id)
                assert reopened["status"] == "new" and reopened["came_back"] is True
            async with AsyncSession(setup.engine) as db:
                row = await db.get(BugIssue, first.id)
                assert row is not None
                row.route = "/changed"
                with pytest.raises(BugReportHistoryError):
                    await db.flush()
                await db.rollback()
                event = await db.scalar(select(BugIssueEvent).limit(1))
                await db.delete(event)
                with pytest.raises(BugReportHistoryError):
                    await db.flush()
            return setup.engine.url, first.number
        finally:
            await setup.engine.dispose()

    url, number = run(exercise())
    url_file = tmp_path / "database-url"
    url_file.write_text(url.render_as_string(hide_password=False))

    def call(*extra: str) -> tuple[int, dict[str, Any]]:
        code = issues_cli.main(["--database-url-file", str(url_file), *extra])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    code, listed = call("list", "--all")
    assert code == 0 and any(item["number"] == number for item in listed["issues"])
    code, shown = call("show", str(number))
    assert code == 0 and shown["issue"]["came_back"] is True
    code, changed = call(
        "set",
        str(number),
        "--status",
        "fixed-in-next-update",
        "--as",
        "sign-in session",
        "--commit",
        "abcdef1",
    )
    assert code == 0 and changed["issue"]["status"] == "fixed_next"
    code, waiting = call("fixed-next")
    assert [item["number"] for item in waiting["issues"]] == [number]
    assert call("set", str(number), "--status", "solved", "--as", " ")[0] == 1
    assert call("show", "99999")[0] == 1
