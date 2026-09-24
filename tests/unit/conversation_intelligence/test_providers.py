"""Transport boundaries are exercised with fake credentials and intercepted HTTPS."""

import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.provider_failure_observation import (
    MAX_ERROR_RESPONSE_BODY_BYTES,
)
from ac_platform.conversation_intelligence.providers import (
    BoundedProviders,
    ProviderError,
    ProviderResult,
    deepgram_transcript,
    scribe_transcript,
)


def grant(
    data, *, provider="gemini", model="gemini-2.5-flash", operation="extract_context_evidence"
):
    digest = hashlib.sha256(data).hexdigest()
    q = Quote(
        "q",
        SourceBinding("tenant", "recording", digest, "1"),
        "owner",
        "scope",
        provider,
        model,
        "test-v1",
        operation,
        digest,
        "synthetic-only",
        "test-permission",
        "test-terms",
        "test-retention",
        "test-purpose",
        "test-free-quote",
        1,
        0,
        100,
        300,
    )
    return Reservation(
        "r",
        q,
        ExecutionPermission("test-authority", q.fingerprint, "owner", 300),
        "in_flight",
        "attempt",
    )


def body():
    return {
        "contents": [{"parts": [{"text": "Synthetic test"}]}],
        "generationConfig": {"maxOutputTokens": 8},
    }


def client(handler, authorize=lambda _: None):
    return BoundedProviders(
        credentials={
            "gemini": "fake-never-real",
            "elevenlabs": "fake-never-real",
            "deepgram": "fake-never-real",
        },
        authorize=authorize,
        clock=lambda: 200,
        transport=httpx.MockTransport(handler),
    )


def test_generation_fixed_endpoint_bound_output_and_usage():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"candidates": [], "usageMetadata": {"totalTokenCount": 9}})

    result = client(handler).generate(grant(canonical(body())), body())
    assert (
        str(seen[0].url)
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert len(seen) == 1 and result.usage == {"totalTokenCount": 9}
    assert "fake-never-real" not in repr(result)


def test_groq_generation_uses_the_fixed_endpoint_and_declared_model():
    request_body = {
        "model": "openai/gpt-oss-120b",
        "messages": [{"role": "user", "content": "Synthetic test"}],
        "max_completion_tokens": 16,
    }
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer fake-never-real"
        return httpx.Response(200, json={"choices": [], "usage": {"total_tokens": 4}})

    provider = BoundedProviders(
        credentials={"groq": "fake-never-real"},
        authorize=lambda _: None,
        clock=lambda: 200,
        transport=httpx.MockTransport(handler),
    )
    result = provider.generate(
        grant(canonical(request_body), provider="groq", model="openai/gpt-oss-120b"),
        request_body,
    )
    assert str(seen[0].url) == "https://api.groq.com/openai/v1/chat/completions"
    assert result.usage == {"total_tokens": 4}


def test_result_and_failures_never_retain_provider_content_or_credentials():
    sensitive_value = "fake-never-real-super-secret"

    def handler(_):
        return httpx.Response(
            403,
            text=json.dumps(
                {
                    "error": {
                        "message": f"permission_denied for {sensitive_value}; api_key_invalid",
                        "private_prompt": "Synthetic caller content must stay private",
                    }
                }
            ),
        )

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(grant(canonical(body())), body())
    assert str(caught.value) == "provider_http_403"
    assert sensitive_value not in repr(caught.value)
    assert caught.value.diagnostic == "key_invalid"
    assert caught.value.failure_observation is not None
    assert caught.value.failure_observation.http_status == 403
    assert caught.value.failure_observation.diagnostic_category == "key_invalid"
    assert sensitive_value not in repr(caught.value.failure_observation)

    def success(_):
        return httpx.Response(
            200,
            json={"private_prompt": sensitive_value, "candidates": []},
        )

    result = client(success).generate(grant(canonical(body())), body())
    assert sensitive_value not in repr(result)
    assert sensitive_value in result.data["private_prompt"]


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_no_redirect_or_retry_and_no_error_body_disclosure(status):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://evil.invalid"},
            text="fake-never-real private-call",
        )

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(grant(canonical(body())), body())
    assert len(seen) == 1
    assert str(caught.value) == f"provider_http_{status}"


