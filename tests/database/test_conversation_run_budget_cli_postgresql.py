"""The watchdog check is bounded, read-only and prints identifiers only."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.run_budget_cli import check, main
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_report_minutes_postgresql import setup_case
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_watchdog_exit_status_and_read_only_state(
    postgres_harness: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    async def prepare() -> Any:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine, plan_hours=-1)
            async with case.sessions() as db, db.begin():
                plan = await db.get(ConversationProcessingPlan, case.plan.id)
                plan.state = "quoted"
            return case.plan.id
        finally:
            await engine.dispose()

    identifier = run(prepare())
    monkeypatch.setenv(
        "AC_DATABASE_URL", postgres_harness.url.render_as_string(hide_password=False)
    )
    assert main() == 1
    output = capsys.readouterr().out
    assert str(identifier) in output and "source_sha256" not in output

    async def read_back() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            from sqlalchemy.ext.asyncio import AsyncSession

            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(ConversationProcessingPlan.state).where(
                            ConversationProcessingPlan.id == identifier
                        )
                    )
                ) == "quoted"
        finally:
            await engine.dispose()

    run(read_back())
    monkeypatch.delenv("AC_DATABASE_URL")
    assert main() == 2
    assert capsys.readouterr().err == "Run budget check unavailable.\n"


def test_check_transaction_cannot_write(
    postgres_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    import ac_platform.conversation_intelligence.run_budget_cli as cli

    async def forbidden_write(database: Any) -> dict[str, Any]:
        await database.execute(text("CREATE TABLE forbidden_watchdog_write (id int)"))
        return {}

    monkeypatch.setenv(
        "AC_DATABASE_URL", postgres_harness.url.render_as_string(hide_password=False)
    )
    monkeypatch.setattr(cli, "overdue_processing_plans", forbidden_write)
    with pytest.raises(DBAPIError, match="read-only"):
        run(check())
