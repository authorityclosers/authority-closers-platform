"""Populated loopback upgrade of the 0077 prospect tags migration (data preserved)."""

import subprocess
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, Table, literal, select, text
from sqlalchemy.orm import registry

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence import guest_models, guest_ownership
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspectMembership,
)
from ac_platform.db.models import model_metadata
from tests.database.prospect_legacy_fixtures import legacy_person_projection
from tests.database.test_conversation_postgresql import _migration_head, run
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_prospect_store_postgresql import direct_call, store


def test_populated_0076_upgrade_preserves_identity_history_and_model(
    tmp_path: Path, monkeypatch: Any
) -> None:
    original = subprocess.run
    invocation: list[Any] = []

    def parent_first(args: Any, **kwargs: Any) -> Any:
        if args[-1] == "head":
            invocation[:] = [args, kwargs]
            args = [*args[:-1], "20261005_0076"]
        return original(args, **kwargs)

    harness = cast(Any, _postgres_harness).__wrapped__()
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", parent_first)
        engine = next(harness)

    # Populate the historical schema with its actual columns, then use today's
    # registry only after upgrading. New nullable ORM columns do not exist at 0076.
    legacy_registry = registry()
    legacy_table = Table("conversation_guest_submissions", MetaData(), autoload_with=engine)
    assert "capture_source" not in legacy_table.c

    class LegacySubmission:
        pass

    legacy_registry.map_imperatively(LegacySubmission, legacy_table)

    async def populate() -> tuple[Any, UUID, Any]:
        setup = await _setup(engine, tmp_path)
        call, identifier = await direct_call(setup), uuid4()
        async with setup.sessions() as db, db.begin():
            await db.execute(
                text(
                    "INSERT INTO conversation_prospects (id, tenant_id, display_name, "
                    "created_by_person_id, owner_person_id, revision, created_at, updated_at) "
                    "VALUES (:id, :tenant, 'Legacy Fictional', :person, :person, 4, :now, :now)"
                ),
                {
                    "id": identifier,
                    "tenant": setup.state.tenant_id,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await db.execute(
                text(
                    "INSERT INTO conversation_prospect_memberships (id, tenant_id, prospect_id, "
                    "submission_id, linked_by_person_id, created_at) "
                    "VALUES (:id, :tenant, :prospect, :call, :person, :now)"
                ),
                {
                    "id": uuid4(),
                    "tenant": setup.state.tenant_id,
                    "prospect": identifier,
                    "call": call,
                    "person": setup.state.person_id,
                    "now": setup.clock[0],
                },
            )
            await store(setup, db)._audit(
                setup.state.actor, identifier, "created", {}, setup.clock[0]
            )
        async with setup.sessions() as db:
            row = (
                (
                    await db.execute(
                        text("SELECT * FROM conversation_prospects WHERE id=:id"),
                        {"id": identifier},
                    )
                )
                .mappings()
                .one()
            )
            events = (await db.scalars(select(AuditEvent))).all()
            members = (
                await db.execute(
                    select(
                        ConversationProspectMembership.id,
                        ConversationProspectMembership.submission_id,
                    )
                )
            ).all()
            preserved = (
                dict(row),
                [(e.id, e.event_hash) for e in events],
                [(m.id, m.submission_id) for m in members],
            )
        await setup.engine.dispose()
        return setup, identifier, preserved

    try:
        with monkeypatch.context() as patch:
            legacy_person_projection(engine, legacy_registry, patch)
            patch.setattr(guest_models, "ConversationGuestSubmission", LegacySubmission)
            patch.setattr(guest_ownership, "ConversationGuestSubmission", LegacySubmission)
            # Populate the actual 0076 schema before its journal exists. These
            # scoped legacy projections are removed before the real upgrade.
            patch.setattr(
                "ac_platform.conversation_intelligence.report_minutes.ReportMinutes.latest",
                AsyncMock(return_value=None),
            )
            patch.setattr(
                "ac_platform.conversation_intelligence.acquisition_usage.report_minute_value",
                lambda *args, **kwargs: literal(None),
            )
            setup, identifier, preserved = run(populate())
        if not invocation:
            pytest.fail("The isolated parent migration was not captured.", pytrace=False)
        migrated = original([*invocation[0][:-1], "20261007_0077"], **invocation[1])
        if migrated.returncode:
            pytest.fail(
                "Isolated tags migration failed; environment/output withheld.", pytrace=False
            )
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261007_0077"
            row = dict(
                db.execute(
                    text("SELECT * FROM conversation_prospects WHERE id=:id"), {"id": identifier}
                )
                .mappings()
                .one()
            )
            assert row.pop("tags") == [] and row == preserved[0]
            assert list(db.execute(select(AuditEvent.id, AuditEvent.event_hash))) == preserved[1]
            assert (
                list(
                    db.execute(
                        select(
                            ConversationProspectMembership.id,
                            ConversationProspectMembership.submission_id,
                        )
                    )
                )
                == preserved[2]
            )
        migrated = original(invocation[0], **invocation[1])
        if migrated.returncode:
            pytest.fail(
                "Isolated head migration failed; environment/output withheld.", pytrace=False
            )
        with engine.connect() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == _migration_head()
            assert compare_metadata(MigrationContext.configure(db), model_metadata()) == []
            assert db.execute(
                text("SELECT submission_id, capture_source FROM conversation_guest_submissions")
            ).all() == [(preserved[2][0][1], None)]
    finally:
        legacy_registry.dispose()
        harness.close()
