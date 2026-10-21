"""One pass's pointer scores, calibrated to today's pointer review and labelled beta (B3).

Owner, 21 Oct 2026: "beta-labelled calibrated scores". On the 16 real calls of the dev
trial (21 Oct 2026; 395 pointers scored by both), the one-pass read scored every pointer
4.6 points higher than today's pointer review on average (sd 8.8) and the overall score
4.3 higher. Calibration v1 subtracts each pointer's own measured lean, shrunk toward the
global mean (prior weight of 8 pairs, so a pointer seen rarely moves little).

Checked leave-one-call-out on the same calls: the overall lean goes from +4.3 to -0.5;
the per-call disagreement stays (overall mean absolute difference 5.7 -> 5.5, per pointer
7.3 -> 7.1). It removes the bias, not the noise between two AI reads, so the scores are
shown as a beta: an AI draft, never an official score (AC-SVAL gates).

Pointer statuses, evidence and words are unchanged; only scores move, and the overall is
the mean of the calibrated scores, as the review computes it. Versioned: the saved review
names its calibration, so a later version never rewrites an earlier one.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Final

VERSION: Final = "one-pass-pointer-calibration/1"
LABEL: Final = "beta"
GLOBAL_OFFSET: Final = 4.64
# Per pointer: the measured lean, shrunk toward GLOBAL_OFFSET (fitted 21 Oct 2026).
OFFSETS: Final[dict[str, float]] = {
    "active_listening": 4.2,
    "building_rapport": 4.9,
    "business_impact": 7.0,
    "call_control": 5.5,
    "call_opening_first_impression": 5.6,
    "checking_concerns": 6.3,
    "closing_attitude": 6.8,
    "creating_value": 4.3,
    "current_solution": 3.0,
    "decision_process": 7.1,
    "discussing_pricing": 2.6,
    "enough_questions": 4.4,
    "handling_competition": 5.2,
    "handling_objections": 3.3,
    "handling_silence": 4.6,
    "needs_challenges": 3.8,
    "next_steps": 7.1,
    "open_ended_questions": 4.5,
    "overall_communication": 4.6,
    "presenting_solution": 4.0,
    "professionalism": 4.7,
    "prospect_role": 1.4,
    "purpose_agenda_setting": 5.3,
    "question_talk_ratio": 5.3,
    "solution_value": 4.5,
    "stakeholders": 2.2,
    "tone_energy": 2.8,
}


def calibrate(review: Mapping[str, Any]) -> dict[str, Any]:
    """A parsed pointer review (``pointer_review.parse_review``) with calibrated scores and
    its calibration named; a review already calibrated is returned as it is."""
    from ac_platform.conversation_intelligence.pointer_review import BAND_LABEL, band

    result = copy.deepcopy(dict(review))
    if isinstance(result.get("calibration"), Mapping):
        return result
    scores: list[int] = []
    for pointer in result.get("pointers") or []:
        score = pointer.get("score")
        if isinstance(score, bool) or not isinstance(score, int | float):
            continue
        offset = OFFSETS.get(str(pointer.get("id")), GLOBAL_OFFSET)
        pointer["score"] = max(0, min(100, round(score - offset)))
        scores.append(pointer["score"])
    overall = dict(result.get("overall") or {})
    if overall.get("score") is not None:
        value = round(sum(scores) / len(scores)) if scores else None
        overall["score"] = value
        overall["label"] = BAND_LABEL[band(value)] if value is not None else None
        overall["scored_pointers"] = len(scores)
        result["overall"] = overall
    result["calibration"] = {"version": VERSION, "label": LABEL, "basis": "one_pass_c4"}
    return result
