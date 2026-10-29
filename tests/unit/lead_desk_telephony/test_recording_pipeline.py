"""Recording downloads are bounded during streaming, retried and never redirected."""

import asyncio
import io
import wave
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ac_platform.lead_desk.telephony import providers
from ac_platform.lead_desk.telephony.http import sign
from ac_platform.lead_desk.telephony.notifications import ReportFcm
from tests.unit.lead_desk_telephony.test_telephony_providers import exotel

URL = "https://recordings.exotel.com/fictional.wav"


class Chunks(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.read = 0

    async def __aiter__(self) -> Any:
        for _ in range(100):
            self.read += 1
            yield b"x" * 65536


def test_download_stops_before_reading_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = Chunks()
    monkeypatch.setattr(providers, "MAX_RECORDING", 65536)
    source = exotel(
        lambda req: httpx.Response(200, stream=stream, headers={"content-type": "audio/wav"})
    )
    with pytest.raises(providers.TelephonyError) as error:
        asyncio.run(source.fetch_recording(URL))
    assert error.value.status == 413
    assert stream.read == 2


def test_download_retries_transient_status_and_connection_errors() -> None:
    attempts = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ConnectError("offline", request=request)
        if len(attempts) == 2:
            return httpx.Response(503)
        return httpx.Response(200, content=b"RIFFfictional", headers={"content-type": "audio/wav"})

    result = asyncio.run(exotel(respond).fetch_recording(URL))
    assert len(attempts) == 3 and result.content == b"RIFFfictional"
    assert all(
        request.headers.get("authorization", "").startswith("Basic ") for request in attempts
    )


@pytest.mark.parametrize(("status", "content_type"), [(302, "audio/wav"), (200, "text/html")])
def test_download_rejects_redirects_and_html_without_a_retry(
    status: int, content_type: str
) -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status,
            content=b"not audio",
            headers={"content-type": content_type, "location": "https://evil.test/x"},
        )

    with pytest.raises(providers.TelephonyError):
        asyncio.run(exotel(respond).fetch_recording(URL))
    assert len(seen) == 1


def test_fake_recording_is_local_valid_wav() -> None:
    fake = providers.FakeProvider(clock=lambda: 100)
    report = asyncio.run(providers.FakeProvider(clock=lambda: 125).report("fake-100-1"))
    assert report.recording_url and report.hung_up_by == "lead"
    recording = asyncio.run(fake.fetch_recording(report.recording_url))
    with wave.open(io.BytesIO(recording.content)) as audio:
        assert audio.getnframes() / audio.getframerate() == fake.TALK
    with pytest.raises(providers.TelephonyError):
        asyncio.run(fake.fetch_recording("https://evil.test/audio.wav"))


def test_callback_mac_binds_tenant_and_call() -> None:
    tenant, call = uuid4(), uuid4()
    original = sign("fictional-secret", tenant, call)
    assert original == sign("fictional-secret", tenant, call)
    assert original != sign("fictional-secret", uuid4(), call)
    assert original != sign("fictional-secret", tenant, uuid4())


def test_report_push_is_a_notification_and_opens_the_existing_android_route() -> None:
    submission = uuid4()
    # No credentials are constructed: the FCM authentication transport is stubbed.
    fcm = object.__new__(ReportFcm)
    fcm.cfg = type("Config", (), {"project_id": "fictional-project"})()

    async def token() -> str:
        return "fictional-token"

    fcm._token = token  # type: ignore[method-assign]
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await fcm.report(client, "fictional-device", submission) == "sent"

    asyncio.run(exercise())
    message = seen[0]["message"]
    assert message["notification"]["title"] == "Your call is analysed"
    assert message["data"]["sx_open"] == f"/analysis/calls/{submission}"
    assert message["android"]["notification"]["channel_id"] == "lead_alerts"
