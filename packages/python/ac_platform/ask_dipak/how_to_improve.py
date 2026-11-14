"""Report -> "How to improve" -> Ask Dipak (13 Nov 2026 meeting, section 5, points 1-2; Pulse
task C2). A call's report names what to improve; this table sends each weakness to Dipak's own
questions, so a tap opens his answer. It is a plain table, deterministic and reviewable by
Dipak (docs/product/ASK-DIPAK-API.md shows it); no AI picks the questions (decision D10).

Keys are the report's own: the eight skill dimensions (``dimensions[].dimension_id``; a skill to
improve is one whose ``call_state`` is ``needs_attention``) and the objection kinds
(``call_map.objections[].kind``). Each list is in the order to offer, complete lessons first.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ac_platform.ask_dipak import catalogue

#: Report skill (dimension_id) -> Dipak's questions to read, best first.
SKILLS: dict[str, tuple[str, ...]] = {
    # Trust and rapport.
    "human_connection_trust": ("RP01", "RP02", "RP04"),
    # Listening and understanding the customer.
    "discovery_deep_understanding": ("PG01", "LI01", "AQ03"),
    # Who decides, readiness, agreement.
    "qualification": ("DM01", "DM02", "DP02"),
    # The problem's real cost and the desire to fix it.
    "problem_impact_desire": ("IM01", "IM02", "PG03"),
    # Presenting the right value.
    "solution_relevance_presentation": ("EX02", "MS04", "MS02"),
    # Objections, handled with certainty.
    "certainty_objection_intelligence": ("PB03", "OB03", "OB02"),
    # Closing and the next step.
    "closing_decision_management": ("NX02", "CL01", "CL04"),
    # How it was said: pace, pauses, tone.
    "communication_tonality": ("TP03", "TP02", "TP05"),
}

#: Report objection kind -> Dipak's questions for that objection.
OBJECTIONS: dict[str, tuple[str, ...]] = {
    "price_concern": ("PB03", "PB04", "PB05"),
    "affordability_gap": ("PB04", "PB03", "NEW-033"),
    "time_constraint": ("NEW-031", "OB03"),
    "stall": ("OB03", "CL04", "NEW-029"),
    "competitor_or_status_quo": ("OB02", "OB04", "NEW-032"),
    "decision_maker_absent": ("DM02", "DM05", "DM03"),
    "trust_concern": ("NEW-005", "RP02", "NEW-007"),
    "other": ("OB02", "OB01"),
}

#: When the report names nothing the table knows: using the report for the next calls.
FALLBACK: tuple[str, ...] = ("NEW-035", "CO02")

#: The meeting's "three or four questions for the most critical gaps".
LIMIT = 4


def questions_for(
    skills: Iterable[str] = (), objections: Iterable[str] = (), limit: int = LIMIT
) -> list[dict[str, Any]]:
    """Dipak's questions for these weaknesses: one per weakness first (in the order given),
    then the next of each, never the same question twice; the fallback when none is known."""
    lists = [SKILLS[key] for key in skills if key in SKILLS]
    lists += [OBJECTIONS[key] for key in objections if key in OBJECTIONS]
    if not lists:
        lists = [FALLBACK]
    picked: list[str] = []
    for depth in range(max(len(items) for items in lists)):
        for items in lists:
            if depth < len(items) and items[depth] not in picked:
                picked.append(items[depth])
    out = []
    for code in picked[: max(1, limit)]:
        found = catalogue.question(code)
        if found is not None:
            out.append(found.public())
    return out


def weaknesses(report: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """What a report says to improve: skills whose call_state is needs_attention (in the
    report's order) and the kinds of objections raised on the call."""
    skills = [
        str(item.get("dimension_id"))
        for item in report.get("dimensions") or []
        if isinstance(item, Mapping) and item.get("call_state") == "needs_attention"
    ]
    call_map = report.get("call_map") if isinstance(report.get("call_map"), Mapping) else {}
    objections = list(
        dict.fromkeys(
            str(item.get("kind"))
            for item in (call_map or {}).get("objections") or []
            if isinstance(item, Mapping) and item.get("kind")
        )
    )
    return skills, objections


def for_report(report: Mapping[str, Any], limit: int = LIMIT) -> dict[str, Any]:
    skills, objections = weaknesses(report)
    return {
        "skills": skills,
        "objections": objections,
        "questions": questions_for(skills, objections, limit),
    }


def table() -> dict[str, Any]:
    """The whole table, for Dipak's review and the docs."""
    return {
        "skills": {key: list(value) for key, value in SKILLS.items()},
        "objections": {key: list(value) for key, value in OBJECTIONS.items()},
        "fallback": list(FALLBACK),
    }


__all__ = [
    "FALLBACK",
    "LIMIT",
    "OBJECTIONS",
    "SKILLS",
    "for_report",
    "questions_for",
    "table",
    "weaknesses",
]
