"""C2 on Gemini 3.1 Flash-Lite: the bounded request, the Files API for long audio and the
transcript contract. Fake credentials, intercepted HTTPS, fictional words only."""

import base64
import dataclasses
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
from ac_platform.conversation_intelligence.checkpoints import canonical
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


def test_a_flex_route_asks_flex_and_falls_back_once_to_standard(monkeypatch) -> None:
    """Flex is a request option on the base model: busy answers go once more on standard,
    and the receipt says so (gemini_tiers)."""
    from ac_platform.conversation_intelligence import gemini_tiers

    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: SPEECH)
    tiers: list[str | None] = []

    def handler(request):
        assert request.url == gemini_audio.URL.format(model=MODEL)  # the base model's URL
        tier = json.loads(request.read()).get("service_tier")
        tiers.append(tier)
        if tier == "flex":
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_response())

    g = grant(AUDIO, provider="gemini", model=MODEL + ":flex", operation=gemini_audio.OPERATION)
    result = client(handler).transcribe(g, AUDIO)
    assert tiers == ["flex", None]
    assert result.model == MODEL + ":flex"
    assert result.usage[gemini_tiers.FLEX_USAGE] == 1
    assert result.usage[gemini_tiers.FALLBACK_USAGE] == 1
    transcript = gemini_audio.gemini_audio_transcript(
        result, duration_ms=60_000, source_sha256=g.quote.source.source_sha256
    )
    assert transcript["segments"]

    # A Flex answer is kept as it is; a refused request is not retried on standard.
    def flex_ok(request):
        return httpx.Response(200, json=_response())

    ok = client(flex_ok).transcribe(g, AUDIO)
    assert ok.usage[gemini_tiers.FLEX_USAGE] == 1 and gemini_tiers.FALLBACK_USAGE not in ok.usage
    seen: list[str | None] = []

    def refused(request):
        seen.append(json.loads(request.read()).get("service_tier"))
        return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})

    with pytest.raises(ProviderError, match="provider_http_400"):
        client(refused).transcribe(g, AUDIO)
    assert seen == ["flex"]


def test_the_flex_text_route_sends_the_same_prompt_to_the_base_model() -> None:
    from ac_platform.conversation_intelligence import gemini_tiers
    from ac_platform.conversation_intelligence.completion_limits import completion_ceiling
    from ac_platform.conversation_intelligence.qualitative_pack import (
        supports_coaching_v6_route,
    )

    flex = gemini_tiers.flex("gemini-3.8-flash")
    assert completion_ceiling("gemini", flex, "C5") == completion_ceiling(
        "gemini", "gemini-3.8-flash", "C5"
    )
    assert supports_coaching_v6_route("gemini", flex)
    body = {
        "systemInstruction": {"parts": [{"text": "S"}]},
        "contents": [{"role": "user", "parts": [{"text": "U"}]}],
        "generationConfig": {"maxOutputTokens": 100},
    }
    sent: list[dict] = []

    def handler(request):
        assert "gemini-3.8-flash:generateContent" in str(request.url)
        sent.append(json.loads(request.read()))
        return httpx.Response(200, json=_response({"ok": True}))

    g = grant(canonical(body), provider="gemini", model=flex)
    result = client(handler).generate(g, body)
    assert sent[0]["service_tier"] == "flex"
    assert {k: v for k, v in sent[0].items() if k != "service_tier"} == body
    assert result.usage[gemini_tiers.FLEX_USAGE] == 1


COMPACT = """[00:00] S1: Namaste, main Rohan.
[00:04] S2: Haan ji, main Amit.
aur aap kaise hain?
```
[00:09] S1: Friday ko baat karte hain.
[1:00:05] S2: Late in a long call."""


def _compact_grant():
    g = _grant()
    quote = dataclasses.replace(g.quote, recipe_revision=gemini_audio.FORMAT_RECIPES["compact"])
    permission = dataclasses.replace(g.permission, quote_fingerprint=quote.fingerprint)
    return dataclasses.replace(g, quote=quote, permission=permission)


def _text_response(text):
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 640, "candidatesTokenCount": 40},
    }


def test_this_route_keeps_the_json_recipe_root_sealed() -> None:
    # Root sealed this recipe and prompt revision (v0.72), and every Flash-Lite C2
    # checkpoint re-derives it from the route; compact is a different recipe.
    assert gemini_audio.TRANSCRIPT_FORMAT == "json"
    assert gemini_audio.RECIPE == "gemini-3.1-flash-lite-audio-v1"
    assert gemini_audio.PROMPT_REVISION == "gemini-audio-transcript/1"
    for model in gemini_audio.MODELS:
        assert transcription_recipe_for_route("gemini", model) == gemini_audio.RECIPE
    assert gemini_audio.FORMAT_RECIPES["compact"] != gemini_audio.RECIPE
    assert gemini_audio.format_of(gemini_audio.RECIPE) == "json"
    assert gemini_audio.format_of(gemini_audio.FORMAT_RECIPES["compact"]) == "compact"


