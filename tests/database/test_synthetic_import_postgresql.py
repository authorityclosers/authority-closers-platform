"""Sandbox flag data change and the sandbox tables' relational invariants."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.db.models import model_metadata
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_bulk_import_postgresql import postgres_harness as _bulk_postgres_harness
from tests.database.test_bulk_import_postgresql import setup_import
from tests.database.test_conversation_postgresql import run

pytestmark = pytest.mark.usefixtures("postgres_harness")


@pytest.fixture(scope="module")
def postgres_harness():
    # Reuse C's existing test-only guardian bridge: native children retain the
    # acquired slot, whose live ancestor is still verified by ac-heavy.
    with pytest.MonkeyPatch.context() as patch:
        yield from _bulk_postgres_harness.__wrapped__(patch)


def test_exact_sandbox_data_change_dry_run_apply_replay_and_environment_guard(
    postgres_harness, tmp_path
):
    path = Path(__file__).parents[2] / "scripts/data-changes/enable-synthetic-sandbox.py"
    spec = importlib.util.spec_from_file_location("synthetic_sandbox_data_change", path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db, db.begin():
                db.add(Tenant(id=tool.TARGET, slug="fictional-ac-sandbox", name="AC Sandbox"))
                await db.flush()
                db.add(
                    Organisation(
                        tenant_id=tool.TARGET,
                        created_by_person_id=setup.state.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="f" * 43,
                    )
                )
                db.add(
                    Membership(
                        tenant_id=tool.TARGET,
                        person_id=setup.state.person_id,
                        role="owner",
                    )
                )
            settings = setup.settings.model_copy(
                update={
                    "environment": "staging",
                    "database_url": postgres_harness.url.render_as_string(hide_password=False),
                }
            )
            args = dict(
                settings=settings,
                approver=setup.state.person_id,
                approval="fictional-owner-approval:AUT-1676",
            )
            preview = await tool.execute(**args, apply=False)
            assert preview["before"] is False and preview["after"] is True
            async with setup.sessions() as db:
                assert await db.get(ConversationSandboxOrganisation, tool.TARGET) is None
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == tool.TARGET)
                    )
                    == 0
                )
            applied = await tool.execute(**args, apply=True)
            assert applied["before"] is False and applied["applied"] is True
            repeat = await tool.execute(**args, apply=True)
            assert repeat["before"] is True and repeat["run_id"] != applied["run_id"]
            async with setup.sessions() as db:
                flag = await db.get(ConversationSandboxOrganisation, tool.TARGET)
                assert flag is not None and flag.approved_by_person_id == setup.state.person_id
                events = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tool.TARGET))
                ).all()
                assert len(events) == 2
                assert all(event.action == "conversation.sandbox_flag_approved" for event in events)
            for environment in ("test", "production"):
                with pytest.raises(ValueError, match="staging"):
                    await tool.execute(
                        **{
                            **args,
                            "settings": settings.model_copy(update={"environment": environment}),
                        },
                        apply=True,
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())


async def flag(setup):
    async with setup.sessions() as db, db.begin():
        db.add(
            ConversationSandboxOrganisation(
                tenant_id=setup.organisation.tenant_id,
                approved_by_person_id=setup.state.person_id,
                approval_reference="fictional-owner-approval:AUT-1676",
                created_at=setup.clock[0],
            )
        )


def test_sandbox_schema_matches_models_and_authored_records_are_append_only(
    postgres_harness,
    tmp_path,
):
    """Schema invariants of the AC Sandbox tables the direct-DB loaders write."""

    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            await flag(setup)
            async with setup.sessions() as db, db.begin():
                db.add(
                    ConversationSyntheticRecord(
                        tenant_id=setup.organisation.tenant_id,
                        kind="companies",
                        synthetic_key="syn-fixture-company-1",
                        revision=1,
                        business_id="syn-fixture",
                        imported_by_person_id=setup.state.person_id,
                        payload_sha256="a" * 64,
                        payload={"synthetic": True, "name": "Fictional Company"},
                        occurred_at=setup.clock[0],
                        imported_at=setup.clock[0],
                    )
                )
            with postgres_harness.connect() as connection:
                assert (
                    compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
                )
            with pytest.raises(DBAPIError):
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationSyntheticRecord).values(payload={"rewritten": True})
                    )
            async with setup.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(
                            ConversationSyntheticRecord.tenant_id == setup.organisation.tenant_id
                        )
                    )
                    == 1
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
