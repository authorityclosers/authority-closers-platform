"""Company-number calls: Exotel's bridge, its refusals and reports, and the stand-in."""

import asyncio
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from ac_platform.lead_desk.telephony import providers

ENV = {
    "AC_TELEPHONY_PROVIDER": "exotel",
    "AC_TELEPHONY_EXOTEL_SID": "fictional1",
    "AC_TELEPHONY_EXOTEL_API_KEY": "key-1",
    "AC_TELEPHONY_EXOTEL_API_TOKEN": "token-1",
}
BRIDGE = providers.BridgeRequest(
    seller="+919800000001",
    lead="+919800000002",
    caller_id="+912000000000",
    reference="5f0c7a1e-0000-4000-8000-000000000001",
    status_url="https://salesxray.example/v1/lead-desk/telephony/exotel/status/t/c/m",
    notice_url="https://salesxray.example/v1/lead-desk/telephony/notice/recording-notice-en-v1.wav",
    time_limit=1200,
)


def exotel(handler: Any) -> providers.ExotelProvider:
    cfg = providers.exotel_config(ENV)
    assert cfg is not None
    return providers.ExotelProvider(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    "missing",
    ["AC_TELEPHONY_EXOTEL_SID", "AC_TELEPHONY_EXOTEL_API_KEY", "AC_TELEPHONY_EXOTEL_API_TOKEN"],
)
def test_company_calling_stays_off_until_every_exotel_key_exists(missing: str) -> None:
    env = {k: v for k, v in ENV.items() if k != missing}
    assert providers.exotel_config(env) is None
    assert providers.provider_from_env(env, environment="development") is None


def test_the_provider_is_chosen_by_setting_and_the_stand_in_never_reaches_production() -> None:
    assert providers.provider_from_env({}, environment="development") is None
    found = providers.provider_from_env(ENV, environment="production")
    assert isinstance(found, providers.ExotelProvider) and found.real
    assert found.cfg.base == "https://api.exotel.com/v1/Accounts/fictional1"
    mumbai = providers.exotel_config({**ENV, "AC_TELEPHONY_EXOTEL_SUBDOMAIN": "api.in.exotel.com"})
    assert mumbai is not None and mumbai.base.startswith("https://api.in.exotel.com/")
    # Only Exotel's own hosts: the keys never go anywhere else.
    assert providers.exotel_config({**ENV, "AC_TELEPHONY_EXOTEL_SUBDOMAIN": "evil.example"}) is None
    fake = {"AC_TELEPHONY_PROVIDER": "fake"}
    assert isinstance(
        providers.provider_from_env(fake, environment="development"), providers.FakeProvider
    )
    assert providers.provider_from_env(fake, environment="production") is None
    assert isinstance(
        providers.provider_from_env({"AC_TELEPHONY_PROVIDER": "plivo"}, environment="development"),
        providers.PlivoProvider,
    )


def test_the_bridge_rings_the_seller_first_records_both_sides_and_plays_the_notice() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"Call": {"Sid": "exo-sid-1", "Status": "in-progress"}})

    call = asyncio.run(exotel(handler).start_bridge(BRIDGE))
    assert call == providers.ProviderCall("exo-sid-1", "in_progress")
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.exotel.com/v1/Accounts/fictional1/Calls/connect.json"
    assert request.headers["authorization"].startswith("Basic ")
    form = dict(parse_qsl(request.content.decode()))
    assert form["From"] == BRIDGE.seller and form["To"] == BRIDGE.lead
    assert form["CallerId"] == BRIDGE.caller_id and form["CallType"] == "trans"
    assert form["Record"] == "true" and form["RecordingChannels"] == "dual"
    assert form["CustomField"] == BRIDGE.reference
    assert form["TimeLimit"] == "1200"
    assert form["StatusCallback"] == BRIDGE.status_url
    assert form["StatusCallbackEvents[0]"] == "terminal"
    assert form["StatusCallbackContentType"] == "application/json"
    # The notice goes to the lead (the callee), before the two are joined.
    assert form["StartPlaybackToNew"] == "Callee"
    assert form["StartPlaybackValueNew"] == BRIDGE.notice_url


def test_without_a_webhook_or_notice_the_bridge_still_goes() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(parse_qsl(request.content.decode())))
        return httpx.Response(200, json={"Call": {"Sid": "exo-sid-2", "Status": "queued"}})

    request = providers.BridgeRequest(
        seller=BRIDGE.seller,
        lead=BRIDGE.lead,
        caller_id=BRIDGE.caller_id,
        reference=BRIDGE.reference,
        status_url=None,
        notice_url=None,
        time_limit=600,
    )
    asyncio.run(exotel(handler).start_bridge(request))
    assert "StatusCallback" not in seen[0] and "StartPlaybackValueNew" not in seen[0]


