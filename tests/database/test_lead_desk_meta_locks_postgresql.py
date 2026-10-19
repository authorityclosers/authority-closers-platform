"""No database lock waits on Meta (19 Oct 2026: a pull holding every Page's lock through
Meta's calls made a manager's Switch off wait minutes on production).

The scheduled pull reads Meta with no transaction open; while Meta is still answering,
the same Page can be locked and switched off at once.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from ac_platform.lead_desk.connectors import meta, meta_pull
from ac_platform.lead_desk.models import Lead, LeadSource
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_lead_desk_meta_postgresql import ENV, LEADS, FakeGraph
from tests.database.test_lead_desk_postgresql import _organisation


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class SlowGraph(FakeGraph):
    """Meta takes its time answering for the Page's leads."""

    asked = asyncio.Event()
    answer = asyncio.Event()

    async def recent_leads(
        self, form_ids: list[str], page_token: str, *, since: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        SlowGraph.asked.set()
        await SlowGraph.answer.wait()
        return [LEADS["fa"][0]]


def test_a_page_is_never_locked_while_meta_answers(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    FakeGraph.forms_listed = ["fa"]
    cfg = meta.config()
    assert cfg is not None

    async def exercise() -> None:
        SlowGraph.asked = asyncio.Event()
        SlowGraph.answer = asyncio.Event()
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            source_id = uuid4()
            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadSource(
                        id=source_id,
                        tenant_id=setup.state.tenant_id,
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, "page-token-1", page_id="p1"),
                            "forms": "all",
                        },
                        active=True,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            pull = asyncio.create_task(
                meta_pull.pull_due(setup.sessions, cfg, SlowGraph(cfg), now=2_000_000_000)
            )
            await asyncio.wait_for(SlowGraph.asked.wait(), timeout=10)
            # Meta is still answering: a manager's Switch off takes the lock at once.
            async with setup.sessions() as db, db.begin():
                await db.execute(text("SET LOCAL lock_timeout = '2s'"))
                source = await db.scalar(
                    select(LeadSource)
                    .where(LeadSource.id == source_id)
                    .with_for_update(nowait=True)
                )
                assert source is not None
                source.active = False
            SlowGraph.answer.set()
            assert await asyncio.wait_for(pull, timeout=10) == 0
            async with setup.sessions() as db:
                # The switched-off Page took nothing from that late answer.
                assert (await db.scalars(select(Lead))).all() == []
                after = await db.get(LeadSource, source_id)
                assert after is not None and after.active is False
                assert "last_pulled_at" not in (after.config or {})
        finally:
            await setup.engine.dispose()

    run(exercise())