def test_transport_exception_is_stable_and_not_retried():
    attempts = []

    def handler(_):
        attempts.append(True)
        raise httpx.ReadTimeout("provider payload contains fake-never-real")

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(grant(canonical(body())), body())
    assert len(attempts) == 1
    assert str(caught.value) == "provider_transport_or_response_failed"
    assert "fake-never-real" not in repr(caught.value)


@pytest.mark.parametrize(
    ("message", "diagnostic"),
    [
        ("schema has too many states for serving", "structured_schema_complexity"),
        ("maximum nesting depth exceeded", "structured_schema_depth"),
        ("null is not supported in schema", "structured_schema_null"),
        ("invalid responseJsonSchema", "structured_schema_rejected"),
    ],
)
def test_schema_errors_classify_without_disclosing_provider_text(message, diagnostic):
    def handler(_):
        return httpx.Response(400, json={"error": message + " secret-private-call"})

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(grant(canonical(body())), body())
    assert str(caught.value) == "provider_http_400"
    assert caught.value.diagnostic == diagnostic
    assert caught.value.failure_observation is not None
    assert caught.value.failure_observation.diagnostic_category == diagnostic
    assert "secret-private-call" not in repr(caught.value)


def test_changed_input_and_stale_grant_never_dispatch():
    def handler(_):
        pytest.fail("unauthorized network dispatch")

    g = grant(canonical(body()))
    with pytest.raises(ProviderError):
        client(handler).generate(g, {**body(), "contents": []})
    with pytest.raises(ProviderError):
        client(handler).generate(replace(g, state="reserved", attempt_id=None), body())


def test_non_object_generation_payload_fails_with_a_stable_provider_error():
    with pytest.raises(ProviderError):
        client(lambda _: pytest.fail("invalid payload dispatched")).generate(
            grant(canonical(body())), []
        )


def test_authority_is_checked_at_dispatch():
    def deny(_):
        raise ProviderError("revoked")

    with pytest.raises(ProviderError, match="revoked"):
        client(lambda _: pytest.fail("network called"), deny).generate(
            grant(canonical(body())), body()
        )


def test_authorization_uses_a_canonical_body_snapshot_before_send():
    request_body = body()
    original_text = request_body["contents"][0]["parts"][0]["text"]
    seen = []

    def mutate_after_admission(_):
        request_body["contents"][0]["parts"][0]["text"] = "mutated after grant"

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"candidates": []})

    provider = BoundedProviders(
        credentials={"gemini": "fake-never-real"},
        authorize=mutate_after_admission,
        clock=lambda: 200,
        transport=httpx.MockTransport(handler),
    )
    provider.generate(grant(canonical(request_body)), request_body)
    assert seen[0]["contents"][0]["parts"][0]["text"] == original_text


def test_transport_timeout_is_finite_and_single_shot():
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"candidates": []})

    client(handler).generate(grant(canonical(body())), body())
    assert len(seen) == 1
    assert set(seen[0]) == {"connect", "read", "write", "pool"}
    assert all(type(value) is int and 0 < value <= 180 for value in seen[0].values())


