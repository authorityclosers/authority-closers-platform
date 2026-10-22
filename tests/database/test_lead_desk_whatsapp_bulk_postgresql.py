"""One approved WhatsApp template to many leads, inside WhatsApp's rules (PostgreSQL,
22 Oct 2026): only leads with a recorded yes get it; a recorded no, no answer, no
WhatsApp number or a lead not on the desk is skipped with its reason; the send must
quote the count the preview showed; a retry sends nothing twice.
"""

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.whatsapp import cloud
from ac_platform.lead_desk.whatsapp.http import install_whatsapp_http
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation
from tests.database.test_lead_desk_whatsapp_postgresql import (
    BASE,
    ENV,
    NUMBER_ID,
    WABA_ID,
    WELCOME,
    WRITE,
    FakeCloud,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_one_template_to_many_leads_who_said_yes(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cloud, "Cloud", FakeCloud)
    FakeCloud.sent = []
    FakeCloud.templates_at_meta = [WELCOME]

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
            install_whatsapp_http(
                setup.app, RouteContext(settings, setup.require_actor, setup.sessions)
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                connected = await client.post(
                    f"{BASE}/whatsapp/connect",
                    json={"code": "signup-code", "wabaId": WABA_ID, "phoneNumberId": NUMBER_ID},
                    headers=WRITE,
                )
                assert connected.status_code == 200, connected.text

                async def add(name: str, phone: str | None) -> str:
                    body = {"command_id": str(uuid4()), "name": name, "assign": "me"}
                    if phone:
                        body["phone"] = phone
                    made = await client.post(f"{BASE}/leads", json=body, headers=WRITE)
                    assert made.status_code == 201, made.text
                    return str(made.json()["lead"]["lead_id"])

                yes = await add("Asha Fictional", "98765 11111")
                quiet = await add("Ravi Sample", "98765 22222")
                stop = await add("Meera Example", "98765 33333")
                no_phone = await add("Karan Example", None)
                for lead_id, agreed in ((yes, True), (stop, False)):
                    said = await client.post(
                        f"{BASE}/leads/{lead_id}/whatsapp/opt-in",
                        json={"commandId": str(uuid4()), "agreed": agreed, "how": "On the call"},
                        headers=WRITE,
                    )
                    assert said.status_code == 200, said.text

                ask = {
                    "leadIds": [yes, quiet, stop, no_phone, str(uuid4())],
                    "template": "welcome_lead",
                    "language": "en",
                    "values": ["{name}"],
                }
                preview = await client.post(
                    f"{BASE}/leads/bulk-whatsapp/preview", json=ask, headers=WRITE
                )
                assert preview.status_code == 200, preview.text
                plan = preview.json()
                assert plan["ready"] == 1 and plan["sent"] == 0
                assert {item["reason"]: item["count"] for item in plan["skipped"]} == {
                    "no_yes": 1,
                    "said_stop": 1,
                    "no_whatsapp": 1,
                    "not_here": 1,
                }
                assert plan["text"].startswith("Hi {name}, thanks")
                assert FakeCloud.sent == []

                command = str(uuid4())
                stale = await client.post(
                    f"{BASE}/leads/bulk-whatsapp",
                    json={**ask, "commandId": command, "confirm": 2},
                    headers=WRITE,
                )
                assert stale.status_code == 409 and FakeCloud.sent == []
                sent = await client.post(
                    f"{BASE}/leads/bulk-whatsapp",
                    json={**ask, "commandId": command, "confirm": 1},
                    headers=WRITE,
                )
                assert sent.status_code == 200, sent.text
                assert (sent.json()["sent"], sent.json()["failed"]) == (1, 0)
                assert len(FakeCloud.sent) == 1
                assert FakeCloud.sent[0]["template"] == "welcome_lead"
                assert FakeCloud.sent[0]["values"][0].lower() == "asha"
                # The same send again: nothing goes twice.
                again = await client.post(
                    f"{BASE}/leads/bulk-whatsapp",
                    json={**ask, "commandId": command, "confirm": 1},
                    headers=WRITE,
                )
                assert again.status_code == 200 and len(FakeCloud.sent) == 1
                wrong = await client.post(
                    f"{BASE}/leads/bulk-whatsapp/preview",
                    json={**ask, "template": "site_visit"},
                    headers=WRITE,
                )
                assert wrong.status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
