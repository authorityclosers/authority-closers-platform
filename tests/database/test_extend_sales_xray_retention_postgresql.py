"""Owner-approved keep-until-deleted retention change on disposable PostgreSQL."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/data-changes/extend-sales-xray-retention.py"
SPEC = importlib.util.spec_from_file_location("extend_sales_xray_retention", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _seven_day_upload(setup: Any) -> tuple[Any, Any]:
    async with setup.sessions() as db, db.begin():
        recording = await db.get(ConversationRecording, setup.prepared.recording_id)
        permission = await db.get(ConversationPermission, recording.permission_id)
        permission.retention_until = permission.created_at + timedelta(days=7)
        return permission.id, permission.created_at


async def _extended_events(setup: Any) -> int:
    async with setup.sessions() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "conversation.retention_extended")
            )
            or 0
        )


def test_hidden_seven_day_upload_is_kept_until_deleted_once_and_not_erased(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            permission_id, created = await _seven_day_upload(setup)
            later = created + timedelta(days=8)

            dry = await tool.extend(
                setup.sessions, apply=False, approver="owner", issue="T-1", clock=lambda: later
            )
            assert dry["permissions_to_extend"] == 1 and dry["hidden_now_restored"] == 1
            async with setup.sessions() as db:
                unchanged = await db.get(ConversationPermission, permission_id)
                assert unchanged.retention_until == created + timedelta(days=7)
            assert await _extended_events(setup) == 0

            applied = await tool.extend(
                setup.sessions,
                apply=True,
                approver="owner, chat 18 Oct",
                issue="T-1",
                snapshot_sha256="0" * 64,
                clock=lambda: later,
            )
            assert applied["permissions_to_extend"] == 1
            async with setup.sessions() as db:
                kept = await db.get(ConversationPermission, permission_id)
                assert kept.retention_until == created + timedelta(days=tool.KEEP_DAYS)
                event = await db.scalar(
                    select(AuditEvent).where(AuditEvent.action == "conversation.retention_extended")
                )
                assert event.actor_type == "system" and event.actor_person_id is None
                assert event.payload["approver"] == "owner, chat 18 Oct"
                assert event.payload["policy_ref"] == tool.POLICY_REF
                [entry] = event.payload["permissions"]
                assert entry["permission_id"] == str(permission_id)
                assert entry["old_retention_until"] == (created + timedelta(days=7)).isoformat()

            # The retention step no longer finds the call, and a second run changes nothing.
            scheduler = ConversationRetentionScheduler(setup.sessions, clock=lambda: later)
            assert await scheduler.step() is False
            again = await tool.extend(
                setup.sessions, apply=True, approver="owner", issue="T-1", clock=lambda: later
            )
            assert again["permissions_to_extend"] == 0
            assert again["already_kept_until_deleted"] == 1
            assert await _extended_events(setup) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_upload_already_being_erased_is_left_alone(postgres_harness: Any, tmp_path: Any) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            permission_id, created = await _seven_day_upload(setup)
            later = created + timedelta(days=8)
            assert await ConversationRetentionScheduler(setup.sessions, clock=lambda: later).step()

            applied = await tool.extend(
                setup.sessions, apply=True, approver="owner", issue="T-2", clock=lambda: later
            )
            assert applied["permissions_to_extend"] == 0
            assert applied["skipped_already_erasing_or_deleted"] == 1
            async with setup.sessions() as db:
                permission = await db.get(ConversationPermission, permission_id)
                assert permission.retention_until == created + timedelta(days=7)
            assert await _extended_events(setup) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_production_apply_needs_a_snapshot_digest() -> None:
    with pytest.raises(ValueError, match="production_snapshot_required"):
        run(
            tool.execute(
                "production",
                "postgresql+psycopg://unused@127.0.0.1:1/unused",
                apply=True,
                approver="owner",
                issue="T-3",
                snapshot_sha256=None,
            )
        )
