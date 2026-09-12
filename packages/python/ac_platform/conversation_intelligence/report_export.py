"""Private, self-contained report exports; never a public upload or storage route."""

from __future__ import annotations

import base64
import hashlib
import html
from collections.abc import Mapping
from typing import Any

from ac_platform.conversation_intelligence.reports import ReportDraft

SECTIONS = (
    ("improvements", "Your three priorities"),
    ("strengths", "What worked"),
    ("missed_opportunities", "Where the conversation could improve"),
    ("objection_analysis", "Objections and business concerns"),
    ("closing_analysis", "The close and next step"),
)

_STYLE = """\
* { box-sizing: border-box; }
body { margin: 0; background: #f5f7fb; color: #1b3039;
  font: 16px/1.65 'Segoe UI', 'Nirmala UI', sans-serif; }
header, main { max-width: 1040px; margin: auto; padding: 28px; }
header { display: flex; justify-content: space-between; align-items: center; }
.brand { font-weight: 650; font-size: 20px; }
.brand small { display: block; font-size: 11px; letter-spacing: .15em; color: #526b77; }
.tag { color: #365343; background: #e6f3e9; padding: 5px 12px;
  border-radius: 20px; font-size: 12px; }
h1 { font: 52px/1.14 Georgia, serif; letter-spacing: -1px; margin: 20px 0; }
h2 { font: 30px/1.2 Georgia, serif; margin-top: 40px; }
h3 { font-size: 19px; line-height: 1.4; margin: 0 0 10px; }
p { margin: 10px 0 16px; }
.lead { font-size: 18px; max-width: 850px; }
.card, article { background: white; border: 1px solid #dbe2ec;
  border-radius: 14px; padding: 24px; margin: 14px 0; }
.card { border-top: 4px solid #3454c8; }
.player { position: sticky; top: 0; z-index: 2; background: #f5f7fbf5;
  padding: 12px 0; backdrop-filter: blur(8px); }
audio { width: 100%; height: 44px; }
button, summary { cursor: pointer; }
button { border: 1px solid #ccd7e8; background: #eef2ff; color: #2a4cc1;
  border-radius: 7px; padding: 7px 13px; font: inherit; }
button:hover { background: #dce5ff; }
summary { font-weight: 600; color: #3653b4; }
small, .muted { color: #5a6e7f; font-size: 13px; }
blockquote { margin: 18px 0 0; padding: 14px 18px; border-left: 3px solid #c2cee8;
  background: #f7f9fe; }
.note { font-size: 13px; padding: 20px; border: 1px solid #dbe2ec;
  border-radius: 12px; }
footer { margin: 40px 0; color: #637586; font-size: 12px; }
.transcript article { padding: 18px; }
@media (max-width: 650px) {
  header, main { padding: 18px; }
  h1 { font-size: 37px; }
  article { padding: 19px; }
  .tag { display: none; }
}
@media print {
  .player, button, summary { display: none; }
  body { background: white; font-size: 11pt; }
  article { break-inside: avoid; border: 0; padding: 8px 0; }
  header { padding: 0; }
  h1 { font-size: 30pt; }
  main { padding: 0; }
  .transcript { display: none; }
}
"""

_SCRIPT = (
    "const audio=document.getElementById('call');\n"
    "document.querySelectorAll('[data-seek]').forEach(button=>\n"
    "button.addEventListener('click',()=>{\n"
    "audio.currentTime=Number(button.dataset.seek);\n"
    "audio.play().catch(()=>{});\n"
    "}));\n"
    "document.getElementById('print').addEventListener('click',()=>window.print());"
)


def timestamp(milliseconds: int) -> str:
    if type(milliseconds) is not int or milliseconds < 0:
        raise ValueError("report_timestamp_invalid")
    return f"{milliseconds // 60000:02}:{milliseconds // 1000 % 60:02}"


def _markdown_escape(value: str) -> str:
    """Keep untrusted report text from becoming HTML, links or images in Markdown."""

    # Break bare-URL/email syntax before a Markdown renderer can autolink it.
    escaped = html.escape(value, quote=False).replace(":", ":\u200b").replace("@", "@\u200b")
    markdown_metacharacters = r"\\`*_{}[]()#+-.!|>"
    return "".join(
        "\\" + character if character in markdown_metacharacters else character
        for character in escaped
    )


