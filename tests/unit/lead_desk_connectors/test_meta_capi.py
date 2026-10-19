"""Lead stages back to Meta (Conversions API for CRM): what is sent, and nothing more."""

import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest

from ac_platform.lead_desk.connectors import meta, meta_capi

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
ENV = {
    "AC_META_APP_ID": "1234567890",
    "AC_META_APP_SECRET": "app-secret",
    "AC_META_LOGIN_CONFIG_ID": "987654321",
    "AC_META_WEBHOOK_VERIFY_TOKEN": "verify-me",
    "AC_LEAD_DESK_TOKEN_KEY": KEY,
}
AT = datetime(2027, 1, 15, 10, 0, tzinfo=UTC)
LEAD_ID = "123456789012345"
TOKEN = "fake-user-token"  # noqa: S105 - a stand-in, never a real token


def cfg() -> meta.MetaConfig:
    value = meta.config(ENV)
    assert value is not None
    return value


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_email_and_phone_are_normalised_the_way_meta_asks_then_hashed() -> None:
    assert meta_capi.hashed_email("  Asha.Patil@Example.COM ") == sha("asha.patil@example.com")
    assert meta_capi.hashed_email("not an email") is None
    assert meta_capi.hashed_email(None) is None
    assert meta_capi.hashed_phone("+91 98765-43210") == sha("919876543210")
    assert meta_capi.hashed_phone("12") is None


def test_an_event_carries_metas_lead_id_and_hashes_only() -> None:
    body = meta_capi.event_body(
        meta_lead_id=LEAD_ID,
        email="asha@example.com",
        phone="+919876543210",
        event_name="Won",
        at=AT,
    )
    assert body == {
        "event_name": "Won",
        "event_time": int(AT.timestamp()),
        "event_id": meta_capi.event_id(LEAD_ID, "Won"),
        "action_source": "system_generated",
        "user_data": {
            "lead_id": 123456789012345,
            "em": [sha("asha@example.com")],
            "ph": [sha("919876543210")],
        },
        "custom_data": {"event_source": "crm", "lead_event_source": "Sales Xray"},
    }
    text = json.dumps(body)
    assert "asha@example.com" not in text and "9876543210" not in text


def test_the_same_lead_and_stage_always_get_the_same_event_id() -> None:
    assert meta_capi.event_id(LEAD_ID, "Won") == meta_capi.event_id(LEAD_ID, "Won")
    assert meta_capi.event_id(LEAD_ID, "Won") != meta_capi.event_id(LEAD_ID, "Lost")


@pytest.mark.parametrize(
    "kind, data, stage",
    [
        ("captured", {}, "new"),
        ("repeat", {"reopened": True}, "new"),
        ("repeat", {"reopened": False}, None),
        ("result", {"stage": "won", "from_stage": "interested"}, "won"),
        ("result", {"stage": "follow_up", "from_stage": "follow_up"}, None),
        ("note", {}, None),
    ],
)
def test_which_lead_desk_events_move_a_lead(kind: str, data: dict, stage: str | None) -> None:
    assert meta_capi.stages_reached(kind, data) == stage


def test_a_funnel_stage_brings_the_stages_a_lead_skipped() -> None:
    assert meta_capi.with_earlier("won") == ["new", "follow_up", "interested", "won"]
    assert meta_capi.with_earlier("follow_up") == ["new", "follow_up"]
    assert meta_capi.with_earlier("lost") == ["lost"]
    assert meta_capi.with_earlier("not_connected") == ["not_connected"]


def test_stage_names_have_defaults_and_can_be_renamed_or_switched_off() -> None:
    assert meta_capi.clean_events(None) == meta_capi.DEFAULT_EVENTS
    assert meta_capi.DEFAULT_EVENTS["not_connected"] is None
    named = meta_capi.clean_events({"won": " Converted ", "lost": "", "interested": None})
    assert (named["won"], named["lost"], named["interested"]) == ("Converted", None, None)


@pytest.mark.parametrize(
    "events",
    [
        {"won": "Lead"},  # the same name twice
        {"won": "<script>"},
        {"won": "x" * 51},
        {"booked": "Booked"},  # not a CRM stage
    ],
)
def test_bad_stage_names_are_refused(events: dict) -> None:
    with pytest.raises(meta_capi.ConversionsError):
        meta_capi.clean_events(events)


