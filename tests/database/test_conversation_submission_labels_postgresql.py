"""Disposable PostgreSQL proof for private call labels and erasure."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, inspect, select, text

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.submission_label_models import (
    ConversationSubmissionLabelRevision,
)
from ac_platform.conversation_intelligence.submission_labels import (
    erase_submission_labels_for_recording,
    read_submission_label,
    update_submission_label,
)
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.identity.sales_xray_profile import erase_sales_xray_profile
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _session,
)
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import (
    run,
    seed,
    wait_blocked,
)
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_postgres_migration_installs_the_revision_table(postgres_harness: Any) -> None:
    with postgres_harness.connect() as connection:
        assert inspect(connection).has_table("conversation_submission_label_revisions")


async def _retained_claimed_submission(setup: Any) -> dict[str, Any]:
    source = await _seed_retained_guest_submission(setup)
    async with setup.sessions() as database, database.begin():
        await setup.factory(database).claim(setup.guest.token, setup.state.actor)
    return source


def test_postgres_http_label_etag_library_and_same_tenant_idor(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            submission_id = source["submission_id"]
            transport = httpx.ASGITransport(app=setup.app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as owner:
                owner.cookies.set(setup.settings.session_cookie_name, setup.token)
                listing = await owner.get(PREFIX + "/submissions")
                assert listing.status_code == 200
                row = next(
                    item
                    for item in listing.json()["submissions"]
                    if item["submission_id"] == str(submission_id)
                )
                assert row["display_name"] is None
                assert row["display_name_revision"] == 0

                path = PREFIX + f"/submissions/{submission_id}/label"
                renamed = await owner.patch(
                    path,
                    json={"display_name": "Discovery — 東京 🙂"},
                    headers={"Origin": ORIGIN, "If-Match": '"call-label-0"'},
                )
                assert renamed.status_code == 200, renamed.text
                assert renamed.json() == {
                    "display_name": "Discovery — 東京 🙂",
                    "display_name_revision": 1,
                }
                assert renamed.headers["etag"] == '"call-label-1"'

                retry = await owner.patch(
                    path,
                    json={"display_name": "Discovery — 東京 🙂"},
                    headers={"Origin": ORIGIN, "If-Match": '"call-label-0"'},
                )
                assert retry.status_code == 200
                assert retry.headers["etag"] == '"call-label-1"'
                invalid = await owner.patch(
                    path,
                    json={"display_name": "bad\u0000name"},
                    headers={"Origin": ORIGIN, "If-Match": '"call-label-1"'},
                )
                assert invalid.status_code == 422

                detail = await owner.get(PREFIX + f"/submissions/{submission_id}")
                assert detail.status_code == 200
                assert detail.json()["display_name"] == "Discovery — 東京 🙂"
                assert detail.json()["display_name_revision"] == 1
                # A label revision is not a validator for the changing whole
                # progress representation. Clients use the explicit JSON field.
                assert "etag" not in detail.headers

            stranger = await seed(setup.engine, tenant_id=setup.state.tenant_id)
            stranger_token = await _session(setup, stranger)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as other:
                other.cookies.set(setup.settings.session_cookie_name, stranger_token)
                denied = await other.patch(
                    PREFIX + f"/submissions/{submission_id}/label",
                    json={"display_name": "Foreign change"},
                    headers={"Origin": ORIGIN, "If-Match": '"call-label-1"'},
                )
                assert denied.status_code in (403, 404)
                listing = await other.get(PREFIX + "/submissions")
                assert listing.status_code == 200
                assert listing.json()["submissions"] == []
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_label_revision_lock_owner_gate_and_idempotent_retry(
    postgres_harness: Any, tmp_path: Path, conflicting: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        task: asyncio.Task[Any] | None = None
        try:
            source = await _retained_claimed_submission(setup)
            submission_id = source["submission_id"]
            pid_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()

            async def retry_after_lock() -> Any:
                async with setup.sessions() as second, second.begin():
                    pid_ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                    return await update_submission_label(
                        GuestOwnership(setup.factory(second)),
                        submission_id,
                        actor=setup.state.actor,
                        expected_revision=0,
                        display_name="Competing name" if conflicting else "Discovery — 東京 🙂",
                    )

            async with setup.sessions() as first, first.begin():
                first_result = await update_submission_label(
                    GuestOwnership(setup.factory(first)),
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=0,
                    display_name="Discovery — 東京 🙂",
                )
                task = asyncio.create_task(retry_after_lock())
                blocked_pid = await asyncio.wait_for(pid_ready, timeout=5)
                await wait_blocked(setup.engine, blocked_pid, task)

            assert first_result.revision == 1
            if conflicting:
                with pytest.raises(ConversationConflict):
                    await asyncio.wait_for(task, timeout=5)
            else:
                retry_result = await asyncio.wait_for(task, timeout=5)
                assert retry_result.revision == 1
                assert retry_result.display_name == "Discovery — 東京 🙂"

            async with setup.sessions() as database, database.begin():
                label = await read_submission_label(
                    GuestOwnership(setup.factory(database)),
                    submission_id,
                    actor=setup.state.actor,
                )
                assert label.display_name == "Discovery — 東京 🙂"
                assert label.revision == 1
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationSubmissionLabelRevision)
                        .where(ConversationSubmissionLabelRevision.submission_id == submission_id)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == setup.state.tenant_id,
                            AuditEvent.action == "conversation.submission_label_changed",
                        )
                    )
                    == 1
                )
                assert (await verify_audit_chain(database, setup.state.tenant_id)).valid

            stranger = await seed(setup.engine, tenant_id=setup.state.tenant_id)
            async with setup.sessions() as database, database.begin():
                with pytest.raises((ConversationDenied, ConversationNotFound)):
                    await update_submission_label(
                        GuestOwnership(setup.factory(database)),
                        submission_id,
                        actor=stranger.actor,
                        expected_revision=1,
                        display_name="Not the owner",
                    )
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await setup.engine.dispose()

    run(exercise())


def test_postgres_retention_worker_erases_label_history(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            submission_id = source["submission_id"]
            recording_id = source["recording_id"]
            async with setup.sessions() as database, database.begin():
                owner = GuestOwnership(setup.factory(database))
                for revision, name in enumerate(("First private name", "Second private name")):
                    await update_submission_label(
                        owner,
                        submission_id,
                        actor=setup.state.actor,
                        expected_revision=revision,
                        display_name=name,
                    )
                recording = await database.get(ConversationRecording, recording_id)
                assert recording is not None
                permission = await database.get(ConversationPermission, recording.permission_id)
                assert permission is not None
                deadline = permission.retention_until
            await _reconcile(setup.sessions, setup.state)
            scheduler = ConversationRetentionScheduler(
                setup.sessions, clock=lambda: deadline + timedelta(seconds=1)
            )
            assert await scheduler.step()
            worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await worker.run_once()
            async with setup.sessions() as database, database.begin():
                recording = await database.get(ConversationRecording, recording_id)
                assert recording is not None and recording.state == "deleted"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationSubmissionLabelRevision)
                        .where(ConversationSubmissionLabelRevision.submission_id == submission_id)
                    )
                    == 0
                )
                assert (await verify_audit_chain(database, setup.state.tenant_id)).valid
            assert setup.runtime.storage.list_recording(setup.state.tenant_id, recording_id) == ()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_postgres_recording_erasure_purges_all_label_revisions(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            submission_id: UUID = source["submission_id"]
            recording_id: UUID = source["recording_id"]
            async with setup.sessions() as database, database.begin():
                owner = GuestOwnership(setup.factory(database))
                await update_submission_label(
                    owner,
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=0,
                    display_name="Source-retained name",
                )
                await update_submission_label(
                    owner,
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=1,
                    display_name="Second private revision",
                )
                erased = await erase_submission_labels_for_recording(
                    database, tenant_id=setup.state.tenant_id, recording_id=recording_id
                )
                assert erased == 2
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationSubmissionLabelRevision)
                        .where(ConversationSubmissionLabelRevision.submission_id == submission_id)
                    )
                    == 0
                )
                assert (await verify_audit_chain(database, setup.state.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_postgres_account_erasure_hook_purges_label_history(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            submission_id: UUID = source["submission_id"]
            async with setup.sessions() as database, database.begin():
                owner = GuestOwnership(setup.factory(database))
                await update_submission_label(
                    owner,
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=0,
                    display_name="Private customer label",
                )
                await update_submission_label(
                    owner,
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=1,
                    display_name="Revised private label",
                )

            async with setup.sessions() as database, database.begin():
                # This is the same canonical hook called in the account deletion
                # transaction before membership termination. The private label
                # and its previous revision are removed together.
                await erase_sales_xray_profile(database, person_id=setup.state.person_id)
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationSubmissionLabelRevision)
                        .where(ConversationSubmissionLabelRevision.submission_id == submission_id)
                    )
                    == 0
                )
                assert (await verify_audit_chain(database, setup.state.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())
