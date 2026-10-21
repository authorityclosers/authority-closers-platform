"""C2 on Gemini 3.1 Flash-Lite: the bounded request, the Files API for long audio and the
transcript contract. Fake credentials, intercepted HTTPS, fictional words only."""

import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from ac_platform.conversation_intelligence import gemini_audio
from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.alignment import _KNOWN_TRANSCRIPT_TIMEBASES
from ac_platform.conversation_intelligence.inference import transcription_recipe_for_route
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_scribe_input,
    validate_scribe_result,
)
from ac_platform.conversation_intelligence.provider_registry import DEFAULT_PROVIDER_CATALOG
from ac_platform.conversation_intelligence.providers import ProviderError, ProviderResult
from tests.unit.conversation_intelligence.test_providers import client, grant

ROOT = Path(__file__).resolve().parents[3]
MODEL = "gemini-3.1-flash-lite"
AUDIO = b"RIFF-synthetic-call-audio"
SPEECH = b"ID3-synthetic-speech"
ANSWER = {
    "segments": [
        {"speaker": "B", "start": "00:04", "end": "00:09", "text": "Haan ji, main Amit."},
        {"speaker": "A", "start": "00:00", "end": "00:04", "text": "Namaste, main Rohan."},
        {"speaker": "A", "start": "00:09", "end": "", "text": "Friday ko baat karte hain."},
        {"speaker": "B", "start": "01:30", "end": "01:35", "text": "After the call ended."},
        {"speaker": "A", "start": "bad", "end": "00:10", "text": "No time."},
    ]
}


def _grant():
    return grant(AUDIO, provider="gemini", model=MODEL, operation=gemini_audio.OPERATION)


def _response(answer=ANSWER, finish="STOP"):
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(answer)}]}, "finishReason": finish}
        ],
        "usageMetadata": {"promptTokenCount": 640, "candidatesTokenCount": 90},
    }


def test_short_audio_goes_inline_with_the_strict_schema(monkeypatch) -> None:
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: SPEECH)
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url == gemini_audio.URL.format(model=MODEL)
        assert request.headers["x-goog-api-key"] == "fake-never-real"
        body = json.loads(request.read())
        part = body["contents"][0]["parts"][0]["inline_data"]
        assert part == {"mime_type": "audio/mpeg", "data": base64.b64encode(SPEECH).decode()}
        config = body["generationConfig"]
        assert config["responseJsonSchema"] == gemini_audio.SCHEMA
        assert config["maxOutputTokens"] == gemini_audio.MAX_OUTPUT_TOKENS
        assert config["temperature"] == 0.0
        assert body["systemInstruction"]["parts"][0]["text"] == gemini_audio.PROMPT
        return httpx.Response(200, json=_response())

    g = _grant()
    result = client(handler).transcribe(g, AUDIO)
    assert len(seen) == 1
    assert (result.provider, result.model) == ("gemini", MODEL)
    assert result.input_sha256 == g.quote.source.source_sha256
    assert result.usage["promptTokenCount"] == 640
    transcript = gemini_audio.gemini_audio_transcript(
        result, duration_ms=60_000, source_sha256=g.quote.source.source_sha256
    )
    assert transcript["revision"] == result.response_sha256
    assert transcript["timebase_id"] == "gemini-audio-mmss-v1"
    assert transcript["speaker_identity"] == "unverified_provider_labels"
    # Ordered; the first voice heard is speaker_0; no end gets a word-count guess (five
    # words, 2 s); a segment after the call's end and one without a time are left out.
    texts = [segment["text"] for segment in ANSWER["segments"]]
    assert transcript["segments"] == [
        {"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 4000, "text": texts[1]},
        {"id": "s2", "speaker_id": "speaker_1", "start_ms": 4000, "end_ms": 9000, "text": texts[0]},
        {
            "id": "s3",
            "speaker_id": "speaker_0",
            "start_ms": 9000,
            "end_ms": 11000,
            "text": texts[2],
        },
    ]


def test_long_audio_goes_through_the_files_api_and_is_removed(monkeypatch) -> None:
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: SPEECH)
    monkeypatch.setattr(gemini_audio, "INLINE_AUDIO_BYTES", 4)
    upload = gemini_audio.UPLOAD_URL + "?upload_id=synthetic"
    uri = gemini_audio.FILES_URL + "files/synthetic"
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        if request.url == gemini_audio.UPLOAD_URL:
            assert request.headers["x-goog-upload-header-content-length"] == str(len(SPEECH))
            return httpx.Response(200, headers={"x-goog-upload-url": upload}, json={})
        if str(request.url) == upload:
            assert "x-goog-api-key" not in request.headers
            assert request.read() == SPEECH
            return httpx.Response(
                200, json={"file": {"name": "files/synthetic", "uri": uri, "state": "ACTIVE"}}
            )
        if request.method == "DELETE":
            return httpx.Response(200, json={})
        body = json.loads(request.read())
        part = body["contents"][0]["parts"][0]
        assert part == {"file_data": {"mime_type": "audio/mpeg", "file_uri": uri}}
        return httpx.Response(200, json=_response())

    client(handler).transcribe(_grant(), AUDIO)
    assert [method for method, _ in calls] == ["POST", "POST", "POST", "DELETE"]
    assert calls[-1][1] == uri


