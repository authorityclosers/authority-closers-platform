"""Only an admitted, marked, unclaimed recording bypasses the account hold."""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from ac_platform.conversation_intelligence.canary import mark_canary_submission
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.worker_account_gate import (
    AccountProfileRequired,
    require_recording_owner_profile,
)
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("mode", ["unmarked", "marked", "other_recording", "claimed"])
def test_canary_account_gate(postgres_harness: Any, tmp_path: Path, mode: str) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _seed_retained_guest_submission(setup)
            marker = (
                await _seed_retained_guest_submission(setup)
                if mode == "other_recording"
                else source
            )
            async with setup.sessions() as db, db.begin():
                recording = await db.get(ConversationRecording, source["recording_id"])
                if mode != "unmarked":
                    await mark_canary_submission(
                        db,
                        tenant_id=setup.state.tenant_id,
                        submission_id=marker["submission_id"],
                        environment="test",
                        fixture_sha256=recording.source_sha256,
                        created_at=setup.state.now,
                    )
                if mode == "claimed":
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                    await db.execute(
                        update(SalesXrayProfile)
                        .where(SalesXrayProfile.person_id == setup.state.person_id)
                        .values(phone_number_e164=None)
                    )
                if mode == "marked":
                    await require_recording_owner_profile(db, recording, now=setup.state.now)
                else:
                    code = "profile_incomplete" if mode == "claimed" else "account_required"
                    with pytest.raises(AccountProfileRequired, match=f"sales_xray_{code}"):
                        await require_recording_owner_profile(db, recording, now=setup.state.now)
        finally:
            await setup.engine.dispose()

    run(exercise())