def test_streaming_response_has_a_whole_execution_deadline():
    ticks = []

    def monotonic():
        ticks.append(True)
        return 0.0 if len(ticks) == 1 else 301.0

    class Chunked(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"candidates":'
            yield b"[]}"

    def handler(_):
        return httpx.Response(200, stream=Chunked())

    with pytest.raises(ProviderError):
        BoundedProviders(
            credentials={"gemini": "fake-never-real"},
            authorize=lambda _: None,
            clock=lambda: 200,
            monotonic=monotonic,
            transport=httpx.MockTransport(handler),
        ).generate(grant(canonical(body())), body())
    assert ticks


def test_http_failure_observation_binds_attempt_and_complete_bounded_body():
    source = grant(canonical(body()))
    response_body = b'{"error":"synthetic schema rejection"}'

    def handler(_):
        return httpx.Response(
            500,
            headers={"x-request-id": "request-123", "retry-after": "45"},
            content=response_body,
        )

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(source, body())

    observation = caught.value.failure_observation
    assert observation is not None
    assert str(caught.value) == "provider_http_500"
    assert observation.reservation_id == source.reservation_id
    assert observation.attempt_id == source.attempt_id
    assert observation.quote_fingerprint == source.quote.fingerprint
    assert observation.provider == source.quote.provider_id
    assert observation.model == source.quote.provider_model
    assert observation.operation == source.quote.operation
    assert observation.input_sha256 == source.quote.input_sha256
    assert observation.http_status == 500
    assert observation.response_body_complete is True
    assert observation.response_body_observed_bytes == len(response_body)
    assert observation.response_body_sha256 == hashlib.sha256(response_body).hexdigest()
    assert observation.provider_request_id_sha256 == hashlib.sha256(b"request-123").hexdigest()
    assert observation.retry_after_seconds == 45
    assert "synthetic schema rejection" not in repr(observation)


def test_http_failure_observation_keeps_status_when_body_stream_truncates():
    source = grant(canonical(body()))
    first_body_chunk = b'{"error":"schema failed fake-never-real"}' + b"x" * 4_054
    second_body_chunk = b" and this suffix was not read"
    ticks = iter((0.0, 0.0, 0.0, 181.0))

    class SlowError(httpx.SyncByteStream):
        def __iter__(self):
            yield first_body_chunk
            yield second_body_chunk

    def handler(_):
        return httpx.Response(
            503,
            headers={"request-id": "request-456", "retry-after": "99999"},
            stream=SlowError(),
        )

    with pytest.raises(ProviderError) as caught:
        BoundedProviders(
            credentials={"gemini": "fake-never-real"},
            authorize=lambda _: None,
            clock=lambda: 200,
            monotonic=lambda: next(ticks, 181.0),
            transport=httpx.MockTransport(handler),
        ).generate(source, body())

    observation = caught.value.failure_observation
    assert observation is not None
    assert str(caught.value) == "provider_http_503"
    assert observation.http_status == 503
    assert observation.response_body_complete is False
    assert observation.response_body_observed_bytes == 4_096
    assert observation.response_body_sha256 is None
    assert observation.provider_request_id_sha256 == hashlib.sha256(b"request-456").hexdigest()
    assert observation.retry_after_seconds is None
    assert "fake-never-real" not in repr(observation)
    assert "fake-never-real" not in repr(caught.value)


def test_http_failure_observation_caps_oversized_body_and_drops_unsafe_metadata():
    source = grant(canonical(body()))
    private_body = b"fake-never-real" + b"x" * (MAX_ERROR_RESPONSE_BODY_BYTES + 1)

    def handler(_):
        return httpx.Response(
            429,
            headers={"x-request-id": "sk_live_synthetic_secret", "retry-after": "1.5"},
            content=private_body,
        )

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(source, body())

    observation = caught.value.failure_observation
    assert observation is not None
    assert observation.http_status == 429
    assert observation.response_body_complete is False
    assert observation.response_body_observed_bytes == MAX_ERROR_RESPONSE_BODY_BYTES
    assert observation.response_body_sha256 is None
    assert (
        observation.provider_request_id_sha256
        == hashlib.sha256(b"sk_live_synthetic_secret").hexdigest()
    )
    assert b"sk_live_synthetic_secret" not in str(observation.as_dict()).encode()
    assert "sk_live_synthetic_secret" not in repr(observation)
    assert observation.retry_after_seconds is None
    assert "fake-never-real" not in repr(observation)


def test_transport_failure_has_no_http_observation():
    def handler(_):
        raise httpx.ReadTimeout("no response and no provider details may escape")

    with pytest.raises(ProviderError) as caught:
        client(handler).generate(grant(canonical(body())), body())

    assert caught.value.failure_observation is None


def test_response_bound():
    with pytest.raises(ProviderError, match="too_large"):
        client(lambda _: httpx.Response(200, content=b"x" * (4 * 1024 * 1024 + 1))).generate(
            grant(canonical(body())), body()
        )


def test_scribe_native_text_and_unverified_identity_preserved():
    audio = b"synthetic-audio"
    g = grant(audio, provider="elevenlabs", model="scribe_v2", operation="transcribe_scribe_v2")

    def handler(request):
        assert str(request.url) == "https://api.elevenlabs.io/v1/speech-to-text"
        assert b"synthetic-audio" in request.read()
        return httpx.Response(
            200,
            json={
                "text": "नमस्ते  friend!",
                "words": [
                    {"text": "नमस्ते", "start": 0.0, "end": 0.5, "speaker_id": "speaker_0"},
                    {"text": "friend!", "start": 0.5, "end": 1.0, "speaker_id": "speaker_0"},
                ],
            },
        )

    transcript = scribe_transcript(
        client(handler).transcribe(g, audio),
        duration_ms=1000,
        source_sha256=g.quote.source.source_sha256,
    )
    assert transcript["raw_text"] == "नमस्ते  friend!"
    assert transcript["revision"] == transcript["raw_response_sha256"]
    assert transcript["segments"] == [
        {
            "id": "s1",
            "speaker_id": "speaker_0",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "नमस्ते friend!",
        }
    ]
    assert transcript["alignment_to_audioatlas"] == "unverified"
    assert transcript["speaker_identity"] == "unverified_provider_labels"
    assert transcript["overlap_observed"] is False
    # Provider speaker labels are not physical channel assignments. The adapter
    # must keep the distinction explicit instead of inventing a channel mapping.
    assert all("channel" not in segment for segment in transcript["segments"])


def test_deepgram_nova3_uses_bounded_binary_request_and_normalizes_labels():
    audio = b"synthetic-audio"
    g = grant(audio, provider="deepgram", model="nova-3", operation="transcribe_deepgram_nova3")
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["authorization"] == "Token fake-never-real"
        assert request.headers["content-type"] == "application/octet-stream"
        assert dict(request.url.params) == {
            "model": "nova-3",
            "language": "multi",
            "mip_opt_out": "true",
            "smart_format": "true",
            "punctuate": "true",
            "diarize": "true",
            "utterances": "true",
            "paragraphs": "true",
        }
        assert request.read() == audio
        return httpx.Response(
            200,
            headers={"dg-request-id": "deepgram-synthetic-request-1"},
            json={
                "results": {
                    "channels": [
                        {
                            "alternatives": [
                                {
                                    "transcript": "Hello, world.",
                                    "words": [
                                        {
                                            "word": "hello",
                                            "punctuated_word": "Hello,",
                                            "start": 0.0,
                                            "end": 0.5,
                                            "speaker": 0,
                                        },
                                        {
                                            "word": "world",
                                            "punctuated_word": "world.",
                                            "start": 0.5,
                                            "end": 1.0,
                                            "speaker": 0,
                                        },
                                    ],
                                }
                            ]
                        }
                    ]
                }
            },
        )

    result = client(handler).transcribe(g, audio)
    assert result.request_id == "deepgram-synthetic-request-1"
    transcript = deepgram_transcript(
        result,
        duration_ms=1000,
        source_sha256=g.quote.source.source_sha256,
    )
    assert len(seen) == 1
    assert transcript["raw_text"] == "Hello, world."
    assert transcript["segments"] == [
        {
            "id": "s1",
            "speaker_id": "speaker_0",
            "start_ms": 0,
            "end_ms": 1000,
            "text": "Hello, world.",
        }
    ]
    assert transcript["timebase_id"] == "deepgram-native-seconds"
    assert transcript["alignment_to_audioatlas"] == "unverified"
    assert transcript["speaker_identity"] == "unverified_provider_labels"


def test_deepgram_preserves_hinglish_text_switching_and_unverified_speakers():
    audio = b"synthetic-hinglish-audio"
    g = grant(audio, provider="deepgram", model="nova-3", operation="transcribe_deepgram_nova3")

    def handler(_):
        return httpx.Response(
            200,
            headers={"dg-request-id": "deepgram-hinglish-request-1"},
            json={
                "results": {
                    "channels": [
                        {
                            "alternatives": [
                                {
                                    "transcript": "Aap kal pricing discuss karenge? Haan, bilkul.",
                                    "words": [
                                        {"word": "Aap", "start": 0.0, "end": 0.4, "speaker": 0},
                                        {"word": "kal", "start": 0.4, "end": 0.7, "speaker": 0},
                                        {"word": "pricing", "start": 0.7, "end": 1.1, "speaker": 0},
                                        {"word": "discuss", "start": 1.1, "end": 1.5, "speaker": 0},
                                        {
                                            "word": "karenge?",
                                            "start": 1.5,
                                            "end": 1.9,
                                            "speaker": 0,
                                        },
                                        {"word": "Haan,", "start": 2.1, "end": 2.5, "speaker": 1},
                                        {"word": "bilkul.", "start": 2.5, "end": 2.9, "speaker": 1},
                                    ],
                                }
                            ]
                        }
                    ]
                }
            },
        )

    result = client(handler).transcribe(g, audio)
    normalized = deepgram_transcript(
        result,
        duration_ms=3_000,
        source_sha256=g.quote.source.source_sha256,
    )
    assert result.request_id == "deepgram-hinglish-request-1"
    assert normalized["raw_text"] == "Aap kal pricing discuss karenge? Haan, bilkul."
    assert [segment["speaker_id"] for segment in normalized["segments"]] == [
        "speaker_0",
        "speaker_1",
    ]
    assert normalized["segments"][0]["text"] == "Aap kal pricing discuss karenge?"
    assert normalized["segments"][1]["text"] == "Haan, bilkul."
    assert normalized["speaker_identity"] == "unverified_provider_labels"
    assert all("channel" not in segment for segment in normalized["segments"])


def _deepgram_from_response(payload, *, duration_ms=2_000):
    audio = b"synthetic-audio"
    g = grant(audio, provider="deepgram", model="nova-3", operation="transcribe_deepgram_nova3")

    def handler(_):
        return httpx.Response(200, json=payload)

    result = client(handler).transcribe(g, audio)
    return result, deepgram_transcript(
        result,
        duration_ms=duration_ms,
        source_sha256=g.quote.source.source_sha256,
    )


def test_deepgram_stably_sorts_valid_out_of_order_words_for_playback():
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "late first overlap middle",
                            "words": [
                                {"word": "late", "start": 1.0, "end": 1.4, "speaker": 0},
                                {"word": "first", "start": 0.0, "end": 0.8, "speaker": 1},
                                {"word": "overlap", "start": 0.5, "end": 0.9, "speaker": 1},
                                {"word": "middle", "start": 0.8, "end": 1.1, "speaker": 0},
                            ],
                        }
                    ]
                }
            ]
        }
    }

    result, normalized = _deepgram_from_response(payload)

    assert result.data == payload
    assert normalized["raw_text"] == "late first overlap middle"
    assert normalized["raw_response_sha256"] == result.response_sha256
    assert normalized["segments"] == [
        {
            "id": "s1",
            "speaker_id": "speaker_1",
            "start_ms": 0,
            "end_ms": 900,
            "text": "first overlap",
        },
        {
            "id": "s2",
            "speaker_id": "speaker_0",
            "start_ms": 800,
            "end_ms": 1400,
            "text": "middle late",
        },
    ]
    assert normalized["overlap_observed"] is True