def report_markdown(report: ReportDraft) -> str:
    lines = [
        "# Your sales-call report",
        "",
        _markdown_escape(report.source_label),
        "",
        "**Private AI draft. Awaiting Dipak’s sales "
        "review and Suyash’s measurement/attribution review.**",
        "",
        _markdown_escape(report.summary),
        "",
    ]
    for field, label in SECTIONS:
        lines.extend([f"## {label}", ""])
        for finding in getattr(report, field):
            lines.extend(
                [
                    f"### {_markdown_escape(finding.title)}",
                    "",
                    _markdown_escape(finding.explanation),
                    "",
                ]
            )
            for evidence in finding.evidence:
                quote = _markdown_escape(evidence.quote).replace("\n", "\n> ")
                lines.extend(
                    [
                        f"**{timestamp(evidence.start_ms)} · "
                        f"{_markdown_escape(evidence.segment_id)}**",
                        "",
                        "> " + quote,
                        "",
                    ]
                )
    lines.extend(
        [
            "## Overall assessment",
            "",
            _markdown_escape(report.verdict),
            "",
            "No numeric grade: source weights total 95 against a declared 100. "
            "Speaker labels and provider timestamps remain unverified; no "
            "acoustic-to-personality claims.",
            "",
            "Source SHA-256: " + report.source_sha256,
            "",
            "Transcript revision: " + _markdown_escape(report.transcript_revision),
            "",
            "This export checks supplied evidence consistency. It does not establish "
            "independent source review, human adjudication or release approval.",
        ]
    )
    return "\n".join(lines)


