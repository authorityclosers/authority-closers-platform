"""Fictional PostgreSQL proof for unused shared-source schema and permanent history."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject as Object,
)
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceReference as Reference,
)
from tests.database.test_conversation_postgresql import (
    application,
    run,
    seed,
)
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_source_history_constraints(postgres_harness: Any) -> None:
    async def recording() -> Any:
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            other = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                result = await application(database, state).register(
                    state.actor, state.recording_intent, key="source-proof"
                )
            return state, other, UUID(result["id"])
        finally:
            await engine.dispose()

    state, other, recording_id = run(recording())
    now = datetime.now(UTC)
    with Session(postgres_harness) as db, db.begin():

        def add_object(tenant: Any) -> Object:
            obj = Object(
                id=uuid4(), tenant_id=tenant, source_sha256=state.source_sha256, created_at=now
            )
            db.add(obj)
            db.flush()
            return obj

        first = add_object(state.tenant_id)
        with pytest.raises(IntegrityError), db.begin_nested():
            add_object(state.tenant_id)
        foreign = add_object(other.tenant_id)
        ref = dict(
            recording_id=recording_id,
            tenant_id=state.tenant_id,
            person_id=state.person_id,
            created_at=now,
        )
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(Reference(**ref, source_object_id=foreign.id))
            db.flush()
        db.add(Reference(**ref, source_object_id=first.id))
        db.flush()
        with pytest.raises(IntegrityError), db.begin_nested():
            db.add(Reference(**ref, source_object_id=first.id))
            db.flush()
        db.execute(update(Reference).values(released_at=now, release_reason="owner_erasure"))
        for statement in (delete(Reference), update(Reference).values(release_reason="rewrite")):
            with pytest.raises(IntegrityError), db.begin_nested():
                db.execute(statement)
        assert db.scalar(select(Reference.release_reason)) == "owner_erasure"
        first.deleted_at = now
        db.flush()
        assert add_object(state.tenant_id).id != first.id
        assert db.get(Object, first.id).deleted_at == now
