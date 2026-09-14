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
from ac_platform.conversation_intelligence.providers import (
    BoundedProviders,
    ProviderError,
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
        credentials={"gemini": "fake-never-real", "elevenlabs": "fake-never-real"},
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
