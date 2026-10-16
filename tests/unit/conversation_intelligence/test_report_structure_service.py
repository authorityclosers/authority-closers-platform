"""Read composition uses existing scoped readers and never issues provider work."""

from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import report_structure_service as service
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
)
from ac_platform.kernel.authz import ActorContext
from tests.unit.conversation_intelligence.test_owner_report_structure import dialogue
from tests.unit.conversation_intelligence.test_report_access import _report


@pytest.fixture
def setup(monkeypatch):
    report = _report()
    source = ReportSourceBinding(uuid4(), uuid4(), report.source_sha256, report.transcript_revision)
    envelope = project_bound_report(report, access=ReportAccess.ACCOUNT, source=source)
    transcript, speakers = dialogue()
    transcript.update(source_sha256=report.source_sha256, revision=report.transcript_revision)
    speakers["transcript_revision"] = transcript["revision"]
    transcript_read = AsyncMock(return_value=transcript)
    speaker_read = AsyncMock(return_value=speakers)
    outcome_read = AsyncMock(
        return_value={"basis": "person", "revision": 1, "value": {"outcome": "won"}}
    )
    monkeypatch.setattr(service.AcquisitionReports, "__init__", lambda *_: None)
    monkeypatch.setattr(service.AcquisitionReports, "transcript", transcript_read)
    monkeypatch.setattr(service, "read_speaker_map", speaker_read)
    monkeypatch.setattr(service.CallOutcomeStore, "read", outcome_read)
    monkeypatch.setattr(service, "ProspectStore", lambda _: object())
    monkeypatch.setattr(service.CallOutcomeStore, "__init__", lambda *_: None)
    actor = ActorContext(uuid4(), uuid4(), uuid4())
    return envelope, object(), uuid4(), actor, transcript_read, speaker_read, outcome_read


async def run(setup):
    envelope, ownership, submission_id, actor, *_ = setup
    return await service.enrich_report_structure(
        envelope, ownership, submission_id, actor=actor, shared_identity_locks=True
    )


async def test_account_enrichment_keeps_scope_binding_input_and_existing_report_fields(setup):
    envelope, ownership, submission_id, actor, transcript, speakers, outcome = setup
    before = deepcopy(envelope)
    result = await run(setup)
    stats = result["report"]["content"]["structure"]["overview"]["call_statistics"]
    assert stats["duration_ms"] == 20000
    assert result["report"]["content"]["structure"]["final_call_outcome"]["outcome"] == "Won"
    assert result["source_sha256"] == envelope["source_sha256"]
    assert result["report"]["content"]["summary"] == envelope["report"]["content"]["summary"]
    assert envelope == before
    for read in (transcript, speakers):
        assert read.await_args.kwargs == {
            "actor": actor,
            "shared_identity_locks": True,
            "allow_organisation_read": True,
        }
        assert read.await_args.args[-1] == submission_id
    outcome.assert_awaited_once_with(actor, submission_id)


@pytest.mark.parametrize("mode", ["guest", "no_actor", "older_response"])
async def test_guest_and_older_readers_are_unchanged_and_do_no_extra_reads(setup, mode):
    envelope, ownership, submission_id, actor, *reads = setup
    if mode == "guest":
        envelope["report"]["access"] = "guest_preview"
    elif mode == "no_actor":
        actor = None
    else:
        envelope["report"]["content"].pop("structure")
    assert (
        await service.enrich_report_structure(envelope, ownership, submission_id, actor=actor)
        is envelope
    )
    for read in reads:
        read.assert_not_awaited()


@pytest.mark.parametrize("field", ["source_sha256", "revision"])
async def test_other_source_or_revision_cannot_supply_statistics(setup, field):
    setup[4].return_value[field] = "different"
    result = await run(setup)
    assert (
        result["report"]["content"]["structure"]["overview"]["call_statistics"]["status"]
        == "unavailable"
    )
    setup[5].assert_not_awaited()
    assert result["report"]["content"]["structure"]["final_call_outcome"]["outcome"] == "Won"


@pytest.mark.parametrize("error", [ConversationNotFound, ConversationConflict])
async def test_missing_optional_context_preserves_report_with_explicit_gaps(setup, error):
    setup[4].side_effect = error("unavailable")
    setup[6].side_effect = error("unavailable")
    result = await run(setup)
    structure = result["report"]["content"]["structure"]
    assert len(structure["pointers"]) == 27
    assert structure["overview"]["call_statistics"]["status"] == "unavailable"
    assert structure["final_call_outcome"]["status"] == "unavailable"


async def test_missing_optional_speaker_map_keeps_measured_speaker_data(setup):
    setup[5].side_effect = ConversationNotFound("No map yet")
    result = await run(setup)
    stats = result["report"]["content"]["structure"]["overview"]["call_statistics"]
    assert stats["speakers"][0]["talk_ms"] == 12000
    assert stats["talk_share_percent"] == {"rep": None, "prospect": None}


async def test_authorization_denial_does_not_turn_into_partial_success(setup):
    setup[4].side_effect = ConversationDenied("Call access revoked")
    with pytest.raises(ConversationDenied):
        await run(setup)
    setup[6].assert_not_awaited()


async def test_existing_report_http_route_serves_extension_with_private_headers_and_auth(
    setup, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from ac_platform.http import conversation_submissions as http
    from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
    from ac_platform.http.conversation_acquisition_runtime import install_acquisition_runtime
    from ac_platform.http.problem import register_problem_handlers
    from ac_platform.identity.application import ResolvedActorContext
    from tests.unit.http.test_conversation_learner_acquisition import (
        PERSON_ID,
        PUBLIC_TENANT,
        SESSION_ID,
        _Database,
        _runtime,
        _SessionScope,
        _settings,
    )

    envelope, _, submission_id, _, *_ = setup
    database = _Database()
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)

    async def require_actor(request):
        if request.headers.get("x-test-auth") != "valid":
            raise AuthenticationRequired("Sign in")
        yield AuthenticatedTransaction(
            database,
            SimpleNamespace(),
            ResolvedActorContext(
                actor=actor, membership_role="learner", person_revision=1, session_revision=1
            ),
            "fictional-session",
        )

    read = AsyncMock(return_value=envelope)
    monkeypatch.setattr(service.AcquisitionReports, "report", read)
    monkeypatch.setattr(
        http,
        "read_submission_label",
        AsyncMock(return_value=SimpleNamespace(display_name="Fictional call", revision=2)),
    )
    app = FastAPI()
    register_problem_handlers(app)
    install_acquisition_runtime(
        app,
        settings=_settings(),
        sessions=lambda: _SessionScope(database),
        require_actor=require_actor,
        runtime=_runtime(tmp_path),
    )
    path = f"/v1/conversation/acquisition/submissions/{submission_id}/report"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as client:
        denied = await client.get(path)
        assert denied.status_code == 401
        read.assert_not_awaited()
        response = await client.get(path, headers={"x-test-auth": "valid"})
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    payload = response.json()
    assert payload["display_name"] == "Fictional call"
    structure = payload["report"]["content"]["structure"]
    assert len(structure["pointers"]) == 27
    assert structure["overview"]["call_statistics"]["duration_ms"] == 20000
    assert structure["final_call_outcome"]["outcome"] == "Won"
    assert read.await_args.kwargs["actor"] == actor
    assert read.await_args.kwargs["allow_organisation_read"] is True