def test_an_upload_address_elsewhere_or_a_failed_answer_still_cleans_up(monkeypatch) -> None:
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: SPEECH)
    monkeypatch.setattr(gemini_audio, "INLINE_AUDIO_BYTES", 4)
    calls = []

    def elsewhere(request):
        calls.append(request.method)
        return httpx.Response(200, headers={"x-goog-upload-url": "https://elsewhere.test/u"})

    with pytest.raises(ProviderError, match="gemini_audio_upload_failed"):
        client(elsewhere).transcribe(_grant(), AUDIO)
    assert calls == ["POST"]  # nothing sent anywhere else, no generate request

    upload = gemini_audio.UPLOAD_URL + "?upload_id=synthetic"
    deleted = []

    def failing(request):
        if request.url == gemini_audio.UPLOAD_URL:
            return httpx.Response(200, headers={"x-goog-upload-url": upload})
        if str(request.url) == upload:
            info = {"name": "files/x", "uri": gemini_audio.FILES_URL + "files/x"}
            return httpx.Response(200, json={"file": info})
        if request.method == "DELETE":
            deleted.append(str(request.url))
            return httpx.Response(200)
        return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})

    with pytest.raises(ProviderError, match="provider_http_503"):
        client(failing).transcribe(_grant(), AUDIO)
    assert deleted == [gemini_audio.FILES_URL + "files/x"]


def test_changed_audio_or_a_failed_transcode_never_reaches_the_network(monkeypatch) -> None:
    def never(_request):
        raise AssertionError("no network")

    transcoded = []
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: transcoded.append(1) or SPEECH)
    with pytest.raises(ProviderError, match="provider_dispatch_not_authorized"):
        client(never).transcribe(_grant(), AUDIO + b"changed")
    assert transcoded == []

    def broken(_audio):
        raise gemini_audio.GeminiAudioError("gemini_audio_transcode_failed")

    monkeypatch.setattr(gemini_audio, "speech_mp3", broken)
    with pytest.raises(ProviderError, match="gemini_audio_transcode_failed"):
        client(never).transcribe(_grant(), AUDIO)


def _result(payload, *, model=MODEL, provider="gemini"):
    raw = json.dumps(payload).encode()
    source = hashlib.sha256(AUDIO).hexdigest()
    return ProviderResult(
        provider, model, None, hashlib.sha256(raw).hexdigest(), raw, payload, {}, source
    ), source


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (_response(finish="MAX_TOKENS"), "gemini_audio_answer_too_long"),
        ({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}, "unreadable"),
        ({"nothing": True}, "gemini_audio_response_invalid"),
        (_response({"segments": "x"}), "gemini_audio_segments_invalid"),
        (_response({"segments": [{"speaker": "A", "start": "99:00", "text": "x"}]}), "empty"),
    ],
)
def test_bad_answers_fail_closed_with_fixed_codes(payload, code) -> None:
    result, source = _result(payload)
    with pytest.raises(ProviderError, match=code):
        gemini_audio.gemini_audio_transcript(result, duration_ms=60_000, source_sha256=source)