def test_turning_sending_on_starts_from_now_and_later_edits_keep_the_start() -> None:
    by = uuid4()
    first = meta_capi.saved(
        {},
        dataset_id="555000111",
        dataset_name="CRM",
        on=True,
        events=None,
        test_code=None,
        now=1000,
        by=by,
    )
    settings = meta_capi.read_settings(first)
    assert settings is not None and (settings.on, settings.since) == (True, 1000)
    first[meta_capi.KEY]["cursor"] = {"at": AT.isoformat(), "id": str(uuid4())}
    renamed = meta_capi.saved(
        first,
        dataset_id="555000111",
        dataset_name="CRM",
        on=True,
        events={"won": "Converted"},
        test_code="TEST123",
        now=2000,
        by=by,
    )
    settings = meta_capi.read_settings(renamed)
    assert settings is not None
    assert (settings.since, settings.events["won"], settings.test_code) == (
        1000,
        "Converted",
        "TEST123",
    )
    assert settings.cursor is not None
    other = meta_capi.saved(
        renamed,
        dataset_id="555000222",
        dataset_name="Other",
        on=True,
        events=None,
        test_code=None,
        now=3000,
        by=by,
    )
    settings = meta_capi.read_settings(other)
    assert settings is not None and (settings.since, settings.cursor) == (3000, None)


@pytest.mark.parametrize(
    "dataset_id, test_code",
    [("abc", None), ("555000111", "bad code!")],
)
def test_a_bad_dataset_or_test_code_is_refused(dataset_id: str, test_code: str | None) -> None:
    with pytest.raises(meta_capi.ConversionsError):
        meta_capi.saved(
            {},
            dataset_id=dataset_id,
            dataset_name="x",
            on=True,
            events=None,
            test_code=test_code,
            now=1,
            by=uuid4(),
        )


@pytest.mark.parametrize(
    "status, body, delivered, wait, code",
    [
        (200, {"events_received": 1, "fbtrace_id": "T1"}, True, "retry", None),
        (200, {"events_received": 0}, False, "retry", "not_received"),
        (400, {"error": {"code": 190, "fbtrace_id": "T2"}}, False, "customer", "meta_190"),
        (403, {"error": {"code": 200}}, False, "customer", "meta_200"),
        (400, {"error": {"code": 2}}, False, "retry", "meta_2"),
        (400, {"error": {"code": 17}}, False, "retry", "meta_17"),
        (503, {}, False, "retry", "http_503"),
        (429, {}, False, "retry", "http_429"),
        (400, {"error": {"code": 100}}, False, "never", "meta_100"),
    ],
)
def test_metas_answer_says_delivered_retry_wait_or_never(
    status: int, body: dict, delivered: bool, wait: str, code: str | None
) -> None:
    answer = meta_capi.read_answer(status, body, 12)
    assert answer.delivered is delivered
    assert answer.error_code == code
    if not delivered:
        assert answer.wait == wait


def test_one_event_goes_to_the_datasets_events_edge_with_the_test_code() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"events_received": 1, "fbtrace_id": "Tx"})

    body = meta_capi.event_body(
        meta_lead_id=LEAD_ID, email=None, phone=None, event_name="Lead", at=AT
    )

    async def send() -> meta_capi.Answer:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await meta_capi.post_event(
                client, cfg(), dataset_id="555000111", token=TOKEN, body=body, test_code="TEST1"
            )

    answer = asyncio.run(send())
    assert answer.delivered and answer.fbtrace_id == "Tx" and answer.events_received == 1
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/v23.0/555000111/events"
    form = parse_qs(request.content.decode())
    assert json.loads(form["data"][0]) == [body]
    assert form["test_event_code"] == ["TEST1"] and form["access_token"] == [TOKEN]


def test_a_timeout_is_tried_again() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async def send() -> meta_capi.Answer:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await meta_capi.post_event(
                client, cfg(), dataset_id="555000111", token=TOKEN, body={}, test_code=None
            )

    answer = asyncio.run(send())
    assert (answer.delivered, answer.error_code, answer.wait) == (False, "timeout", "retry")


def test_retries_wait_longer_each_time_up_to_an_hour() -> None:
    assert meta_capi.retry_delay(1) == timedelta(seconds=30)
    assert meta_capi.retry_delay(3) == timedelta(seconds=120)
    assert meta_capi.retry_delay(20) == timedelta(hours=1)


def test_the_connection_token_is_sealed_to_its_organisation() -> None:
    tenant = uuid4()
    box = meta.seal(cfg().token_key, "user-token", page_id=meta_capi.connection_bound(tenant))
    config = {meta_capi.CONNECTION: {"token": box}}
    assert meta_capi.connection_token(config, cfg(), tenant) == "user-token"
    assert meta_capi.connection_token(config, cfg(), uuid4()) is None
    assert meta_capi.connection_token({}, cfg(), tenant) is None
