"""Append-only settings history through the same Admin service used by HTTP/CLI."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
)
from ac_platform.conversation_intelligence.analysis_settings_admin import (
    ConversationAnalysisSettingsAdmin,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
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


def test_language_versions_replay_and_do_not_silently_reset(postgres_harness: Any) -> None:
    async def scenario() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed_actor(engine)
            async with AsyncSession(engine) as db, db.begin():
                service = ConversationAnalysisSettingsAdmin(
                    ConversationApplication(db, clock=lambda: owner.now),
                    operations_tenant_id=owner.tenant_id,
                )
                original = await service.save(
                    owner.actor,
                    DEFAULT_ANALYSIS_SETTINGS,
                    expected_revision=0,
                    key="legacy-settings",
                )
                values = AnalysisSettings.model_validate(
                    {
                        **DEFAULT_ANALYSIS_SETTINGS.model_dump(),
                        "c5_coaching_prompt_revision": "coaching-v4",
                        "report_language_default": "mr-Deva+en",
                    }
                )
                current = await service.save(
                    owner.actor, values, expected_revision=1, key="marathi-settings"
                )
                assert current["settings"]["report_language_default"] == "mr-Deva+en"
                assert (await service.current(owner.actor)) == current
                assert (
                    await service.save(
                        owner.actor,
                        DEFAULT_ANALYSIS_SETTINGS,
                        expected_revision=0,
                        key="legacy-settings",
                    )
                    == original
                )
                assert (
                    await service.save(
                        owner.actor, values, expected_revision=1, key="marathi-settings"
                    )
                    == current
                )
                with pytest.raises(ConversationConflict, match="Include the current"):
                    await service.save(
                        owner.actor,
                        DEFAULT_ANALYSIS_SETTINGS,
                        expected_revision=2,
                        key="outdated-cli",
                    )
                # An explicit rollback is a new revision, never a history edit.
                reverted = await service.save(
                    owner.actor,
                    AnalysisSettings.model_validate(DEFAULT_ANALYSIS_SETTINGS.effective_values()),
                    expected_revision=2,
                    key="explicit-rollback",
                )
                assert reverted["revision"] == 3
                history = await service.history(owner.actor)
                assert [
                    item["settings"]["report_language_default"] for item in history["items"]
                ] == ["en", "mr-Deva+en", "en"]
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(ConversationCommand.tenant_id == owner.tenant_id)
                    )
                ) == 3
        finally:
            await engine.dispose()

    run(scenario())
