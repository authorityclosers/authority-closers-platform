"""Explicit report projections. Locked sections never cross the API boundary.

Ownership and claim authorization must be resolved before calling this pure
projector. An access value from a request body/query is never accepted here.
The preview is a useful section selection, not a percentage of report bytes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from ac_platform.conversation_intelligence.reports import ReportDraft


class ReportAccess(StrEnum):
    GUEST = "guest_preview"
    ACCOUNT = "claimed_account"


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