@pytest.mark.parametrize(
    "word",
    [
        {"word": "negative", "start": -0.1, "end": 0.2, "speaker": 0},
        {"word": "backwards", "start": 0.7, "end": 0.2, "speaker": 0},
        {"word": "tail", "start": 1.0, "end": 2.1, "speaker": 0},
    ],
)
def test_deepgram_rejects_invalid_individual_timestamps(word):
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {"transcript": "synthetic", "words": [word]},
                    ]
                }
            ]
        }
    }

    with pytest.raises(ProviderError, match="deepgram_timing_invalid"):
        _deepgram_from_response(payload, duration_ms=1_000)


def test_deepgram_rejects_nonfinite_individual_timestamps():
    audio = b"synthetic-audio"
    g = grant(audio, provider="deepgram", model="nova-3", operation="transcribe_deepgram_nova3")
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "synthetic",
                            "words": [{"word": "nonfinite", "start": float("nan"), "end": 0.2}],
                        }
                    ]
                }
            ]
        }
    }
    raw = json.dumps(payload, allow_nan=True).encode()
    result = ProviderResult(
        "deepgram",
        "nova-3",
        None,
        hashlib.sha256(raw).hexdigest(),
        raw,
        payload,
        input_sha256=g.quote.source.source_sha256,
    )

    with pytest.raises(ProviderError, match="deepgram_timing_invalid"):
        deepgram_transcript(result, duration_ms=1_000, source_sha256=g.quote.source.source_sha256)


