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

Evidence and words are unchanged. Scores move, and each scored pointer's status is banded
again from its calibrated score (the review's own rule: a row never contradicts its
score); not_observed, not_applicable and insufficient_evidence stay as they are. The
overall is the mean of the calibrated scores, as the review computes it. Versioned: the
saved review names its calibration, so a later version never rewrites an earlier one.

Each model has its own table: a review read by GPT-6 Luna (the one-pass C4 request on an
OpenAI route) takes Luna's (``LUNA_VERSION``), every other read Gemini's (``VERSION``).
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


# OpenAI GPT-6 Luna reads the other way (orchestrator, 21 Oct 2026: "Add a Luna-specific
# pointer calibration from the 16-call Luna trial, labelled beta"). Production's one-pass C4
# request on Luna (Flex) over the same AC trial calls' Flash-Lite transcripts: 13 calls with a
# usable review, 301 pointers scored by both; Luna scored every pointer 8.2 points lower than
# today's review on average (sd 10.0), the overall 8.5 lower. Fitted the same way (prior of 8
# pairs); leave-one-call-out the overall lean goes from -8.5 to -0.4, the overall mean
# absolute difference 8.5 -> 3.0, per pointer 10.1 -> 7.2 (Gemini v1: 7.3 -> 7.1).
LUNA_MODEL: Final = "gpt-6-luna"
LUNA_VERSION: Final = "one-pass-pointer-calibration-luna/1"
LUNA_GLOBAL_OFFSET: Final = -8.2
LUNA_OFFSETS: Final[dict[str, float]] = {
    "active_listening": -8.2,
    "building_rapport": -6.5,
    "business_impact": -6.3,
    "call_control": -11.4,
    "call_opening_first_impression": -8.4,
    "checking_concerns": -7.9,
    "closing_attitude": -3.2,
    "creating_value": -11.6,
    "current_solution": -11.5,
    "decision_process": -6.5,
    "discussing_pricing": -7.3,
    "enough_questions": -12.5,
    "handling_competition": -8.4,
    "handling_objections": -14.9,
    "handling_silence": -8.2,  # never scored by both: the global lean
    "needs_challenges": -5.4,
    "next_steps": 0.3,
    "open_ended_questions": -6.4,
    "overall_communication": -10.4,
    "presenting_solution": -6.3,
    "professionalism": -5.9,
    "prospect_role": -13.4,
    "purpose_agenda_setting": -8.0,
    "question_talk_ratio": -9.5,
    "solution_value": -10.6,
    "stakeholders": -7.5,
    "tone_energy": -6.5,
}


def _table(model: str | None) -> tuple[str, float, Mapping[str, float], str]:
    """The calibration for the model that answered the one-pass C4 request: Luna's own
    (any ``gpt-6-luna`` route), otherwise Gemini's (v1)."""
    if model is not None and model.split(":", 1)[0] == LUNA_MODEL:
        return LUNA_VERSION, LUNA_GLOBAL_OFFSET, LUNA_OFFSETS, "one_pass_c4_luna"
    return VERSION, GLOBAL_OFFSET, OFFSETS, "one_pass_c4"


def calibrate(review: Mapping[str, Any], *, model: str | None = None) -> dict[str, Any]:
    """A parsed pointer review (``pointer_review.parse_review``) with calibrated scores and
    its calibration named, by the model that answered (``model``; Gemini's when not given);
    a review already calibrated is returned as it is."""
    from ac_platform.conversation_intelligence.pointer_review import BAND_LABEL, SCORED, band

    result = copy.deepcopy(dict(review))
    if isinstance(result.get("calibration"), Mapping):
        return result
    version, global_offset, offsets, basis = _table(model)
    scores: list[int] = []
    for pointer in result.get("pointers") or []:
        score = pointer.get("score")
        if isinstance(score, bool) or not isinstance(score, int | float):
            continue
        offset = offsets.get(str(pointer.get("id")), global_offset)
        pointer["score"] = max(0, min(100, round(score - offset)))
        scores.append(pointer["score"])
        if pointer.get("status") in SCORED:
            # The Report rates a row by its status (merge_into_structure): band it again.
            pointer["status"] = band(pointer["score"])
    overall = dict(result.get("overall") or {})
    if overall.get("score") is not None:
        value = round(sum(scores) / len(scores)) if scores else None
        overall["score"] = value
        overall["label"] = BAND_LABEL[band(value)] if value is not None else None
        overall["scored_pointers"] = len(scores)
        result["overall"] = overall
    result["calibration"] = {"version": version, "label": LABEL, "basis": basis}
    return result
