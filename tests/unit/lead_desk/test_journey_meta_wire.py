"""Lead stages to Meta, end to end on the wire (16 Nov 2026, Wise Life and iSolar Power).

The path production uses: a Meta lead-form lead's stage -> the confirmed event name ->
one Conversions API for CRM event -> the workspace's own dataset, with the workspace's
sealed Meta connection. Meta's answers are recorded shapes; no test calls Meta.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

from ac_platform.lead_desk.connectors import meta, meta_capi
from ac_platform.lead_desk.journey import mapping
from ac_platform.lead_desk.journey.model import Journey, default_journey
from ac_platform.lead_desk.journey.providers import Answer, event_id
from ac_platform.lead_desk.journey.providers import meta as provider

KEY = base64.urlsafe_b64encode(b"w" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
TENANT = UUID("00000000-0000-4000-8000-00000000a001")
OTHER = UUID("00000000-0000-4000-8000-00000000a002")
LEAD = UUID("00000000-0000-4000-8000-00000000a0e1")
META_LEAD_ID = "120000000000777"
DATASET = "555000111222333"
TOKEN = "fake-user-token"  # noqa: S105 - a stand-in, never a real token
CAPTURED = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)

# The matches Wise Life confirmed (production settings, 2 Nov 2026): the desk's stages
# by their own names, "Lead" first, Couldn't reach never sent.
CONFIRMED: dict[str, str | None] = {
    "new": "Lead",
    "interested": "Interested",
    "follow_up": "Follow-up",
    "won": "Won",
    "lost": "Lost",
    "not_connected": None,
}

# Meta's answers to POST /{dataset}/events, as Meta sends them.
RECORDED: dict[str, tuple[int, dict[str, Any]]] = {
    "received": (200, {"events_received": 1, "messages": [], "fbtrace_id": "AbC123recorded"}),
    "token_expired": (
        400,
        {
            "error": {
                "message": "Error validating access token: Session has expired.",
                "type": "OAuthException",
                "code": 190,
                "error_subcode": 463,
                "fbtrace_id": "AbC190recorded",
            }
        },
    ),
    "no_permission": (
        403,
        {"error": {"message": "Permissions error", "type": "OAuthException", "code": 200}},
    ),
    "meta_busy": (
        500,
        {"error": {"message": "An unknown error occurred", "code": 1, "is_transient": True}},
    ),
    "bad_event": (
        400,
        {"error": {"message": "Invalid parameter", "type": "OAuthException", "code": 100}},
    ),
}


@pytest.fixture(autouse=True)
def meta_app(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


def workspace_config() -> dict[str, Any]:
    cfg = meta.config(ENV)
    assert cfg is not None
    sealed = meta.seal(cfg.token_key, TOKEN, page_id=meta_capi.connection_bound(TENANT))
    return {meta_capi.CONNECTION: {"token": sealed, "at": 1, "by": "x", "expires_at": None}}


def journey() -> Journey:
    return Journey(1, None, default_journey().stages)


def meta_lead() -> Any:
    return SimpleNamespace(
        id=LEAD,
        source="meta",
        source_ref=META_LEAD_ID,
        email="Buyer@Example.test",
        phone="+919812345678",
        payload={},
        created_at=CAPTURED,
        test_data=False,
    )


def send(
    config: dict[str, Any], body: dict[str, Any], answer: str, tenant: UUID = TENANT
) -> tuple[Answer, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    status, reply = RECORDED[answer]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=reply)

    async def go() -> Answer:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await provider.send(
                client,
                config=config,
                tenant_id=tenant,
                destination=DATASET,
                payload=body,
                test_code=None,
            )

    return asyncio.run(go()), seen


def test_the_confirmed_matches_are_live_stages_of_the_desk() -> None:
    live = {stage.key for stage in journey().live}
    assert set(CONFIRMED) <= live
    assert mapping.clean_events("meta", journey(), CONFIRMED) == CONFIRMED


def test_a_workspace_without_its_own_switch_sends_nothing() -> None:
    # iSolar Power today: connected to Meta, no ad platform switched on.
    config = workspace_config()
    assert provider.connected(config, TENANT)
    assert mapping.read(config, "meta").ready is False
    assert mapping.any_on(config) is False
    # Matches confirmed but sending still off: nothing goes.
    confirmed = mapping.confirmed(config, "meta", journey(), CONFIRMED, by=TENANT, now=10)
    saved = mapping.destination_saved(
        confirmed,
        "meta",
        destination_id=DATASET,
        destination_name="iSolar dataset",
        on=False,
        test_code=None,
        now=10,
    )
    assert mapping.read(saved, "meta").ready is False
    on = mapping.destination_saved(
        saved,
        "meta",
        destination_id=DATASET,
        destination_name="iSolar dataset",
        on=True,
        test_code=None,
        now=20,
    )
    ready = mapping.read(on, "meta")
    assert ready.ready and ready.since == 20 and ready.destination_id == DATASET


def test_each_stage_a_meta_lead_reaches_goes_to_the_workspaces_dataset() -> None:
    config = workspace_config()
    who = provider.identity(meta_lead())
    assert who is not None
    for step, (stage, name) in enumerate(
        [("new", "Lead"), ("interested", "Interested"), ("won", "Won")]
    ):
        at = CAPTURED + timedelta(hours=step)
        assert CONFIRMED[stage] == name
        body = provider.body(who, event_name=name, at=at)
        assert body["event_name"] == name
        assert body["event_time"] == int(at.timestamp())
        assert body["action_source"] == "system_generated"
        assert body["user_data"]["lead_id"] == int(META_LEAD_ID)
        assert body["custom_data"] == {
            "event_source": "crm",
            "lead_event_source": meta_capi.CRM_NAME,
        }
        assert body["event_id"] == event_id("meta", META_LEAD_ID, name)

        answer, seen = send(config, body, "received")
        assert answer.delivered and answer.http_status == 200
        assert answer.trace_id == "AbC123recorded"
        request = seen[0]
        assert request.method == "POST" and request.url.path.endswith(f"/{DATASET}/events")
        form = parse_qs(request.content.decode())
        assert json.loads(form["data"][0]) == [body]
        assert form["access_token"] == [TOKEN]
        assert "test_event_code" not in form


def test_no_personal_words_go_only_the_lead_id_and_hashes() -> None:
    who = provider.identity(meta_lead())
    assert who is not None
    wire = json.dumps(provider.body(who, event_name="Won", at=CAPTURED))
    assert "Buyer@Example.test".lower() not in wire.lower()
    assert "9812345678" not in wire


@pytest.mark.parametrize(
    "answer, code, wait",
    [
        ("token_expired", "meta_190", "customer"),
        ("no_permission", "meta_200", "customer"),
        ("meta_busy", "meta_1", "retry"),
        ("bad_event", "meta_100", "never"),
    ],
)
def test_metas_recorded_refusals_say_retry_wait_for_the_customer_or_never(
    answer: str, code: str, wait: str
) -> None:
    who = provider.identity(meta_lead())
    assert who is not None
    body = provider.body(who, event_name="Interested", at=CAPTURED)
    said, _ = send(workspace_config(), body, answer)
    assert (said.delivered, said.error_code, said.wait) == (False, code, wait)


def test_a_connection_from_another_workspace_is_never_used() -> None:
    who = provider.identity(meta_lead())
    assert who is not None
    body = provider.body(who, event_name="Lead", at=CAPTURED)
    said, seen = send(workspace_config(), body, "received", tenant=OTHER)
    assert (said.error_code, said.wait) == ("not_connected", "customer")
    assert seen == []


def test_leads_that_did_not_come_from_a_meta_form_or_ad_are_not_sent() -> None:
    other = meta_lead()
    other.source = "manual"
    assert provider.identity(other) is None
    no_id = meta_lead()
    no_id.source_ref = "sheet-row-12"
    assert provider.identity(no_id) is None
