"""Private, self-contained report exports; never a public upload or storage route."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import re
import zipfile
from collections.abc import Mapping
from typing import Any, cast
from xml.etree import ElementTree as ET

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

_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_DCTERMS_NS = "http://purl.org/dc/terms/"
_XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

ET.register_namespace("w", _W_NS)
ET.register_namespace("r", _R_NS)
ET.register_namespace("cp", _CP_NS)
ET.register_namespace("dc", _DC_NS)
ET.register_namespace("dcterms", _DCTERMS_NS)
ET.register_namespace("xsi", _XSI_NS)


def _w(tag: str) -> str:
    return f"{{{_W_NS}}}{tag}"


def _docx_run(text: str, *, bold: bool = False, italic: bool = False) -> ET.Element:
    run = ET.Element(_w("r"))
    if bold or italic:
        properties = ET.SubElement(run, _w("rPr"))
        if bold:
            ET.SubElement(properties, _w("b"))
        if italic:
            ET.SubElement(properties, _w("i"))
    lines = text.splitlines() or [""]
    for index, line in enumerate(lines):
        if index:
            ET.SubElement(run, _w("br"))
        node = ET.SubElement(run, _w("t"))
        if line[:1].isspace() or line[-1:].isspace():
            node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = line
    return run


def _docx_paragraph(
    text: str = "",
    *,
    style: str | None = None,
    bold: bool = False,
    italic: bool = False,
) -> ET.Element:
    paragraph = ET.Element(_w("p"))
    properties = ET.SubElement(paragraph, _w("pPr"))
    if style is not None:
        style_node = ET.SubElement(properties, _w("pStyle"))
        style_node.set(_w("val"), style)
    if style in {"Title", "Subtitle", "Heading1", "Heading2", "Heading3"}:
        ET.SubElement(properties, _w("keepNext"))
    paragraph.append(_docx_run(text, bold=bold, italic=italic))
    return paragraph


def _docx_labeled_paragraph(label: str, value: object) -> ET.Element:
    paragraph = ET.Element(_w("p"))
    paragraph.append(_docx_run(f"{label}: ", bold=True))
    paragraph.append(_docx_run(str(value)))
    return paragraph


def _human_label(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def _docx_heading(body: ET.Element, text: str, level: int) -> None:
    body.append(_docx_paragraph(text, style=f"Heading{min(max(level, 1), 3)}"))


def _docx_bullet(body: ET.Element, text: str) -> None:
    body.append(_docx_paragraph(text, style="ListBullet"))


def _docx_evidence(body: ET.Element, evidence: Mapping[str, Any]) -> None:
    segment_id = evidence.get("segment_id")
    start_ms = evidence.get("start_ms")
    end_ms = evidence.get("end_ms")
    quote = evidence.get("quote")
    if not isinstance(segment_id, str) or not isinstance(quote, str):
        raise ValueError("report_docx_evidence_invalid")
    if type(start_ms) is not int or type(end_ms) is not int:
        raise ValueError("report_docx_evidence_invalid")
    body.append(
        _docx_paragraph(
            f"{timestamp(start_ms)}-{timestamp(end_ms)} · {segment_id}",
            style="Heading3",
        )
    )
    body.append(_docx_paragraph(quote, style="Quote"))


def _docx_findings(body: ET.Element, findings: object) -> None:
    if not isinstance(findings, list):
        raise ValueError("report_docx_findings_invalid")
    if not findings:
        body.append(_docx_paragraph("No evidence-backed finding was recorded."))
        return
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise ValueError("report_docx_finding_invalid")
        title = finding.get("title")
        explanation = finding.get("explanation")
        evidence = finding.get("evidence")
        if not isinstance(title, str) or not isinstance(explanation, str):
            raise ValueError("report_docx_finding_invalid")
        _docx_heading(body, title, 2)
        body.append(_docx_paragraph(explanation))
        if not isinstance(evidence, list):
            raise ValueError("report_docx_finding_invalid")
        for item in evidence:
            if not isinstance(item, Mapping):
                raise ValueError("report_docx_evidence_invalid")
            _docx_evidence(body, item)


def _docx_nested_value(body: ET.Element, label: str, value: object, depth: int = 2) -> None:
    if isinstance(value, Mapping):
        _docx_heading(body, label, depth)
        for key, child in value.items():
            _docx_nested_value(body, _human_label(str(key)), child, min(depth + 1, 3))
        return
    if isinstance(value, list):
        if not value:
            body.append(_docx_labeled_paragraph(label, "None recorded"))
            return
        for index, child in enumerate(value, start=1):
            if isinstance(child, Mapping):
                _docx_heading(body, f"{label} {index}", depth)
                for key, nested in child.items():
                    if key == "evidence" and isinstance(nested, list):
                        for evidence in nested:
                            if isinstance(evidence, Mapping):
                                _docx_evidence(body, evidence)
                            else:
                                raise ValueError("report_docx_evidence_invalid")
                    else:
                        _docx_nested_value(body, _human_label(str(key)), nested, min(depth + 1, 3))
            else:
                _docx_bullet(body, str(child))
        return
    body.append(_docx_labeled_paragraph(label, "None recorded" if value is None else value))


def _docx_styles() -> bytes:
    styles = ET.Element(_w("styles"))

    def style(style_id: str, *, name: str, based_on: str = "Normal", size: str = "22") -> None:
        node = ET.SubElement(
            styles,
            _w("style"),
            {_w("type"): "paragraph", _w("styleId"): style_id},
        )
        ET.SubElement(node, _w("name"), {_w("val"): name})
        ET.SubElement(node, _w("basedOn"), {_w("val"): based_on})
        properties = ET.SubElement(node, _w("rPr"))
        ET.SubElement(properties, _w("rFonts"), {_w("ascii"): "Aptos", _w("hAnsi"): "Aptos"})
        ET.SubElement(properties, _w("sz"), {_w("val"): size})
        ET.SubElement(properties, _w("color"), {_w("val"): "000000"})

    style("Normal", name="Normal", size="22")
    style("Title", name="Title", size="36")
    style("Subtitle", name="Subtitle", size="22")
    style("Heading1", name="Heading 1", size="28")
    style("Heading2", name="Heading 2", size="24")
    style("Heading3", name="Heading 3", size="21")
    style("Quote", name="Quote", size="21")
    style("ListBullet", name="List Bullet", size="21")
    return cast(bytes, ET.tostring(styles, encoding="utf-8", xml_declaration=True))


def _docx_document(body: ET.Element) -> bytes:
    section = ET.SubElement(body, _w("sectPr"))
    ET.SubElement(section, _w("pgSz"), {_w("w"): "12240", _w("h"): "15840"})
    ET.SubElement(
        section,
        _w("pgMar"),
        {_w("top"): "1080", _w("right"): "1080", _w("bottom"): "1080", _w("left"): "1080"},
    )
    document = ET.Element(_w("document"))
    document.append(body)
    return cast(bytes, ET.tostring(document, encoding="utf-8", xml_declaration=True))


def _docx_core_properties(title: str) -> bytes:
    root = ET.Element(f"{{{_CP_NS}}}coreProperties")
    ET.SubElement(root, f"{{{_DC_NS}}}title").text = title
    ET.SubElement(root, f"{{{_DC_NS}}}creator").text = "Authority Closers"
    created = ET.SubElement(root, f"{{{_DCTERMS_NS}}}created")
    created.set(f"{{{_XSI_NS}}}type", "dcterms:W3CDTF")
    created.text = "2026-01-01T00:00:00Z"
    return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _docx_package(document: bytes, *, title: str) -> bytes:
    content_types = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        b'package.relationships+xml"/>\n'
        b'<Default Extension="xml" ContentType="application/xml"/>\n'
        b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
        b'officedocument.wordprocessingml.document.main+xml"/>\n'
        b'<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-'
        b'officedocument.wordprocessingml.styles+xml"/>\n'
        b'<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-'
        b'package.core-properties+xml"/>\n'
        b"</Types>"
    )
    package_rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
        b'relationships/metadata/core-properties" Target="docProps/core.xml"/>\n'
        b"</Relationships>"
    )
    document_rels = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
        b'2006/relationships/styles" Target="styles.xml"/>\n'
        b"</Relationships>"
    )
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", package_rels)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", _docx_styles())
        archive.writestr("word/_rels/document.xml.rels", document_rels)
        archive.writestr("docProps/core.xml", _docx_core_properties(title))
    return result.getvalue()


def report_docx_bytes(envelope: Mapping[str, Any]) -> bytes:
    """Build a genuine, self-contained Word document from a projected report envelope."""

    if (
        not isinstance(envelope, Mapping)
        or envelope.get("schema") != "ac.sales-xray.report-envelope/2"
    ):
        raise ValueError("report_docx_envelope_invalid")
    source_label = envelope.get("source_label")
    source_sha256 = envelope.get("source_sha256")
    transcript_revision = envelope.get("transcript_revision")
    report = envelope.get("report")
    access = report.get("access") if isinstance(report, Mapping) else None
    if access not in {"guest_preview", "claimed_account"}:
        raise ValueError("report_docx_access_invalid")
    if (
        not isinstance(source_label, str)
        or not isinstance(source_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        or not isinstance(transcript_revision, str)
        or not isinstance(report, Mapping)
        or report.get("schema") != "ac.sales-xray.report-access/2"
        or report.get("access") != access
        or not isinstance(report.get("content"), Mapping)
    ):
        raise ValueError("report_docx_envelope_invalid")
    content = report["content"]
    body = ET.Element(_w("body"))
    body.append(_docx_paragraph("Your Sales Call Report", style="Title"))
    body.append(_docx_paragraph(source_label, style="Subtitle"))
    body.append(
        _docx_paragraph(
            "Private qualitative AI draft. This document preserves the saved report and its "
            "source references; it is not a numeric score or human adjudication."
        )
    )
    preview = report.get("preview")
    if access == "guest_preview" and isinstance(preview, Mapping):
        hidden = sum(
            int(item.get("hidden_count", 0))
            for item in preview.get("sections", {}).values()
            if isinstance(item, Mapping) and type(item.get("hidden_count")) is int
        )
        if hidden:
            body.append(
                _docx_paragraph(
                    "Guest preview: some saved findings remain available after account claim."
                )
            )

    _docx_heading(body, "Call summary", 1)
    for key in ("summary", "verdict"):
        value = content.get(key)
        if not isinstance(value, str):
            raise ValueError("report_docx_content_invalid")
        body.append(_docx_labeled_paragraph(_human_label(key), value))

    for field, label in SECTIONS:
        _docx_heading(body, label, 1)
        _docx_findings(body, content.get(field))

    dimensions = content.get("dimensions")
    if not isinstance(dimensions, list):
        raise ValueError("report_docx_dimensions_invalid")
    _docx_heading(body, "Dimensions and uncertainty", 1)
    for dimension in dimensions:
        if not isinstance(dimension, Mapping):
            raise ValueError("report_docx_dimension_invalid")
        dimension_label = dimension.get("label")
        status = dimension.get("status")
        observation = dimension.get("observation")
        citations = dimension.get("citations")
        if (
            not isinstance(dimension_label, str)
            or not isinstance(status, str)
            or not isinstance(observation, str)
        ):
            raise ValueError("report_docx_dimension_invalid")
        _docx_heading(body, dimension_label, 2)
        body.append(_docx_labeled_paragraph("Status", status))
        body.append(_docx_labeled_paragraph("Observation", observation))
        if not isinstance(citations, list):
            raise ValueError("report_docx_dimension_invalid")
        for citation in citations:
            if not isinstance(citation, Mapping):
                raise ValueError("report_docx_citation_invalid")
            doc = citation.get("doc")
            sections = citation.get("sections")
            if (
                not isinstance(doc, str)
                or not isinstance(sections, list)
                or not all(isinstance(section, str) for section in sections)
            ):
                raise ValueError("report_docx_citation_invalid")
            _docx_bullet(body, f"Source reference: {doc}, {', '.join(sections)}")

    overview = content.get("overview")
    if overview is not None:
        if not isinstance(overview, Mapping):
            raise ValueError("report_docx_overview_invalid")
        _docx_heading(body, "Detailed overview", 1)
        for key, value in overview.items():
            _docx_nested_value(body, _human_label(str(key)), value)

    _docx_heading(body, "Report provenance", 1)
    body.append(_docx_labeled_paragraph("Access", access))
    body.append(_docx_labeled_paragraph("Review status", report.get("review_status")))
    body.append(_docx_labeled_paragraph("Numeric publication", report.get("numeric_publication")))
    body.append(_docx_labeled_paragraph("Source SHA-256", source_sha256))
    body.append(_docx_labeled_paragraph("Transcript revision", transcript_revision))
    body.append(
        _docx_paragraph(
            "Speaker labels and provider timestamps remain unverified. The report does not make "
            "acoustic, personality or vocal-tone claims."
        )
    )
    document = _docx_document(body)
    return _docx_package(document, title=f"Sales call report - {source_label}")


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
                "<details><summary>Listen to the evidence</summary>"
                + "".join(evidence_html)
                + "</details></article>"
            )
        section_parts.append("</section>")
        sections.append("".join(section_parts))
    transcript_rows = "".join(
        "<article>"
        f'<button data-seek="{_seek(segment["start_ms"])}">'
        f"▶ {timestamp(segment['start_ms'])}</button> "
        f"<small>{escape(segment['speaker_id'])} · {escape(segment['id'])}</small>"
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


__all__ = ["SECTIONS", "report_docx_bytes", "report_html", "report_markdown", "timestamp"]
