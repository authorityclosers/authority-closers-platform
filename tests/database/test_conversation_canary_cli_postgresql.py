"""Canary marker, guest usage reservation and queued run commit or roll back together."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.canary_cli import submit
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.signals import file_sha256
from tests.database.test_conversation_canary_account_gate_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_worker_postgresql import _wav_one_second_48k


@pytest.mark.parametrize("commit", [False, True])
def test_marker_and_reservation_are_atomic(
    postgres_harness: Any, tmp_path: Path, commit: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            path = tmp_path / "source.wav"
            path.write_bytes(_wav_one_second_48k())
            upload = NativeUploadPreflight(setup.native).measure(path, uuid4(), file_sha256(path))
            async with setup.sessions() as db:
                transaction = await db.begin()
                await submit(GuestOwnership(setup.factory(db)), setup.runtime, upload, path, "test")
                await transaction.commit() if commit else await transaction.rollback()
            async with setup.sessions() as db:
                for model in (ConversationAcquisitionUsage, ConversationCanarySubmission):
                    count = await db.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            model.submission_id == upload.source.submission_id,
                        )
                    )
                    assert count == int(commit)
        finally:
            await setup.engine.dispose()

    run(exercise())
