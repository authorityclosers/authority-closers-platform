"""Owner-scoped fast-only activation: real Admin handler, fictional local DB."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.call_data import engine
from ac_platform.identity.models import Person, Session
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

spec = importlib.util.spec_from_file_location(
    "call_data_fast_production",
    Path(__file__).resolve().parents[2] / "scripts/data-changes/call-data-fast-production.py",
)
script = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = script
spec.loader.exec_module(script)


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_fast_only_dry_run_audit_idempotency_and_revoked_session(postgres_harness, tmp_path):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        try:
            settings = Settings(
                _env_file=None, environment="test", operations_tenant_id=setup.actor.tenant_id
            )
            async with setup.sessions() as db:
                email = (await db.get(Person, setup.actor.person_id)).email

            async def invoke(apply):
                async with setup.sessions() as db:
                    tx = await db.begin()
                    try:
                        result = await script.execute(db, script.Command(email, apply), settings)
                        if apply:
                            await tx.commit()
                        else:
                            await tx.rollback()
                        return result
                    except BaseException:
                        await tx.rollback()
                        raise

            dry = await invoke(False)
            assert dry["status"] == "dry_run"
            assert dry["before"]["revision"] is None
            assert dry["after"]["config"]["deep"]["enabled"] is False
            async with setup.sessions() as db:
                before, revision = await db.run_sync(lambda s: engine.read_settings(s.connection()))
                assert revision is None
                assert not list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action.in_([script.ORDER_ACTION, "call_data.settings_saved"])
                        )
                    )
                )
            applied = await invoke(True)
            assert applied["status"] == "applied"
            after = applied["after"]["config"]
            assert after["fast"]["enabled"] and after["fast"]["daily_cap_inr"] == 150
            assert after["deep"]["enabled"] is False
            assert after["streaming"]["provider"] == "off"
            assert after["deep"]["daily_cap_inr"] == before["deep"]["daily_cap_inr"]
            assert after["fast"]["model"] == before["fast"]["model"]
            assert (await invoke(True))["status"] == "no_op"
            async with setup.sessions() as db:
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action.in_([script.ORDER_ACTION, "call_data.settings_saved"])
                        )
                    )
                )
                assert len(events) == 2
                order = next(e for e in events if e.action == script.ORDER_ACTION)
                assert order.payload["issue"] == "AUT-2182"
                assert order.actor_person_id == setup.actor.person_id
            async with setup.sessions() as db, db.begin():
                session = await db.get(Session, setup.actor.session_id)
                session.revoked_at = datetime.now(UTC)
            with pytest.raises(script.Refused, match="current_admin_session_required"):
                await invoke(True)
        finally:
            await setup.engine.dispose()

    run(exercise())
