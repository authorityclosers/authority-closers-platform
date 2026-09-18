"""Synthetic-only C5 provider stubs for the versioned qualitative overview."""

from typing import Any


def overview_for(report: dict[str, Any]) -> dict[str, Any]:
    """Minimal explicit new-format output; no assertions about real recordings."""
    improvements = report["improvements"]
    return {
        "version": "dipak-14-point-v1",
        "diagnosis": None,
        "outcome": None,
        "strength_details": [
            {"finding_index": index, "why_it_matters": "A synthetic reason to repeat this."}
            for index, _ in enumerate(report["strengths"])
        ],
        "improvement_details": [
            {
                "finding_index": index,
                "what_happened": {"text": finding["explanation"], "evidence": finding["evidence"]},
                "why_it_matters": "The stated barrier needs clarification.",
                "replacement_behavior": "Ask one question about the stated barrier.",
                "business_impact": {
                    "status": "insufficient_data",
                    "missing_inputs": ["Comparable conversion history", "Lead volume"],
                },
            }
            for index, finding in enumerate(improvements)
        ],
        "golden_moments": [],
        "missed_details": [],
        "prospect_interpretations": [],
        "rewatch": [],
        "conversation_change": None,
        "ethics_notes": [],
        "next_call_focus": {
            "improvement_index": 0,
            "behavior": "Ask before presenting.",
            "target": "Ask one follow-up question before giving an answer.",
        }
        if improvements
        else None,
        "practice": {
            "improvement_index": 0,
            "instructions": "Rehearse asking the follow-up question out loud.",
            "success_condition": "You ask one open question before explaining the offer.",
        }
        if improvements
        else None,
        "progress": None,
        "final_assessment": {
            "repeat": "Keep the supported strength.",
            "fix_first": "Clarify the stated barrier." if improvements else "Not established.",
            "next_focus": "Ask one follow-up question." if improvements else "Not established.",
            "assessment": "Synthetic qualitative draft for human review.",
        },
    }
