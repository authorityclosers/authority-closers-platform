"""Leads Meta's testing tools make are stored as test data, on PostgreSQL, Meta faked.

Meta's Lead Ads Testing Tool (and a form's test lead from Connected apps) sends a lead
whose answers are "<test lead: dummy data for …>". Whether it comes by webhook or by
the scheduled pull, it is filed with test_data true, so it stays out of partner sends
and SLA reports; a person's lead from the same Page is not.
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.connectors import meta, meta_pull
from ac_platform.lead_desk.connectors.http import install_connectors_http
from ac_platform.lead_desk.models import Lead, LeadSource
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
PAGE_TOKEN = "page-token-1"  # noqa: S105 - a fake Page's token


def _made_up(lead_id: str) -> dict[str, Any]:
    """A lead as Meta's Lead Ads Testing Tool sends it."""
    return {
        "id": lead_id,
        "created_time": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime()),
        "form_id": "fa",
        "is_organic": True,
        "field_data": [
            {"name": "email", "values": ["test@meta.com"]},
            {"name": "full_name", "values": ["<test lead: dummy data for full_name>"]},
            {"name": "phone_number", "values": ["<test lead: dummy data for phone_number>"]},
        ],
    }


HOOKED_TEST = _made_up("200000000000001")
PERSON = {
    "id": "200000000000002",
    "created_time": time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime()),
    "form_id": "fa",
    "is_organic": False,
    "platform": "fb",
    "ad_id": "300000000000001",
    "field_data": [
        {"name": "full_name", "values": ["Fictional Person"]},
        {"name": "phone_number", "values": ["+919999000001"]},
    ],
}
PULLED_TEST = _made_up("200000000000003")


class FakeGraph:
    """Meta's Graph API for one Page with one form."""

    def __init__(self, cfg: meta.MetaConfig, client: Any = None) -> None:
        self.cfg = cfg

    async def lead(self, leadgen_id: str, page_token: str) -> dict[str, Any]:
        assert page_token == PAGE_TOKEN
        return {lead["id"]: lead for lead in (HOOKED_TEST, PERSON)}[leadgen_id]

    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]:
        return [{"id": "fa", "name": "Enquiry", "status": "ACTIVE"}]

    async def recent_leads(
        self, form_ids: list[str], page_token: str, *, since: int, limit: int = 1000
    ) -> list[dict[str, Any]]:
        return [PULLED_TEST]


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _signed(payload: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    digest = hmac.new(ENV["AC_META_APP_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    return body, {"content-type": "application/json", "x-hub-signature-256": f"sha256={digest}"}


def test_leads_from_metas_testing_tools_are_stored_as_test_data(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(meta, "Graph", FakeGraph)
    cfg = meta.config()
    assert cfg is not None

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
                        kind="meta",
                        label="Meta · Fictional Homes",
                        token_sha256=None,
                        config={
                            "page_id": "p1",
                            "page_name": "Fictional Homes",
                            "token": meta.seal(cfg.token_key, PAGE_TOKEN, page_id="p1"),
                            "forms": "all",
                            "last_pulled_at": int(time.time()),
                        },
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
                # Meta's webhook brings in a testing-tool lead and a person's lead.
                body, headers = _signed(
                    {
                        "object": "page",
                        "entry": [
                            {
                                "id": "p1",
                                "changes": [
                                    {
                                        "field": "leadgen",
                                        "value": {
                                            "leadgen_id": lead["id"],
                                            "page_id": "p1",
                                            "form_id": "fa",
                                        },
                                    }
                                    for lead in (HOOKED_TEST, PERSON)
                                ],
                            }
                        ],
                    }
                )
                hooked = await client.post(
                    "/v1/lead-desk/meta/webhook", content=body, headers=headers
                )
                assert hooked.status_code == 200, hooked.text
                assert hooked.json() == {"received": 2, "filed": 2}

                # The scheduled pull brings in another testing-tool lead.
                async with setup.sessions() as db, db.begin():
                    source = await db.get(LeadSource, source_id)
                    assert source is not None
                    source.config = {**source.config, "last_pulled_at": 1}
                pulled = await meta_pull.pull_due(
                    setup.sessions, cfg, FakeGraph(cfg), now=int(time.time())
                )
                assert pulled == 1

                async with setup.sessions() as db:
                    rows = (
                        await db.execute(select(Lead.source_ref, Lead.test_data, Lead.id))
                    ).all()
                stored = {ref: test for ref, test, _ in rows}
                assert stored == {
                    HOOKED_TEST["id"]: True,
                    PERSON["id"]: False,
                    PULLED_TEST["id"]: True,
                }

                # They are what the Test data filter shows, and a person's lead isn't.
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                tests = await client.get("/v1/lead-desk/leads?scope=team&test=only")
                assert tests.status_code == 200, tests.text
                assert {row["lead_id"] for row in tests.json()["leads"]} == {
                    str(lead_id) for _, test, lead_id in rows if test
                }
        finally:
            await setup.engine.dispose()

    run(exercise())
