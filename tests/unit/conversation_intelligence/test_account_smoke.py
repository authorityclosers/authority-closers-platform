"""Script the QA HTTP contract without live credentials, provider calls or writes."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from ac_platform.conversation_intelligence.account_smoke import (
    ORIGINS,
    PREFIX,
    SmokeFailure,
    account_smoke,
)
from ac_platform.conversation_intelligence.canary_cli import FIXTURE_SHA256
from ac_platform.conversation_intelligence.checkpoints import content_hash
from tests.conversation_overview_fixtures import overview_for


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "missing_coaching",
        "transport_error",
        "wrong_source",
        "wrong_person",
        "wrong_report_revision",
        "wrong_report_submission",
        "stale_report_recording",
        "over_cap",
        "held",
    ],
)
def test_qa_smoke_binds_call_coaching_and_never_retries_an_uncertain_send(monkeypatch, scenario):
    async def exercise():
        person, tenant, recording, run_id = (str(uuid4()) for _ in range(4))
        shown_recording = str(uuid4()) if scenario == "stale_report_recording" else recording
        calls = []
        submission = None
        polls = 0
        projection = {
            "access": "claimed_account",
            "content": {
                "improvements": [],
                "overview": overview_for({"improvements": [], "strengths": []}),
            },
        }

        def response(status, body):
            return httpx.Response(status, json=body)

        def handler(request):
            nonlocal submission, polls
            path = request.url.path
            calls.append((request.method, path))
            assert request.headers["Origin"] == ORIGINS["staging"]
            if path == "/v1/auth/password/login":
                return response(200, {"authenticated": True})
            if path == "/v1/me/workspaces":
                return response(200, {"person_id": person, "selected_tenant_id": tenant})
            if path.endswith("/write-eligibility"):
                return httpx.Response(204)
            if path.endswith("/upload-policy"):
                return response(200, {"policy_sha256": "b" * 64, "retention_days": 7})
            if path.endswith("/source"):
                submission = path.split("/")[-2]
                assert request.headers["X-Source-SHA256"] == FIXTURE_SHA256
                assert request.headers["X-Upload-Consent"] == "accepted"
                return response(202, {"recording_id": recording})
            if path.endswith("/plan/quote"):
                return response(
                    201,
                    {
                        "id": str(uuid4()),
                        "plan_fingerprint": "a" * 64,
                        "privacy_revision": "sales-xray-processing-plan-v1",
                        "max_cost_paise": 45_001 if scenario == "over_cap" else 45_000,
                    },
                )
            if path.endswith("/plan"):
                return response(202, {"accepted": True})
            if path == f"{PREFIX}/submissions/{submission}":
                polls += 1
                return response(
                    200,
                    {
                        "local_state": "completed",
                        "state": "held" if scenario == "held" else "active",
                        "has_report": polls >= 2,
                        "stages": [{"state": "uncertain"}] if scenario == "held" else [],
                    },
                )
            if path.endswith("/report"):
                return response(
                    200,
                    {
                        "source_sha256": FIXTURE_SHA256,
                        "submission_id": str(uuid4())
                        if scenario == "wrong_report_submission"
                        else submission,
                        "recording_id": shown_recording,
                        "run_id": run_id,
                        "transcript_revision": "fictional-revision",
                        "report": projection,
                    },
                )
            if path == f"/v1/me/coaching/calls/{submission}":
                if scenario == "transport_error":
                    raise httpx.ReadTimeout("fictional-untrusted-transport-content")
                return response(
                    404 if scenario == "missing_coaching" else 200,
                    {
                        "schema": "ac.sales-xray.call-coaching/1",
                        "state": "ready",
                        "submission_id": submission,
                        "recording_id": shown_recording,
                        "source_sha256": "f" * 64 if scenario == "wrong_source" else FIXTURE_SHA256,
                        "transcript_revision": "fictional-revision",
                        "report_revision": "f" * 64
                        if scenario == "wrong_report_revision"
                        else content_hash(projection),
                        "authority": "provisional",
                        "person_id": str(uuid4()) if scenario == "wrong_person" else person,
                        "tenant_id": tenant,
                    },
                )
            pytest.fail("Unexpected smoke route")

        async with httpx.AsyncClient(
            base_url=ORIGINS["staging"], transport=httpx.MockTransport(handler)
        ) as client:
            kwargs = dict(
                environment="staging",
                email="fictional+ac-qa-staging@authorityclosers.com",
                password="fictional-placeholder",  # noqa: S106 -- fictional MockTransport only
            )
            if scenario == "success":
                result = await account_smoke(client, **kwargs)
                assert result["report_present"] and result["per_call_coaching_present"]
                assert result["submission_id"] == submission
            else:
                with pytest.raises(SmokeFailure) as failure:
                    await account_smoke(client, **kwargs)
                assert failure.value.submission_id == submission
                assert "untrusted" not in str(failure.value)
        assert sum(method == "PUT" for method, _ in calls) == 1
        if scenario in {"held", "over_cap"}:
            assert not any(path.endswith("/plan") for _, path in calls)

    monkeypatch.setattr(asyncio, "sleep", lambda *args: _no_wait())
    asyncio.run(exercise())


def test_failure_receipt_discards_unrecognized_exception_content():
    failure = SmokeFailure("fictional-untrusted-error-content", submission_id=uuid4())
    assert failure.code == "qa_smoke_failed"
    assert str(failure) == "qa_smoke_failed"
    assert "untrusted" not in str(failure)


async def _no_wait():
    return None


def test_qa_credentials_cannot_be_sent_to_an_arbitrary_origin():
    async def exercise():
        async with httpx.AsyncClient(
            base_url="https://invalid.example.test",
            transport=httpx.MockTransport(lambda request: pytest.fail("credentials sent")),
        ) as client:
            with pytest.raises(SmokeFailure, match="qa_runtime_refused"):
                await account_smoke(
                    client,
                    environment="staging",
                    email="fictional+ac-qa-staging@authorityclosers.com",
                    password="fictional-placeholder",  # noqa: S106 -- no network permitted
                )

    asyncio.run(exercise())
