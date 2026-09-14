"""Explicit projections for a source-bound guest preview and full account report.

Ownership and claim authorization must be resolved before calling this pure
projector. An access value from a request body/query is never accepted here.
Guests receive whole findings, with additional insights available after claim.
The canonical report is never shortened or mutated by this presentation boundary.
Internal provenance and future private fields never cross this explicit boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.reports import ReportDraft


class ReportAccess(StrEnum):
    GUEST = "guest_preview"
    ACCOUNT = "claimed_account"


_FINDING_LISTS = (
    "strengths",
    "improvements",
    "missed_opportunities",
    "objection_analysis",
    "closing_analysis",
)
_OVERVIEW_LISTS = ("golden_moments", "prospect_interpretations", "rewatch", "ethics_notes")


def _preview_size(total: int) -> int:
    # Keep one-item sections useful. Round to whole findings, reserving at least
    # one additional insight when there are two or more; never slice a quotation.
    return total if total < 2 else min(total - 1, (3 * total + 4) // 5)


def _guest_preview(content: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, dict[str, int]] = {}

    def record(name: str, total: int, visible: int) -> None:
        counts[name] = {
            "visible_count": visible,
            "total_count": total,
            "hidden_count": total - visible,
        }

    for name in _FINDING_LISTS:
        original = content[name]
        content[name] = original[: _preview_size(len(original))]
        record(name, len(original), len(content[name]))
    detail = content.get("overview")
    for name in _OVERVIEW_LISTS:
        original = detail[name] if detail is not None else []
        eligible = original
        if name == "golden_moments":
            eligible = [
                moment
                for moment in original
                if moment["strength_index"] < len(content["strengths"])
            ]
        visible = eligible[: _preview_size(len(original))]
        if detail is not None:
            detail[name] = visible
        record(name, len(original), len(visible))
    if detail is not None:
        for name, collection in (
            ("strength_details", "strengths"),
            ("improvement_details", "improvements"),
            ("missed_details", "missed_opportunities"),
        ):
            # Prefix selection preserves the original zero-based indices. Drop
            # linked explanations as well as the finding they would disclose.
            detail[name] = [
                item for item in detail[name] if item["finding_index"] < len(content[collection])
            ]
    return {"version": "guest-findings-v1", "sections": counts}


@dataclass(frozen=True)
class ReportSourceBinding:
    """Source identifiers selected from authorized server rows, never request fields."""

    recording_id: UUID
    run_id: UUID
    source_sha256: str
    transcript_revision: str

    def validate(self) -> None:
        if (
            type(self.recording_id) is not UUID
            or type(self.run_id) is not UUID
            or not isinstance(self.source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
            or not isinstance(self.transcript_revision, str)
            or not 1 <= len(self.transcript_revision) <= 256
        ):
            raise ValueError("A server-resolved report source binding is required.")


def project_bound_report(
    report: ReportDraft, *, access: ReportAccess, source: ReportSourceBinding
) -> dict[str, Any]:
    """Preserve source/seek association around the explicit guest/account projection.

    The caller must first authorize the recording, run and current ownership and
    select this binding from those rows. This pure function cannot prove row
    ownership and is not a substitute for that query boundary.
    """
    if type(source) is not ReportSourceBinding:
        raise ValueError("A server-resolved report source binding is required.")
    source.validate()
    view = project_report(report, access=access)
    if (
        report.source_sha256 != source.source_sha256
        or report.transcript_revision != source.transcript_revision
    ):
        raise ValueError("The report does not match the authorized recording and transcript.")
    return {
        "schema": "ac.sales-xray.report-envelope/2",
        "recording_id": str(source.recording_id),
        "run_id": str(source.run_id),
        "source_sha256": source.source_sha256,
        "transcript_revision": source.transcript_revision,
        "source_label": report.source_label,
        "report": view,
    }


def project_report(report: ReportDraft, *, access: ReportAccess) -> dict[str, Any]:
    if type(access) is not ReportAccess:
        raise ValueError("A server-resolved report access level is required.")
    # Revalidate even a model_construct/model_copy caller. No arbitrary extra
    # response fields, provider traces or future private fields can hitchhike.
    report = ReportDraft.model_validate_json(report.model_dump_json())
    account = access is ReportAccess.ACCOUNT
    fields: dict[str, Any] = {
        "summary": report.summary,
        "strengths": [item.model_dump(mode="json") for item in report.strengths],
        "missed_opportunities": [
            item.model_dump(mode="json") for item in report.missed_opportunities
        ],
        "dimensions": [item.model_dump(mode="json") for item in report.dimensions],
        "next_action": (
            report.improvements[0].model_dump(mode="json") if report.improvements else None
        ),
        "improvements": [item.model_dump(mode="json") for item in report.improvements],
        "objection_analysis": [item.model_dump(mode="json") for item in report.objection_analysis],
        "closing_analysis": [item.model_dump(mode="json") for item in report.closing_analysis],
        "verdict": report.verdict,
    }
    if report.overview is not None:
        fields["overview"] = report.overview.model_dump(mode="json")
    preview = None if account else _guest_preview(fields)
    return {
        "schema": "ac.sales-xray.report-access/2",
        "access": access.value,
        "review_status": report.review_status,
        "numeric_publication": False,
        "content": fields,
        "preview": preview,
        "sections": [
            {"id": "overview", "label": "Overview", "access": "available"},
            {"id": "moments", "label": "Call moments", "access": "available"},
            {"id": "transcript", "label": "Transcript", "access": "available"},
            {
                "id": "coaching",
                "label": "Your coaching plan",
                "access": "available",
            },
            {
                "id": "history",
                "label": "Your saved calls",
                "access": "available" if account else "sign_in",
            },
        ],
        "unlock": None
        if account
        else {
            "title": "Unlock remaining insights with a free account"
            if any(item["hidden_count"] for item in preview["sections"].values())
            else "Keep your report with your AC account",
            "description": "Sign in to see your full report and return to your saved calls.",
            "action": "Continue with a free account",
        },
    }