def _scribe_from_response(payload, *, duration_ms=1000):
    audio = b"synthetic-audio"
    g = grant(audio, provider="elevenlabs", model="scribe_v2", operation="transcribe_scribe_v2")

    def handler(_):
        return httpx.Response(200, json=payload)

    result = client(handler).transcribe(g, audio)
    return scribe_transcript(
        result,
        duration_ms=duration_ms,
        source_sha256=g.quote.source.source_sha256,
    )


def test_scribe_output_remains_bound_to_the_exact_source_hash():
    audio = b"synthetic-audio"
    g = grant(audio, provider="elevenlabs", model="scribe_v2", operation="transcribe_scribe_v2")

    def handler(_):
        return httpx.Response(200, json={"text": "x", "words": []})

    result = client(handler).transcribe(g, audio)
    with pytest.raises(ProviderError):
        scribe_transcript(result, duration_ms=1000, source_sha256="b" * 64)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "scribe_transcript_invalid"),
        ({"text": "x", "words": "not-a-list"}, "scribe_words_invalid"),
        ({"text": "x", "words": [{"text": 3, "start": 0, "end": 1}]}, "scribe_word_invalid"),
        ({"text": "x", "words": [{"text": "x", "start": -0.1, "end": 1}]}, "scribe_timing_invalid"),
        (
            {"text": "x", "words": [{"text": "x", "start": 0.5, "end": 0.1}]},
            "scribe_timing_invalid",
        ),
        ({"text": "x", "words": [{"text": "x", "start": 0, "end": 2.1}]}, "scribe_timing_invalid"),
        (
            {"text": "x", "words": [{"text": "x", "start": 0, "end": 0.5, "speaker_id": 4}]},
            "scribe_speaker_invalid",
        ),
    ],
)
def test_scribe_bad_response_shapes_fail_closed(payload, message):
    with pytest.raises(ProviderError, match=message):
        _scribe_from_response(payload)


