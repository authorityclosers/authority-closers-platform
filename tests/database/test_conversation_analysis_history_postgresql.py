"""Append-only settings history through the same Admin service used by HTTP/CLI."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.analysis_settings import DEFAULT_ANALYSIS_SETTINGS
from ac_platform.conversation_intelligence.analysis_settings_admin import (
    ConversationAnalysisSettingsAdmin,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.models import ConversationCommand
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_provider_admin_postgresql import seed_actor


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Any]:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


def test_history_is_bounded_tenant_scoped_and_does_not_mutate(postgres_harness: Any) -> None:
    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed_actor(engine)
            other = await seed_actor(engine)
            async with AsyncSession(engine) as db, db.begin():
                service = ConversationAnalysisSettingsAdmin(
                    ConversationApplication(db, clock=lambda: owner.now),
                    operations_tenant_id=owner.tenant_id,
                )
                assert await service.history(owner.actor) == {
                    "items": [],
                    "next_before_revision": None,
                }
                for revision in range(3):
                    await service.save(
                        owner.actor,
                        DEFAULT_ANALYSIS_SETTINGS.model_copy(
                            update={"c4_max_requests": revision + 1}
                        ),
                        expected_revision=revision,
                        key=f"history-proof-{revision}",
                    )
                count_before = await db.scalar(
                    select(func.count()).select_from(ConversationCommand)
                )
                page = await service.history(owner.actor, limit=2)
                assert [row["revision"] for row in page["items"]] == [3, 2]
                assert [row["settings"]["c4_max_requests"] for row in page["items"]] == [3, 2]
                assert page["next_before_revision"] == 2
                tail = await service.history(owner.actor, before_revision=2, limit=2)
                assert [row["revision"] for row in tail["items"]] == [1]
                assert tail["next_before_revision"] is None
                assert (await service.current(owner.actor))["revision"] == 3
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationCommand))
                    == count_before
                )
                with pytest.raises(ConversationError, match="operations workspace"):
                    await service.history(other.actor)
                for bad in (0, 51, True):
                    with pytest.raises(ConversationError, match="history limit"):
                        await service.history(owner.actor, limit=bad)
        finally:
            await engine.dispose()

    run(scenario())
