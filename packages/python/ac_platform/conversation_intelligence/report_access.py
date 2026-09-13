"""Explicit report projections. Locked sections never cross the API boundary.

Ownership and claim authorization must be resolved before calling this pure
projector. An access value from a request body/query is never accepted here.
The preview is a useful section selection, not a percentage of report bytes.
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
        "schema": "ac.sales-xray.report-envelope/1",
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
    }
    if account:
        fields.update(
            improvements=[item.model_dump(mode="json") for item in report.improvements],
            objection_analysis=[item.model_dump(mode="json") for item in report.objection_analysis],
            closing_analysis=[item.model_dump(mode="json") for item in report.closing_analysis],
            verdict=report.verdict,
        )
    return {
        "schema": "ac.sales-xray.report-access/1",
        "access": access.value,
        "review_status": report.review_status,
        "numeric_publication": False,
        "content": fields,
        "sections": [
            {"id": "overview", "label": "Overview", "access": "available"},
            {"id": "moments", "label": "Call moments", "access": "available"},
            {"id": "transcript", "label": "Transcript", "access": "available"},
            {
                "id": "coaching",
                "label": "Your coaching plan",
                "access": "available" if account else "sign_in",
            },
        ],
        "unlock": None
        if account
        else {
            "title": "Keep going with your coaching plan",
            "description": (
                "Sign in free to explore your objections, closing approach and next steps."
            ),
            "action": "Sign in to unlock",
        },
    }
