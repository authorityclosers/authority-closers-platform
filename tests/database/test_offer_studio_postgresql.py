"""Offer Studio's shared store on PostgreSQL: append-only versions, stale saves refused,
archiving as a new version, one workspace's offers invisible to another, bodies bounded.
Fictional rows only; each run uses fresh offer ids (the database outlives one test)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationNotFound,
)
from ac_platform.offer_studio.models import AdminOfferVersion, OfferHistoryError
from ac_platform.offer_studio.store import (
    MAX_BODY_BYTES,
    OfferStudioStore,
    OfferTooLarge,
    offer_name,
)
from tests.database.test_conversation_reviews_postgresql import ReviewCase, run
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)


def _body(name: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "naming": {"chosen": ""}, "stack": [], **extra}


async def exercise(case: ReviewCase) -> None:
    ops = case.admin_actor
    offer_id = uuid4()

    async def save(base: int | None, body: dict[str, Any], *, tenant=None, archived=False):
        async with case.sessions() as database, database.begin():
            return await OfferStudioStore(database).save(
                tenant_id=tenant or ops.tenant_id,
                person_id=ops.person_id,
                offer_id=offer_id,
                base_version=base,
                body=body,
                archived=archived,
                now=datetime.now(UTC),
            )

    first = await save(None, _body("Fictional team offer"))
    assert first["version"] == 1 and first["name"] == "Fictional team offer"
    second = await save(1, _body("Fictional team offer", naming={"chosen": "Close-More System"}))
    assert second["version"] == 2 and second["name"] == "Close-More System"

    # A save on an old version, or a "new" offer that already exists: refused, nothing written.
    for stale in (1, None, 7):
        with pytest.raises(ConversationConflict):
            await save(stale, _body("Overwrite"))

    async with case.sessions() as database:
        store = OfferStudioStore(database)
        latest = {o["offer_id"]: o for o in (await store.latest(ops.tenant_id))["offers"]}
        assert latest[str(offer_id)]["version"] == 2
        assert latest[str(offer_id)]["body"]["naming"]["chosen"] == "Close-More System"
        history = (await store.history(ops.tenant_id, offer_id))["versions"]
        assert [v["version"] for v in history] == [2, 1]
        assert "body" not in history[0]
        assert (await store.version(ops.tenant_id, offer_id, 1))["body"]["name"] == (
            "Fictional team offer"
        )
        # Another workspace sees none of it.
        with pytest.raises(ConversationNotFound):
            await store.history(case.foreign_actor.tenant_id, offer_id)
        with pytest.raises(ConversationNotFound):
            await store.version(case.foreign_actor.tenant_id, offer_id, 1)
        foreign = (await store.latest(case.foreign_actor.tenant_id))["offers"]
        assert str(offer_id) not in {o["offer_id"] for o in foreign}

    # Nor can it save on top of it.
    with pytest.raises(ConversationNotFound):
        await save(2, _body("Foreign"), tenant=case.foreign_actor.tenant_id)

    # Too large: refused before anything is read or written.
    with pytest.raises(OfferTooLarge):
        await save(2, _body("Big", notes="x" * (MAX_BODY_BYTES + 1)))

    # Archive: a third version, archived; it leaves the list but keeps its history.
    archived = await save(2, _body("Fictional team offer"), archived=True)
    assert archived["version"] == 3 and archived["archived"] is True
    async with case.sessions() as database:
        store = OfferStudioStore(database)
        listed = {o["offer_id"] for o in (await store.latest(ops.tenant_id))["offers"]}
        assert str(offer_id) not in listed
        assert len((await store.history(ops.tenant_id, offer_id))["versions"]) == 3
        rows = await database.scalar(
            select(func.count()).where(AdminOfferVersion.offer_id == offer_id)
        )
        assert rows == 3

    # The ORM refuses to change or remove a version.
    for change in ("update", "delete"):
        with pytest.raises(OfferHistoryError):
            async with case.sessions() as database, database.begin():
                row = await database.scalar(
                    select(AdminOfferVersion).where(AdminOfferVersion.offer_id == offer_id).limit(1)
                )
                assert row is not None
                if change == "update":
                    row.name = "Rewritten"
                else:
                    await database.delete(row)
                await database.flush()

    # Archiving something that was never shared: not found.
    offer_id = uuid4()
    with pytest.raises(ConversationNotFound):
        await save(None, _body("Ghost"), archived=True)


def test_offer_studio_versions_on_postgresql(review_case: ReviewCase) -> None:
    run(exercise(review_case))


def test_offer_name_prefers_the_chosen_name() -> None:
    assert offer_name({"name": " Working ", "naming": {"chosen": " Chosen "}}) == "Chosen"
    assert offer_name({"name": "Working", "naming": {"chosen": "  "}}) == "Working"
    assert offer_name({"name": 5, "naming": "x"}) == "Untitled offer"
    assert len(offer_name({"name": "n" * 500})) == 200