def test_a_compact_recipe_asks_for_lines_without_a_schema(monkeypatch) -> None:
    monkeypatch.setattr(gemini_audio, "speech_mp3", lambda audio: SPEECH)
    sent = []

    def handler(request):
        sent.append(json.loads(request.read()))
        return httpx.Response(200, json=_text_response(COMPACT))

    g = _compact_grant()
    result = client(handler).transcribe(g, AUDIO)
    config = sent[0]["generationConfig"]
    assert "responseJsonSchema" not in config and "responseMimeType" not in config
    assert config["maxOutputTokens"] == gemini_audio.MAX_OUTPUT_TOKENS
    assert config["temperature"] == 0.0
    assert sent[0]["systemInstruction"]["parts"][0]["text"] == gemini_audio.COMPACT_PROMPT
    transcript = gemini_audio.gemini_audio_transcript(
        result, duration_ms=60_000, source_sha256=g.quote.source.source_sha256
    )
    # Each turn ends where the next starts; a line without a time continues its turn;
    # the fence is not speech; the last turn gets the word-count guess; a turn after the
    # call's end is left out.
    assert transcript["segments"] == [
        {
            "id": "s1",
            "speaker_id": "speaker_0",
            "start_ms": 0,
            "end_ms": 4000,
            "text": "Namaste, main Rohan.",
        },
        {
            "id": "s2",
            "speaker_id": "speaker_1",
            "start_ms": 4000,
            "end_ms": 9000,
            "text": "Haan ji, main Amit. aur aap kaise hain?",
        },
        {
            "id": "s3",
            "speaker_id": "speaker_0",
            "start_ms": 9000,
            "end_ms": 60_000,
            "text": "Friday ko baat karte hain.",
        },
    ]


def test_compact_lines_read_as_the_json_answers_segments() -> None:
    answer = gemini_audio.compact_answer(COMPACT)
    assert [(row["speaker"], row["start"], row["end"]) for row in answer["segments"]] == [
        ("S1", "00:00", "00:04"),
        ("S2", "00:04", "00:09"),
        ("S1", "00:09", "1:00:05"),
        ("S2", "1:00:05", None),
    ]
    assert gemini_audio.clock_ms("1:00:05") == 3_605_000
    # The same answer as JSON gives the same segments.
    as_json = gemini_audio.normalized_segments({"segments": answer["segments"]}, duration_ms=60_000)
    as_lines = gemini_audio.normalized_segments(
        gemini_audio.answer_of(_text_response(COMPACT)), duration_ms=60_000
    )
    assert as_json == as_lines
    with pytest.raises(gemini_audio.GeminiAudioError, match="unreadable"):
        gemini_audio.compact_answer("Here is the transcript:\n```\n```")
    with pytest.raises(gemini_audio.GeminiAudioError, match="too_long"):
        gemini_audio.answer_of(
            {
                **_text_response(COMPACT),
                "candidates": [
                    {"content": {"parts": [{"text": COMPACT}]}, "finishReason": "MAX_TOKENS"}
                ],
            }
        )


def test_compact_parts_join_with_one_speaker_per_voice() -> None:
    first = gemini_audio.compact_answer(
        "[00:00] S1: Namaste, main Rohan bol raha hoon.\n"
        "[05:00] S2: Haan ji, boliye, main Amit.\n"
        "[10:05] S1: Aapki team kitne logon ki hai abhi?"
    )
    # The second part's model happened to hear the prospect first.
    second = gemini_audio.compact_answer(
        "[00:05] S2: Aapki team kitne logon ki hai abhi?\n"
        "[00:21] S1: Aath log hain aur revenue chaar lakh.\n"
        "[01:00] S2: Theek hai, Friday ko baat karte hain."
    )
    rows = gemini_audio.stitched_rows([(0, first), (600_000, second)])
    segments, _ = gemini_audio.normalized_segments(duration_ms=700_000, rows=rows)
    assert [(s["speaker_id"], s["start_ms"]) for s in segments] == [
        ("speaker_0", 0),
        ("speaker_1", 300_000),
        ("speaker_0", 605_000),
        ("speaker_1", 621_000),
        ("speaker_0", 660_000),
    ]