def _validated_segments(report: ReportDraft, transcript: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (
        transcript.get("revision") != report.transcript_revision
        or transcript.get("source_sha256") != report.source_sha256
    ):
        raise ValueError("report_transcript_source_mismatch")
    raw_segments = transcript.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("report_transcript_segments_invalid")
    duration = transcript.get("duration_ms")
    segments: list[dict[str, Any]] = []
    by_id: set[str] = set()
    upper_bound = 0
    for raw in raw_segments:
        if not isinstance(raw, Mapping):
            raise ValueError("report_transcript_segment_invalid")
        segment_id = raw.get("id")
        speaker_id = raw.get("speaker_id")
        start_ms = raw.get("start_ms")
        end_ms = raw.get("end_ms")
        text = raw.get("text")
        if (
            not isinstance(segment_id, str)
            or not segment_id.strip()
            or segment_id in by_id
            or not isinstance(speaker_id, str)
            or not speaker_id.strip()
            or type(start_ms) is not int
            or type(end_ms) is not int
            or start_ms < 0
            or end_ms <= start_ms
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError("report_transcript_segment_invalid")
        by_id.add(segment_id)
        upper_bound = max(upper_bound, end_ms)
        segments.append(
            {
                "id": segment_id,
                "speaker_id": speaker_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
            }
        )
    if duration is not None and (
        type(duration) is not int or duration < upper_bound or duration <= 0
    ):
        raise ValueError("report_transcript_duration_invalid")
    return segments


def _validate_report_evidence(report: ReportDraft, segments: list[dict[str, Any]]) -> None:
    by_id = {segment["id"]: segment for segment in segments}
    for field, _ in SECTIONS:
        for finding in getattr(report, field):
            for evidence in finding.evidence:
                segment = by_id.get(evidence.segment_id)
                if segment is None:
                    raise ValueError("report_evidence_segment_invalid")
                if evidence.quote not in segment["text"]:
                    raise ValueError("report_evidence_quote_mismatch")
                if (evidence.start_ms, evidence.end_ms) != (
                    segment["start_ms"],
                    segment["end_ms"],
                ):
                    raise ValueError("report_evidence_timing_mismatch")


def _seek(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def report_html(
    report: ReportDraft,
    transcript: Mapping[str, Any],
    *,
    original_audio: bytes,
) -> str:
    if type(original_audio) is not bytes or not original_audio:
        raise ValueError("report_audio_invalid")
    if hashlib.sha256(original_audio).hexdigest() != report.source_sha256:
        raise ValueError("report_audio_source_mismatch")
    segments = _validated_segments(report, transcript)
    _validate_report_evidence(report, segments)
    escape = html.escape
    sections: list[str] = []
    for field, label in SECTIONS:
        section_parts = [f"<section><h2>{escape(label)}</h2>"]
        for finding in getattr(report, field):
            evidence_html: list[str] = []
            for evidence in finding.evidence:
                evidence_html.append(
                    "<blockquote>"
                    f'<button data-seek="{_seek(evidence.start_ms)}">'
                    f"▶ {timestamp(evidence.start_ms)}</button> "
                    f"<small>{escape(evidence.segment_id)}</small>"
                    f'<p lang="und">{escape(evidence.quote)}</p>'
                    "</blockquote>"
                )
            section_parts.append(
                "<article>"
                f"<h3>{escape(finding.title)}</h3>"
                f"<p>{escape(finding.explanation)}</p>"
                '<details><summary>Listen to the evidence</summary>'
                + "".join(evidence_html)
                + "</details></article>"
            )
        section_parts.append("</section>")
        sections.append("".join(section_parts))
    transcript_rows = "".join(
        "<article>"
        f'<button data-seek="{_seek(segment["start_ms"])}">'
        f'▶ {timestamp(segment["start_ms"])}</button> '
        f'<small>{escape(segment["speaker_id"])} · {escape(segment["id"])}</small>'
        f'<p lang="und">{escape(segment["text"])}</p>'
        "</article>"
        for segment in segments
    )
    script_hash = base64.b64encode(hashlib.sha256(_SCRIPT.encode()).digest()).decode()
    encoded_audio = base64.b64encode(original_audio).decode()
    source_label = escape(report.source_label)
    summary = escape(report.summary)
    verdict = escape(report.verdict)
    section_html = "".join(sections)
    csp = (
        "default-src 'none'; media-src data:; img-src 'none'; font-src 'none'; "
        "style-src 'unsafe-inline'; "
        f"script-src 'sha256-{script_hash}'; connect-src 'none'; object-src 'none'; "
        "frame-src 'none'; worker-src 'none'; manifest-src 'none'; base-uri 'none'; "
        "form-action 'none'"
    )
    segment_count = len(segments)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>Your call report · Dipak’s Sales Xray</title>
<style>{_STYLE}</style></head>
<body><header><div class="brand">Dipak’s Sales Xray
<small>AUTHORITY CLOSERS</small></div><span class="tag">Private call report</span></header>
<main><div class="muted">{source_label} · AI draft</div>
<h1>Your call.<br>Your next step.</h1>
<p class="lead">{summary}</p>
<div class="player"><audio id="call" controls preload="metadata"
src="data:audio/mpeg;base64,{encoded_audio}"></audio>
<small>Click a timestamp below to listen. The recording is included in this private file;
no upload or internet connection is needed.</small></div>
<div class="card"><h3>The call’s outcome</h3><p>{verdict}</p></div>
{section_html}
<div class="note"><strong>How to read this report</strong>
<p>This is an AI coaching draft based on Dipak’s supplied AC principles. Export validation
checks supplied evidence consistency; it does not establish independent source review.
It has not been adjudicated by Dipak or measurement-validated by Suyash.</p>
<p>No numeric grade is published: the source weights total 95 against a declared 100.
Speaker labels are unverified. Timestamps use Scribe’s native clock; exact AudioAtlas
alignment is not certified. No personality or vocal-tone conclusions are made.</p></div>
<details class="transcript"><summary><h2>Read the full transcript · {segment_count} segments</h2>
</summary>{transcript_rows}</details>
<footer>Private AI draft · No automatic
retraining · No public publication<br>Source SHA-256: {escape(report.source_sha256)}
<br>Transcript revision: {escape(report.transcript_revision)}
<br><button id="print">Print / Save as PDF</button></footer>
</main><script>{_SCRIPT}</script></body></html>"""


__all__ = ["SECTIONS", "report_html", "report_markdown", "timestamp"]