def test_only_this_route_and_source_make_a_transcript() -> None:
    for kwargs in ({"model": "gemini-3.8-flash"}, {"provider": "elevenlabs"}):
        result, source = _result(_response(), **kwargs)
        with pytest.raises(ProviderError, match="gemini_audio_transcript_invalid"):
            gemini_audio.gemini_audio_transcript(result, duration_ms=60_000, source_sha256=source)
    result, _ = _result(_response())
    with pytest.raises(ProviderError, match="gemini_audio_transcript_invalid"):
        gemini_audio.gemini_audio_transcript(result, duration_ms=60_000, source_sha256="b" * 64)


def test_the_route_is_one_c2_recipe_priced_and_catalogued() -> None:
    source = hashlib.sha256(AUDIO).hexdigest()
    prepared = prepare_scribe_input(
        source, 60_000, content_type="audio/wav", provider="gemini", model=MODEL
    )
    assert prepared.operation == gemini_audio.OPERATION
    assert transcription_recipe_for_route("gemini", MODEL) == gemini_audio.RECIPE
    result, _ = _result(_response())
    output = validate_scribe_result(result, prepared, duration_ms=60_000)
    assert output.data()["timebase_id"] == gemini_audio.TIMEBASE
    assert gemini_audio.TIMEBASE in _KNOWN_TRANSCRIPT_TIMEBASES
    snapshot = PRICING_SNAPSHOTS[("gemini", MODEL)]
    evidence = ROOT / "docs/ops/pricing-evidence/gemini-3.1-flash-lite-audio-20261021.md"
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == snapshot.evidence_sha256
    assert snapshot.rate_basis == "per_minute" and str(snapshot.usd_per_minute) == "0.0030"
    gemini = next(p for p in DEFAULT_PROVIDER_CATALOG.providers if p.provider_id == "gemini")
    model = next(m for m in gemini.models if m.model_id == MODEL)
    assert model.support_for("asr") == "implemented"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed here")