@pytest.mark.parametrize(
    ("status", "body", "words", "http"),
    [
        (409, {"RestException": {"Code": 1012}}, "switched off", 409),
        (409, {"RestException": {"Code": 10706}}, "on another call", 409),
        (401, {}, "refused our keys", 503),
        (429, {}, "Too many calls", 429),
        (400, {"RestException": {"Message": "To is invalid"}}, "couldn't place", 502),
        (500, {}, "had a problem", 502),
    ],
)
def test_refusals_are_plain_words(status: int, body: dict[str, Any], words: str, http: int) -> None:
    provider = exotel(lambda request: httpx.Response(status, json=body))
    with pytest.raises(providers.TelephonyError) as caught:
        asyncio.run(provider.start_bridge(BRIDGE))
    assert words in str(caught.value) and caught.value.status == http
    # Never Exotel's own error text or a key.
    assert "To is invalid" not in str(caught.value) and "key-1" not in str(caught.value)


def test_no_answer_from_exotel_is_a_plain_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(providers.TelephonyError, match="didn't answer"):
        asyncio.run(exotel(handler).start_bridge(BRIDGE))


def test_a_finished_call_reads_as_talk_time_legs_price_and_recording() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/Accounts/fictional1/Calls/exo-sid-1.json"
        assert request.url.params["details"] == "true"
        return httpx.Response(
            200,
            json={
                "Call": {
                    "Sid": "exo-sid-1",
                    "Status": "completed",
                    "Duration": "212",
                    "Price": "4.20",
                    "RecordingUrl": "https://recordings.exotel.com/exotelrecordings/x/exo-sid-1.mp3",
                    "Details": {
                        "ConversationDuration": 187,
                        "Leg1Status": "completed",
                        "Leg2Status": "completed",
                        "Legs": [
                            {"Leg": {"Id": 1, "OnCallDuration": 205, "Status": "completed"}},
                            {"Leg": {"Id": 2, "OnCallDuration": 187, "Status": "completed"}},
                        ],
                    },
                }
            },
        )

    report = asyncio.run(exotel(handler).report("exo-sid-1"))
    assert report.final and report.status == "completed"
    assert report.seller_answered is True and report.lead_answered is True
    assert report.talk_seconds == 187 and report.total_seconds == 212
    assert report.leg_seconds == (205, 187)
    assert report.price_paise == 420
    assert report.recording_url and report.recording_url.endswith("exo-sid-1.mp3")


def test_the_lead_not_answering_and_the_seller_not_answering_read_apart() -> None:
    lead_missed = providers.exotel_report(
        {
            "Sid": "a",
            "Status": "no-answer",
            "Details": {"Leg1Status": "completed", "Leg2Status": "no-answer"},
        }
    )
    assert (
        lead_missed.final
        and lead_missed.seller_answered is True
        and lead_missed.lead_answered is False
    )
    seller_missed = providers.exotel_report(
        {
            "Sid": "b",
            "Status": "no-answer",
            "Details": {"Leg1Status": "no-answer", "Leg2Status": ""},
        }
    )
    assert seller_missed.seller_answered is False
    # A status webhook's flat body reads the same way.
    hook = providers.exotel_report(
        {
            "CallSid": "c",
            "Status": "busy",
            "ConversationDuration": 0,
            "Legs": [{"Status": "completed"}, {"Status": "busy"}],
        }
    )
    assert hook.sid == "c" and hook.status == "busy" and hook.lead_answered is False
    assert providers.exotel_report({"Status": "in-progress"}).final is False


def test_recordings_come_only_from_exotel_hosts_over_https() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    provider = exotel(handler)
    for bad in (
        "http://recordings.exotel.com/x.mp3",
        "https://example.com/x.mp3",
        "https://exotel.com.evil/x",
    ):
        with pytest.raises(providers.TelephonyError):
            asyncio.run(provider.fetch_recording(bad))
    assert calls == []
    got = asyncio.run(provider.fetch_recording("https://recordings.exotel.com/x.mp3"))
    assert got.content == b"ID3audio" and got.content_type == "audio/mpeg"


def test_the_stand_in_rings_talks_and_ends_and_a_lead_ending_in_0_doesnt_answer() -> None:
    clock = [1_000_000.0]
    fake = providers.FakeProvider(clock=lambda: clock[0])
    answered = asyncio.run(fake.start_bridge(BRIDGE))
    missed = asyncio.run(
        fake.start_bridge(
            providers.BridgeRequest(
                seller=BRIDGE.seller,
                lead="+919800000010",
                caller_id=BRIDGE.caller_id,
                reference=BRIDGE.reference,
                status_url=None,
                notice_url=None,
                time_limit=600,
            )
        )
    )
    assert asyncio.run(fake.report(answered.sid)).status == "ringing"
    clock[0] += 10
    assert asyncio.run(fake.report(answered.sid)).status == "in_progress"
    clock[0] += 15
    done = asyncio.run(fake.report(answered.sid))
    assert done.final and done.lead_answered and done.talk_seconds == providers.FakeProvider.TALK
    nobody = asyncio.run(fake.report(missed.sid))
    assert nobody.status == "no_answer" and nobody.lead_answered is False
    with pytest.raises(providers.TelephonyError):
        asyncio.run(fake.report("exo-not-fake"))
