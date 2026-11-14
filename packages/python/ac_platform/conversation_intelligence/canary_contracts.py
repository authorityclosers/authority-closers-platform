"""The staging canary's offline C4/C5 contract check (orchestrator, 13 Nov 2026).

Staging's canary stops after the transcript (``call_ai.policy.TRANSCRIPT_ONLY_CANARIES``),
so no paid facts (C4) or coaching (C5) call proves those stages there. Instead, this
release's own validators read one fixed, fictional C4 answer and one C5 answer built
from the live report profile, exactly as they read a provider's. A release that can no
longer accept a well-formed answer fails its staging canary without spending anything.
Production's canary still runs every stage for real.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V4,
    COACHING_PROMPT_V5,
    CoachingPromptRevision,
    load_report_profile,
    parse_fact_packet,
    parse_report_draft,
    plan_transcript_chunks,
)

# The C5 answer shapes this fixture stands in for. A newer revision needs its own
# fixture before staging switches to it; until then its canary fails closed.
FIXTURE_REVISIONS: frozenset[str] = frozenset({COACHING_PROMPT_V4, COACHING_PROMPT_V5})
UNAVAILABLE = "c5_fixture_unavailable"

# Fictional words only: no real person, customer or call.
TRANSCRIPT: dict[str, Any] = {
    "source_sha256": "c" * 64,
    "revision": "canary-contract-fixture-v1",
    "timebase_id": "1ms",
    "duration_ms": 9_000,
    "segments": [
        {
            "id": "s1",
            "speaker_id": "speaker_0",
            "start_ms": 0,
            "end_ms": 2_800,
            "text": "Thanks for taking the call. Is now still a good time to talk?",
        },
        {
            "id": "s2",
            "speaker_id": "speaker_1",
            "start_ms": 3_000,
            "end_ms": 5_900,
            "text": "Yes. We lose track of call-backs, and the price is above our budget.",
        },
        {
            "id": "s3",
            "speaker_id": "speaker_0",
            "start_ms": 6_100,
            "end_ms": 8_900,
            "text": "Understood. Shall we review a sample with your colleague next Tuesday?",
        },
    ],
}

C4_ANSWER: dict[str, Any] = {
    "overview": "A fictional call about call-backs, a budget concern and a sample review.",
    "observations": [],
    "uncertainties": ["Whether the budget can change."],
}


def coaching_answer(profile: Mapping[str, Any]) -> dict[str, Any]:
    """One well-formed C5 answer for every dimension of the live report profile."""
    finding = {
        "title": "Explore the budget concern",
        "explanation": (
            "The buyer said the price is above their budget. Ask what decides the "
            "budget before offering the sample."
        ),
        "evidence": [{"segment_id": "s2"}],
    }
    dimensions = [
        {
            "dimension_id": dimension["id"],
            "status": "observed" if index == 0 else "insufficient_evidence",
            "observation": (
                "The buyer named a budget gap; explore it before the next step."
                if index == 0
                else "The supplied words do not establish this dimension."
            ),
            "evidence": [{"segment_id": "s2"}] if index == 0 else [],
        }
        for index, dimension in enumerate(profile["dimensions"])
    ]
    return {
        "summary": "The buyer raised call-backs and a budget gap; a sample review was offered.",
        "strengths": [
            {
                "title": "You checked the timing",
                "explanation": "You asked whether the buyer could talk before you went on.",
                "evidence": [{"segment_id": "s1"}],
            }
        ],
        "missed_opportunities": [],
        "improvements": [finding],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Qualitative draft for human review.",
        "review_status": "draft_not_dipak_adjudicated",
        "dimensions": dimensions,
    }


def check_stage_contracts(coaching_prompt_revision: str | None) -> dict[str, str]:
    """Read the fixture through this release's C4 and C5 validators; raise on a miss."""
    revision = coaching_prompt_revision or COACHING_PROMPT_V4
    for chunk in plan_transcript_chunks(TRANSCRIPT):
        parse_fact_packet(C4_ANSWER, TRANSCRIPT, chunk=chunk)
    if revision not in FIXTURE_REVISIONS:
        raise ValueError(UNAVAILABLE)
    profile = load_report_profile()
    parse_report_draft(
        coaching_answer(profile),
        TRANSCRIPT,
        profile=profile,
        coaching_prompt_revision=cast(CoachingPromptRevision, revision),
    )
    return {"C4": "ok", "C5": "ok", "c5_revision": revision}
