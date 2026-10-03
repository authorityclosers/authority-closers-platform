"""Disposable PostgreSQL proof for speaker history, tenancy and canonical erasure."""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.models import ConversationPermission
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.db.models import model_metadata
from ac_platform.identity.sales_xray_profile import erase_sales_xray_profile
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_submission_labels_postgresql import (
    _retained_claimed_submission,
)
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _choices(setup: Any, source: dict[str, Any], count: int = 1) -> None:
    async with setup.sessions() as database, database.begin():
        for revision in range(1, count + 1):
            database.add(
                ConversationSpeakerMapRevision(
                    id=uuid4(),
                    tenant_id=setup.state.tenant_id,
                    submission_id=source["submission_id"],
                    revision=revision,
                    transcript_revision="fictional-c2-revision",
                    speakers=[{"speaker_id": "speaker_0", "role": "you", "display_name": "Zoya"}],
                    actor_person_id=setup.state.person_id,
                    created_at=setup.state.now,
                )
            )


def test_postgres_schema_bounds_tenant_fks_and_no_history_update(
    postgres_harness: Any, tmp_path: Path
) -> None:
    with postgres_harness.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
        column = next(
            c
            for c in inspect(connection).get_columns("conversation_processing_plans")
            if c["name"] == "speaker_roles"
        )
        assert column["nullable"] and column["default"] is None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            await _choices(setup, source)
            other = await seed(setup.engine)
            table = ConversationSpeakerMapRevision.__table__
            values = dict(
                id=uuid4(),
                tenant_id=setup.state.tenant_id,
                submission_id=source["submission_id"],
                revision=2,
                transcript_revision="fictional-c2-revision",
                speakers=[],
                actor_person_id=setup.state.person_id,
                created_at=setup.state.now,
            )
            for invalid in (
                {"revision": 0},
                {"revision": 51},
                {"revision": 1},
                {"transcript_revision": ""},
                {"transcript_revision": "r" * 257},
                {"tenant_id": other.tenant_id, "actor_person_id": other.person_id},
                {"actor_person_id": other.person_id},
            ):
                with pytest.raises(DBAPIError), postgres_harness.begin() as connection:
                    connection.execute(table.insert().values({**values, **invalid}))
            with pytest.raises(DBAPIError, match="append-only"), postgres_harness.begin() as conn:
                conn.execute(
                    update(table)
                    .where(table.c.submission_id == source["submission_id"])
                    .values(speakers=[])
                )
            async with setup.sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.submission_id == source["submission_id"])
                    )
                    == 1
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("erasure", ["recording", "person"])
def test_postgres_canonical_erasure_preserves_other_calls_tenants_and_audit(
    postgres_harness: Any, tmp_path: Path, erasure: str
) -> None:
    async def exercise() -> None:
        (tmp_path / "owner").mkdir()
        (tmp_path / "other-tenant").mkdir()
        setup = await _setup(postgres_harness, tmp_path / "owner")
        other = await _setup(postgres_harness, tmp_path / "other-tenant")
        try:
            source = await _seed_retained_guest_submission(setup)
            sibling = await _seed_retained_guest_submission(setup)
            async with setup.sessions() as database, database.begin():
                await setup.factory(database).claim(setup.guest.token, setup.state.actor)
            unrelated = await _retained_claimed_submission(other)
            for actor, call in ((setup, source), (setup, sibling), (other, unrelated)):
                await _choices(actor, call, count=2)
            async with setup.sessions() as database, database.begin():
                audit_count = await database.scalar(select(func.count()).select_from(AuditEvent))
                permission = await database.get(ConversationPermission, setup.state.permission_id)
                assert permission is not None
                deadline = permission.retention_until
                if erasure == "person":
                    assert await erase_sales_xray_profile(database, person_id=setup.state.person_id)
                    assert not await erase_sales_xray_profile(
                        database, person_id=setup.state.person_id
                    )
            if erasure == "recording":
                await _reconcile(setup.sessions, setup.state)
                # Only this recording reaches its deadline; sibling rows must survive.
                async with setup.sessions() as database, database.begin():
                    from ac_platform.conversation_intelligence.models import ConversationRecording

                    recording = await database.get(ConversationRecording, source["recording_id"])
                    assert recording is not None
                    permission = await database.get(ConversationPermission, recording.permission_id)
                    assert permission is not None
                    permission.retention_until = deadline - timedelta(seconds=1)
                scheduler = ConversationRetentionScheduler(setup.sessions, clock=lambda: deadline)
                assert await scheduler.step()
                worker = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await worker.run_once()
            async with setup.sessions() as database:
                rows = (await database.scalars(select(ConversationSpeakerMapRevision))).all()
                ids = {row.submission_id for row in rows}
                assert source["submission_id"] not in ids
                assert (sibling["submission_id"] in ids) == (erasure == "recording")
                assert unrelated["submission_id"] in ids
                assert (
                    await database.scalar(select(func.count()).select_from(AuditEvent))
                    >= audit_count
                )
                for tenant in (setup.state.tenant_id, other.state.tenant_id):
                    assert (await verify_audit_chain(database, tenant)).valid
        finally:
            await setup.engine.dispose()
            await other.engine.dispose()

    run(exercise())
