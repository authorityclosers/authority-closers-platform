"""Small, source-referenced Report projection of already validated C5 output.

No provider call, scoring, new extraction, agreement inference or state write.
The browser resolves each reference against the same bound transcript. Legacy
reports omit this extension and remain readable with explicit information gaps.
"""

from typing import Any

from ac_platform.conversation_intelligence.reports import ReportDraft


def report_story(report: ReportDraft) -> dict[str, Any] | None:
    call_map = report.call_map
    if call_map is None:
        return None
    return {
        "version": "report-story/1",
        "phases": [phase.model_dump(mode="json") for phase in call_map.phases],
        "outcome": call_map.outcome.model_dump(mode="json"),
        "next_step": next(
            (
                {"text": signal.text, "evidence": [e.model_dump() for e in signal.evidence]}
                for signal in call_map.signals
                if signal.kind == "next_step_agreed"
            ),
            None,
        ),
        "prospect_commitments": [item.model_dump(mode="json") for item in call_map.prospect_tasks],
        "seller_commitments": [
            {
                "text": item.text,
                "due_text": item.due_text,
                "evidence": [e.model_dump() for e in item.evidence],
            }
            for item in call_map.seller_tasks
        ],
    }
