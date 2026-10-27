"""Google Ads' "Send test data" is stored as test data, on PostgreSQL (owner, 27 Oct 2026).

A lead form's webhook check sends a lead with ``is_test: true``. It is filed with
test_data true, so it sits under Test leads, apart from real leads; a person's lead
from the same form is not.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadSource
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

KEY = "fictional-google-form-key"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _lead(lead_id: str, name: str, phone: str, *, test: bool) -> dict[str, Any]:
    """A lead as a Google Ads lead form's webhook sends it."""
    return {
        "lead_id": lead_id,
        "api_version": "1.0",
        "form_id": 1,
        "campaign_id": 2,
        "google_key": KEY,
        "is_test": test,
        "user_column_data": [
            {"column_id": "FULL_NAME", "column_name": "Full Name", "string_value": name},
            {"column_id": "PHONE_NUMBER", "column_name": "User Phone", "string_value": phone},
        ],
    }


def test_googles_send_test_data_is_stored_as_test_data(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_connectors_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            source_id = uuid4()
            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadSource(
                        id=source_id,
                        tenant_id=setup.state.tenant_id,
                        kind="webhook",
                        label="Google Ads lead form",
                        token_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                        config={},
                        active=True,
                        received=0,
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                path = f"/v1/lead-desk/capture/{source_id}/google-ads"
                for body in (
                    _lead("g-test-1", "Fictional Test", "+919876500031", test=True),
                    _lead("g-person-1", "Fictional Person", "+919876500032", test=False),
                ):
                    sent = await client.post(path, json=body)
                    assert sent.status_code == 200, sent.text
                    assert sent.json()["outcome"] == "created"
            async with setup.sessions() as db:
                rows = (await db.execute(select(Lead.name, Lead.test_data))).all()
            assert dict(rows) == {"Fictional Test": True, "Fictional Person": False}
        finally:
            await setup.engine.dispose()

    run(exercise())
