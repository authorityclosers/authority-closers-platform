"""Admin's AI spend view and its one-click caps on PostgreSQL (owner, 20 Oct 2026).

Disposable loopback PostgreSQL, fictional rows only. The operations-control check
has its own tests; here the test's own workspace is the operations workspace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select

from ac_platform.ai_spend import admin_http
from ac_platform.audit.models import AuditEvent
from ac_platform.http.routes import RouteContext
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
ADMIN = "/v1/admin/ai-spend"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class _Admitted:
    def __init__(self, application: Any) -> None:
        pass

    async def admit(self, actor: Any) -> None:
        return None


def test_admin_sees_where_ai_money_goes_and_raises_caps_in_one_click(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin_http, "ConversationProviderAdmin", _Admitted)
    monkeypatch.setattr(admin_http, "require_admin_surface", lambda request, settings: None)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            staff = RouteContext(
                setup.settings.model_copy(update={"operations_tenant_id": setup.state.tenant_id}),
                setup.require_actor,
                setup.sessions,
            )
            admin_http.install_ai_spend_admin_http(setup.app, staff)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as http:
                http.cookies.set(setup.settings.session_cookie_name, setup.token)
                view = (await http.get(ADMIN)).json()
                # A test run reads as development: the tightest defaults.
                assert view["environment"] == "development"
                assert view["settings"]["revision"] is None
                assert view["settings"]["config"]["background_enabled"] is False
                assert view["days"] == 14
                assert {line["target"] for line in view["caps"]} == {
                    "daily",
                    "monthly",
                    "backfill",
                    "canary",
                    "pointer_review",
                    "partner_quote_facts",
                }
                assert [line["feature"] for line in view["elsewhere"]] == [
                    "call_data_fast",
                    "call_data_deep",
                    "lead_desk_ai",
                ]
                assert view["window"]["total_inr"] == 0
                assert (await http.get(ADMIN, params={"days": 5})).status_code == 422
                assert (await http.get(ADMIN, params={"tenant": "x"})).status_code == 422

                raised = await http.post(
                    f"{ADMIN}/raise",
                    json={"expected_revision": None, "target": "daily"},
                    headers=WRITE,
                )
                assert raised.status_code == 200, raised.text
                settings = raised.json()["settings"]
                assert settings["revision"] == 1
                assert settings["config"]["daily_cap_inr"] == 100
                assert settings["history"][0]["reason"] == "Raised daily from ₹50 to ₹100"
                stale = await http.post(
                    f"{ADMIN}/raise",
                    json={"expected_revision": None, "target": "daily"},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                lower = await http.post(
                    f"{ADMIN}/raise",
                    json={"expected_revision": 1, "target": "daily", "cap_inr": 50},
                    headers=WRITE,
                )
                assert lower.status_code == 422

                saved = await http.put(
                    f"{ADMIN}/settings",
                    json={
                        "expected_revision": 1,
                        "config": {**settings["config"], "background_enabled": True},
                        "reason": "Lead card demo on dev",
                    },
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert saved.json()["settings"]["config"]["background_enabled"] is True
                assert saved.json()["settings"]["config"]["daily_cap_inr"] == 100
                bad = await http.put(
                    f"{ADMIN}/settings",
                    json={"expected_revision": 2, "config": {"daily_cap_inr": -5}},
                    headers=WRITE,
                )
                assert bad.status_code == 422
            async with setup.sessions() as db:
                audited = (
                    await db.execute(
                        select(AuditEvent.action, AuditEvent.payload)
                        .where(AuditEvent.resource_type == "ai_spend_settings")
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
            assert [action for action, _ in audited] == [
                "ai_spend.cap_raised",
                "ai_spend.settings_saved",
            ]
            assert audited[0][1]["old"]["daily_cap_inr"] == 50
            assert audited[0][1]["new"]["daily_cap_inr"] == 100
        finally:
            await setup.engine.dispose()

    run(exercise())
