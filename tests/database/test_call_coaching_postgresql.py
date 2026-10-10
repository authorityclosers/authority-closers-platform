"""Call-level Coaching privacy is checked again even after a cached read."""

from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from tests.database.test_coaching_postgresql import draft_for, install
from tests.database.test_coaching_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


@pytest.mark.parametrize("dimension_evidence", [True, False])
def test_call_coaching_one_report_private_cache_withholding_and_revocation(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any, dimension_evidence: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        reads = []
        original = AcquisitionReports.report

        async def counted(self: Any, submission_id: Any, **kwargs: Any) -> Any:
            reads.append(submission_id)
            return await original(self, submission_id, **kwargs)

        monkeypatch.setattr(AcquisitionReports, "report", counted)
        try:
            call = await direct_call(setup)
            recording_id, revision = await draft_for(
                setup, call, dimension_evidence=dimension_evidence
            )
            path = f"/v1/me/coaching/calls/{call}"
            stranger = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="admin")
            other_token = await _session(setup, stranger)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                assert (await client.get(path)).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                for _ in range(2):
                    response = await client.get(path)
                    assert response.status_code == 200, response.text
                    assert response.headers["cache-control"] == "private, no-store"
                    data = response.json()
                    assert data["schema"] == "ac.sales-xray.call-coaching/1"
                    assert data["state"] == "ready" and data["submission_id"] == str(call)
                    assert data["mission"]["origin_submission_id"] == str(call)
                    assert data["lesson"]["own_call"]["submission_id"] == str(call)
                assert reads == [call, call]  # exactly one selected report per request
                assert (
                    await client.get(path, params={"person_id": str(stranger.person_id)})
                ).status_code == 422
                assert (await client.get("https://admin.example.test" + path)).status_code == 404
                client.cookies.set(setup.settings.session_cookie_name, other_token)
                assert (await client.get(path)).status_code == 404
                assert reads == [call, call]  # admin never reaches the private report
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                async with setup.sessions() as db, db.begin():
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=recording_id,
                        transcript_revision=revision,
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1678",
                        idempotency_key="fictional-call-coaching-sensitive",
                    )
                withheld = (await client.get(path)).json()
                assert withheld["state"] == "unavailable" and withheld["evidence"] == []
                assert "buyer asks" not in str(withheld)
                assert withheld["report_revision"] != data["report_revision"]
                async with setup.sessions() as db, db.begin():
                    recording = await db.get(ConversationRecording, recording_id)
                    permission = await db.get(ConversationPermission, recording.permission_id)
                    permission.revoked_at = setup.clock[0]
                assert (await client.get(path)).status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())
