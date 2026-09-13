"""Security and provenance tests for the private report export."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from ac_platform.conversation_intelligence.report_export import (
    report_html,
    report_markdown,
    timestamp,
)
from ac_platform.conversation_intelligence.reports import parse_report_draft


def _transcript(audio: bytes) -> dict[str, Any]:
    return {
        "source_sha256": hashlib.sha256(audio).hexdigest(),
        "revision": "scribe-test-r1",
        "timebase_id": "elevenlabs-scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "s1",
                "speaker_id": "unattributed",
                "start_ms": 0,
                "end_ms": 900,
                "text": (
                    '<img src="https://evil.test/x" onerror="alert(1)"> '
                    "& [click](https://evil.test)"
                ),
            }
        ],
    }


def _report(transcript: dict[str, Any], *, audio: bytes) -> Any:
    quote = transcript["segments"][0]["text"]
    finding = {
        "title": "<script>alert(1)</script> ![x](https://evil.test)",
        "explanation": "<img src=x> & a [link](https://evil.test)",
        "evidence": [{"segment_id": "s1", "quote": quote, "start_ms": 0, "end_ms": 900}],
    }
    payload = {
        "summary": "<script>alert(1)</script> ![summary](https://evil.test)",
        "strengths": [finding],
        "missed_opportunities": [],
        "improvements": [finding],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "<b>untrusted verdict</b>",
        "review_status": "draft_not_dipak_adjudicated",
    }
    return parse_report_draft(
        payload,
        transcript,
        source_label='</div><img src="https://evil.test">',
    )


def test_html_escapes_untrusted_report_and_transcript_text() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    output = report_html(_report(transcript, audio=audio), transcript, original_audio=audio)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in output
    assert "&lt;img src=&quot;https://evil.test/x&quot;" in output
    assert '<img src="https://evil.test">' not in output
    assert "<script>alert(1)</script>" not in output
    assert "https://evil.test/x" in output


def test_markdown_escapes_raw_html_links_and_images() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    output = report_markdown(_report(transcript, audio=audio))

    assert "<img" not in output.lower()
    assert "![" not in output
    assert "](" not in output
    assert "&lt;img" in output
    assert "\\[link\\]" in output
    assert "https://" not in output
    assert "https:\u200b//" in output


def test_export_does_not_invent_source_review_and_retains_binding_metadata() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    report = _report(transcript, audio=audio)
    for output in (
        report_markdown(report),
        report_html(report, transcript, original_audio=audio),
    ):
        assert "corrected against source evidence" not in output
        assert "source-reviewed draft" not in output
        assert "Reviewed draft" not in output
        assert report.source_sha256 in output
        assert "Transcript revision:" in output
        assert "does not establish independent source review" in output


def test_html_has_no_external_connections_or_assets_and_dynamic_segment_count() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    output = report_html(_report(transcript, audio=audio), transcript, original_audio=audio)
    lower = output.lower()

    assert "connect-src 'none'" in lower
    assert "img-src 'none'" in lower
    assert "font-src 'none'" in lower
    assert "object-src 'none'" in lower
    assert "frame-src 'none'" in lower
    assert "<link" not in lower
    assert re.search(r"(?:src|href)\s*=\s*[\"']https?://", output) is None
    assert "· 1 segments" in output
    assert "144 segments" not in output


def test_export_requires_exact_audio_and_transcript_binding() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    report = _report(transcript, audio=audio)

    with pytest.raises(ValueError, match="report_audio_source_mismatch"):
        report_html(report, transcript, original_audio=b"other-audio")

    wrong_source = dict(transcript)
    wrong_source["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="report_transcript_source_mismatch"):
        report_html(report, wrong_source, original_audio=audio)

    wrong_revision = dict(transcript)
    wrong_revision["revision"] = "scribe-test-r2"
    with pytest.raises(ValueError, match="report_transcript_source_mismatch"):
        report_html(report, wrong_revision, original_audio=audio)


def test_export_uses_derived_segment_bounds_for_timestamps() -> None:
    audio = b"synthetic-audio"
    transcript = _transcript(audio)
    report = _report(transcript, audio=audio)
    finding = report.strengths[0]
    bad_evidence = finding.evidence[0].model_copy(update={"end_ms": 901})
    bad_finding = finding.model_copy(update={"evidence": [bad_evidence]})
    bad_report = report.model_copy(update={"strengths": [bad_finding]})

    with pytest.raises(ValueError, match="report_evidence_timing_mismatch"):
        report_html(bad_report, transcript, original_audio=audio)
    with pytest.raises(ValueError, match="report_transcript_duration_invalid"):
        report_html(report, {**transcript, "duration_ms": 10}, original_audio=audio)
    with pytest.raises(ValueError, match="report_timestamp_invalid"):
        timestamp(-1)