def test_speech_mp3_is_mono_speech_mp3(tmp_path) -> None:
    wav = tmp_path / "tone.wav"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            str(wav),
        ],
        check=True,
        timeout=60,
    )
    mp3 = gemini_audio.speech_mp3(wav.read_bytes())
    assert mp3[:3] == b"ID3" or mp3[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xe3")
    part = gemini_audio.cut(mp3, 500, 1_000)
    assert part and len(part) < len(mp3)
    with pytest.raises(gemini_audio.GeminiAudioError, match="transcode_failed"):
        gemini_audio.speech_mp3(b"not audio at all")


def test_long_calls_are_planned_as_overlapping_parts() -> None:
    minute = 60_000
    assert gemini_audio.plan_parts(15 * minute) == [(0, 15 * minute)]
    assert gemini_audio.plan_parts(25 * minute) == [
        (0, 10 * minute + 30_000),
        (10 * minute, 10 * minute + 30_000),
        (20 * minute, 5 * minute),
    ]
    # A tail shorter than the overlap was already heard by the last part.
    assert [offset for offset, _ in gemini_audio.plan_parts(20 * minute + 20_000)] == [
        0,
        10 * minute,
    ]
    assert len(gemini_audio.plan_parts(120 * minute)) == 12
    with pytest.raises(gemini_audio.GeminiAudioError, match="too_long"):
        gemini_audio.plan_parts(150 * minute)
    assert gemini_audio.speech_ms(b"x" * 8_000) == 2_000


def _turns(*rows):
    return {"segments": [{"speaker": s, "start": a, "end": b, "text": t} for s, a, b, t in rows]}


FIRST = _turns(
    ("A", "00:00", "05:00", "Namaste, main Rohan bol raha hoon."),
    ("B", "05:00", "10:02", "Haan ji, boliye, main Amit."),
    ("A", "10:05", "10:20", "Aapki team kitne logon ki hai abhi?"),
)
# The second part's model happened to call the prospect A and the salesperson B.
SECOND = _turns(
    ("B", "00:05", "00:20", "Aapki team kitne logon ki hai abhi?"),
    ("A", "00:21", "00:40", "Aath log hain aur revenue chaar lakh."),
    ("B", "01:00", "01:30", "Theek hai, Friday ko baat karte hain."),
)


def test_parts_join_on_the_calls_clock_with_one_speaker_per_voice() -> None:
    rows = gemini_audio.stitched_rows([(0, FIRST), (600_000, SECOND)])
    segments, _ = gemini_audio.normalized_segments(duration_ms=700_000, rows=rows)
    assert [(s["speaker_id"], s["start_ms"], s["text"][:12]) for s in segments] == [
        ("speaker_0", 0, "Namaste, mai"),
        ("speaker_1", 300_000, "Haan ji, bol"),
        # The overlap turn heard by both parts is kept once (the second part's copy).
        ("speaker_0", 605_000, "Aapki team k"),
        ("speaker_1", 621_000, "Aath log hai"),
        ("speaker_0", 660_000, "Theek hai, F"),
    ]


def test_long_audio_goes_as_parts_at_once_and_one_receipt(monkeypatch) -> None:
    minute_bytes = 60 * gemini_audio.BYTES_PER_SECOND
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: b"x" * (11 * minute_bytes * 2))
    monkeypatch.setattr(
        gemini_audio, "cut", lambda speech, offset, length: f"part-{offset}".encode()
    )
    answers = {
        b"part-0": FIRST,
        b"part-600000": SECOND,
        b"part-1200000": _turns(
            ("A", "00:10", "00:30", "Theek hai, Friday ko baat karte hain."),
            ("B", "00:40", "00:50", "Dhanyavaad, milte hain."),
        ),
    }
    seen = []

    def handler(request):
        body = json.loads(request.read())
        piece = base64.b64decode(body["contents"][0]["parts"][0]["inline_data"]["data"])
        seen.append(piece)
        return httpx.Response(200, json=_response(answers[piece]))

    g = _grant()
    result = client(handler).transcribe(g, AUDIO)
    assert sorted(seen) == sorted(answers)  # 22 minutes: three parts
    assert result.data["schema"] == gemini_audio.PARTS_SCHEMA
    assert [part["offset_ms"] for part in result.data["parts"]] == [0, 600_000, 1_200_000]
    assert result.response_sha256 == hashlib.sha256(result.raw_json).hexdigest()
    assert result.usage["promptTokenCount"] == 3 * 640
    transcript = gemini_audio.gemini_audio_transcript(
        result, duration_ms=22 * 60_000, source_sha256=g.quote.source.source_sha256
    )
    assert transcript["revision"] == result.response_sha256
    speakers = [s["speaker_id"] for s in transcript["segments"]]
    assert speakers[0] == "speaker_0" and set(speakers) == {"speaker_0", "speaker_1"}
    assert transcript["segments"][-1]["start_ms"] == 1_200_000 + 40_000


def test_a_failed_part_fails_the_whole_transcription(monkeypatch) -> None:
    monkeypatch.setattr(
        gemini_audio, "speech_mp3", lambda audio: b"x" * (20 * 60 * gemini_audio.BYTES_PER_SECOND)
    )
    monkeypatch.setattr(
        gemini_audio, "cut", lambda speech, offset, length: f"part-{offset}".encode()
    )

    def handler(request):
        body = json.loads(request.read())
        piece = base64.b64decode(body["contents"][0]["parts"][0]["inline_data"]["data"])
        if piece == b"part-600000":
            return httpx.Response(200, json=_response(finish="MAX_TOKENS"))
        return httpx.Response(200, json=_response())

    result = client(handler).transcribe(_grant(), AUDIO)
    with pytest.raises(ProviderError, match="gemini_audio_answer_too_long"):
        gemini_audio.gemini_audio_transcript(
            result, duration_ms=20 * 60_000, source_sha256=result.input_sha256
        )
