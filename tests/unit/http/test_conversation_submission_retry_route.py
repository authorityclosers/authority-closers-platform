"""A progress deadlock retry retains the selected workspace and read authority."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.submission_labels import SubmissionLabel
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_conversation_learner_acquisition import (
    ORGANISATION_TENANT,
    PERSON_ID,
    PUBLIC_TENANT,
    SESSION_ID,
    _Database,
    _runtime,
    _Service,
    _SessionScope,
    _settings,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", [ORGANISATION_TENANT, PUBLIC_TENANT])
async def test_progress_deadlock_retry_keeps_original_owner(tmp_path, monkeypatch, tenant_id):
    database, retry_database = _Database(), _Database()
    database.rollback = AsyncMock()
    actor = ActorContext(PERSON_ID, SESSION_ID, tenant_id)
    submission_id = uuid4()

    async def require_actor(request):
        yield AuthenticatedTransaction(
            database, SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    reads = []

    async def progress(self, requested_id, **arguments):
        reads.append((self.ownership.tenant_id, self.database, arguments))
        assert requested_id == submission_id
        assert self.ownership.tenant_id == actor.tenant_id
        assert arguments == {
            "actor": actor,
            "token": None,
            "shared_identity_locks": True,
            "allow_organisation_read": True,
        }
        if len(reads) == 1:
            error = Exception("fictional deadlock")
            error.sqlstate = "40P01"
            raise DBAPIError(None, None, error)
        return {"submission_id": str(requested_id), "failure_code": None}

    monkeypatch.setattr(AcquisitionReports, "progress", progress)
    label = AsyncMock(return_value=SubmissionLabel("Fictional organisation call", 1))
    monkeypatch.setattr("ac_platform.http.conversation_submissions.read_submission_label", label)
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    app, runtime = FastAPI(), _runtime(tmp_path)
    intake = replace(
        runtime.intake,
        policy=replace(
            runtime.intake.policy, tenant_ids=frozenset({PUBLIC_TENANT, ORGANISATION_TENANT})
        ),
    )
    install_submission_http(
        app,
        settings=_settings(),
        sessions=lambda: _SessionScope(retry_database),
        require_actor=require_actor,
        factory=_Service,
        runtime=intake,
        preflight=runtime.preflight,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as client:
        response = await client.get(f"/v1/conversation/acquisition/submissions/{submission_id}")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "submission_id": str(submission_id),
        "failure_code": None,
        "display_name": "Fictional organisation call",
        "display_name_revision": 1,
    }
    assert [read[1] for read in reads] == [database, retry_database]
    database.rollback.assert_awaited_once_with()
    label.assert_awaited_once()
    assert label.call_args.args[0].tenant_id == tenant_id
    assert label.call_args.args[0].database is retry_database
    assert label.call_args.kwargs == reads[-1][2]