def test_scribe_preserves_overlapping_native_words_without_shrinking_timing():
    transcript = _scribe_from_response(
        {
            "text": "x y",
            "words": [
                {"text": "x", "start": 0, "end": 0.9},
                {"text": "y", "start": 0.5, "end": 0.6},
            ],
        }
    )
    assert transcript["overlap_observed"] is True
    assert transcript["segments"][0]["start_ms"] == 0
    assert transcript["segments"][0]["end_ms"] == 900


def test_scribe_rejects_mutable_audio_payload_before_network():
    audio = bytearray(b"synthetic-audio")
    g = grant(
        bytes(audio),
        provider="elevenlabs",
        model="scribe_v2",
        operation="transcribe_scribe_v2",
    )
    with pytest.raises(ProviderError):
        client(lambda _: pytest.fail("mutable audio dispatched")).transcribe(g, audio)


def test_cross_source_scribe_and_oversized_output_budget_rejected():
    g = grant(b"audio", provider="elevenlabs", model="scribe_v2", operation="transcribe_scribe_v2")
    with pytest.raises(ProviderError):
        client(lambda _: pytest.fail("network called")).transcribe(g, b"other audio")
    invalid = {**body(), "generationConfig": {"maxOutputTokens": 9000}}
    with pytest.raises(ProviderError, match="budget"):
        client(lambda _: pytest.fail("network called")).generate(grant(canonical(invalid)), invalid)


def test_scribe_rejects_audio_over_shared_provider_limit_before_network():
    audio = b"a" * (MAX_AUDIO_BYTES + 1)
    reservation = grant(
        audio,
        provider="elevenlabs",
        model="scribe_v2",
        operation="transcribe_scribe_v2",
    )

    with pytest.raises(ProviderError, match="audio_or_model_invalid"):
        client(lambda _: pytest.fail("oversized audio dispatched")).transcribe(reservation, audio)
