from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import wave
from types import SimpleNamespace

import pytest

import ac_platform.development.sales_xray_samples as samples
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.gemini_tasks import decode_gemini_object
from ac_platform.conversation_intelligence.providers import ProviderResult, scribe_transcript
from ac_platform.conversation_intelligence.reports import (
    coaching_source_context,
    load_report_profile,
    parse_report_draft,
)
from ac_platform.development.sales_xray_sample_fakes import (
    _AUDIO_DURATION_SECONDS,
    FictionalReportingBroker,
    _transcript_words,
    fictional_audio,
)

TARGET = {
    "AC_ENVIRONMENT": "development",
    "AC_DATABASE_URL": "postgresql+psycopg://ac_runtime:local-only@127.0.0.1:55432/ac_platform",
    "AC_SALES_XRAY_APP_URL": "https://salesxray-dev.authorityclosers.com",
    "AC_EXTERNAL_SIDE_EFFECTS_HOLD": "true",
}


def test_pinned_dev_target_is_accepted() -> None:
    samples.require_sample_target(TARGET, acknowledged=True)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AC_ENVIRONMENT", "staging"),
        ("AC_ENVIRONMENT", "production"),
        ("AC_ENVIRONMENT", "local"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@localhost:55432/ac_platform"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@127.0.0.1:5432/ac_platform"),
        ("AC_DATABASE_URL", "postgresql+psycopg://ac_runtime:p@127.0.0.1:55432/other"),
        ("AC_DATABASE_URL", "postgresql+psycopg://other:p@127.0.0.1:55432/ac_platform"),
        (
            "AC_DATABASE_URL",
            "postgresql+psycopg://ac_runtime:p@127.0.0.1:55432/ac_platform?sslmode=require",
        ),
        ("AC_SALES_XRAY_APP_URL", "https://salesxray.authorityclosers.com"),
        ("AC_EXTERNAL_SIDE_EFFECTS_HOLD", "false"),
    ],
)
def test_every_target_guard_refuses(key: str, value: str) -> None:
    environ = dict(TARGET)
    environ[key] = value
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(environ, acknowledged=True)


def test_acknowledgement_is_required() -> None:
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(TARGET, acknowledged=False)


def test_pg_environment_variables_are_refused() -> None:
    environ = {**TARGET, "PGHOST": "127.0.0.1"}
    with pytest.raises(samples.SampleRefused):
        samples.require_sample_target(environ, acknowledged=True)


@pytest.mark.parametrize(
    ("key", "value", "acknowledged"),
    [
        ("AC_ENVIRONMENT", "production", True),
        ("AC_DATABASE_URL", "postgresql+psycopg://bad@db.invalid/ac_platform", True),
        ("AC_SALES_XRAY_APP_URL", "https://salesxray.authorityclosers.com", True),
        ("AC_EXTERNAL_SIDE_EFFECTS_HOLD", "false", True),
        ("", "", False),
        ("PGHOST", "127.0.0.1", True),
    ],
)
def test_cli_refuses_before_settings_or_database_creation(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str, acknowledged: bool
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("PG"):
            monkeypatch.delenv(name, raising=False)
    for name, target_value in TARGET.items():
        monkeypatch.setenv(name, target_value)
    if key:
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(samples, "Settings", lambda **_: pytest.fail("Settings touched"))
    monkeypatch.setattr(samples, "create_async_engine", lambda *_: pytest.fail("DB touched"))
    args = ["--email", "tester@example.test"]
    if acknowledged:
        args.append("--acknowledge-dev-samples")
    assert samples.main(args) == 2


@pytest.mark.parametrize(
    ("maximum", "cap", "accepted"),
    [
        (0, 0, True),
        (1, 100_000, True),
        (100_000, 100_000, True),
        (100_001, 100_000, False),
        (-1, 100_000, False),
        (True, 100_000, False),
    ],
)
def test_sample_quote_must_fit_current_dev_budget_cap(
    maximum: int, cap: int, accepted: bool
) -> None:
    assert samples.quote_within_budget({"max_cost_paise": maximum}, cap) is accepted


def test_fictional_audio_covers_the_full_transcript_in_mono_16khz() -> None:
    _text, words = _transcript_words("elevenlabs")
    audio = fictional_audio(1)
    with wave.open(io.BytesIO(audio), "rb") as source:
        assert source.getnchannels() == 1
        assert source.getframerate() == 16_000
        duration = source.getnframes() / source.getframerate()
    assert duration == _AUDIO_DURATION_SECONDS
    assert duration >= max(word["end"] for word in words)


def test_fake_c4_result_uses_gemini_envelope_and_zero_usage() -> None:
    request = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(
                            {
                                "schema": "ac.sales-xray.native-scribe-input/1",
                                "segments": [{"id": "s1", "text": "The price feels high."}],
                            }
                        )
                    }
                ],
            }
        ]
    }
    payload = canonical(request)
    reservation = SimpleNamespace(
        quote=SimpleNamespace(
            provider_id="gemini",
            provider_model="gemini-3.8-flash",
            input_sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    result = asyncio.run(FictionalReportingBroker().execute(reservation, payload))
    facts = decode_gemini_object(result.data)

    assert facts["observations"][0]["segment_id"] == "s1"
    assert all(value == 0 for value in result.usage.values())


def test_fake_report_is_complete_and_passes_source_quote_validation() -> None:
    source_sha256 = "a" * 64
    text, words = _transcript_words("elevenlabs")
    transcription_data = {"text": text, "words": words}
    transcription_raw = canonical(transcription_data)
    transcription_sha256 = hashlib.sha256(transcription_raw).hexdigest()
    transcript = scribe_transcript(
        ProviderResult(
            "elevenlabs",
            "scribe_v2",
            "fictional-sample-unit",
            transcription_sha256,
            transcription_raw,
            transcription_data,
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            source_sha256,
        ),
        duration_ms=_AUDIO_DURATION_SECONDS * 1000,
        source_sha256=source_sha256,
    )
    transcript["duration_ms"] = _AUDIO_DURATION_SECONDS * 1000
    facts = {"source_context": coaching_source_context(transcript), "observations": []}
    user = "Complete transcript + selective C4 observations:\n" + json.dumps(
        facts, ensure_ascii=False, separators=(",", ":")
    )
    payload = canonical({"contents": [{"parts": [{"text": user}]}]})
    reservation = SimpleNamespace(
        quote=SimpleNamespace(
            provider_id="gemini",
            provider_model="gemini-3.8-flash",
            input_sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    result = asyncio.run(FictionalReportingBroker().execute(reservation, payload))
    response = json.loads(result.data["candidates"][0]["content"]["parts"][0]["text"])
    report = parse_report_draft(
        response,
        transcript,
        source_label="Fictional sample",
        profile=load_report_profile(),
    )
    for section in (
        report.strengths,
        report.missed_opportunities,
        report.improvements,
        report.objection_analysis,
        report.closing_analysis,
        report.overview.strength_details,
        report.overview.improvement_details,
        report.overview.golden_moments,
        report.overview.missed_details,
        report.overview.prospect_interpretations,
        report.overview.rewatch,
        report.overview.ethics_notes,
    ):
        assert len(section) >= 2
    assert "not an official score" in report.summary
    assert "not an official score" in report.verdict
