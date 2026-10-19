"""A saved report's coaching as stable points, for Review 2.0's coaching pipeline.

Reviewers judge coaching points, not the report's layout: this is the one place
that knows where coaching sits in a saved report (dipak-14-point-v1 overview).
If the report changes shape, only this mapping changes; verdicts stay bound to
each point by key and by the digest of what it says. Pure.
"""

from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def coaching_points(report: Any) -> list[dict[str, str]]:
    """Each coaching point: a stable key, its kind, a short title and what it says."""
    if not isinstance(report, dict):
        return []
    overview = report.get("overview")
    if not isinstance(overview, dict):
        return []
    listed = report.get("improvements")
    improvements: list[Any] = listed if isinstance(listed, list) else []
    points: list[dict[str, str]] = []

    focus = overview.get("next_call_focus")
    if isinstance(focus, dict) and _text(focus.get("behavior")):
        target = _text(focus.get("target"))
        points.append(
            {
                "key": "focus",
                "kind": "focus",
                "title": "What to work on now",
                "text": _text(focus.get("behavior")) + (f" · Target: {target}" if target else ""),
            }
        )
    diagnosis = overview.get("diagnosis")
    if isinstance(diagnosis, dict) and _text(diagnosis.get("text")):
        points.append(
            {
                "key": "diagnosis",
                "kind": "diagnosis",
                "title": "Why this keeps happening",
                "text": _text(diagnosis.get("text")),
            }
        )
    details = overview.get("improvement_details")
    for index, detail in enumerate(details if isinstance(details, list) else []):
        if not isinstance(detail, dict) or not _text(detail.get("replacement_behavior")):
            continue
        finding = detail.get("finding_index")
        title = ""
        if isinstance(finding, int) and 0 <= finding < len(improvements):
            item = improvements[finding]
            title = _text(item.get("title")) if isinstance(item, dict) else ""
        points.append(
            {
                "key": f"better:{index}",
                "kind": "better",
                "title": title or "What better looks like",
                "text": _text(detail.get("replacement_behavior")),
            }
        )
    practice = overview.get("practice")
    if isinstance(practice, dict) and _text(practice.get("instructions")):
        condition = _text(practice.get("success_condition"))
        points.append(
            {
                "key": "practice",
                "kind": "practice",
                "title": "Practice",
                "text": _text(practice.get("instructions"))
                + (f" · Done when: {condition}" if condition else ""),
            }
        )
    return points
