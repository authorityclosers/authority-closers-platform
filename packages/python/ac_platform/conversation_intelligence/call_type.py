"""Pure Python twin of Sales Xray's call-type rule (AUT-341 decision 1, AUT-629).

The call type is derived by code from structured call-map inputs, never by a
model. First match wins, in the order of ``CALL_TYPES``. The result is one
closed key, never a score. The shared vectors in
``apps/sales-xray-web/tests/fixtures/call-type-vectors.json`` pin every rule.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final, Literal, TypedDict, TypeGuard

CallType = Literal[
    "not_sales",
    "objection_negotiation",
    "prospect_story",
    "screening",
    "first_meeting",
    "pitch_demo",
    "follow_up_closing",
    "full_sales",
    "unclear",
]

CALL_TYPES: Final[tuple[CallType, ...]] = (
    "not_sales",
    "objection_negotiation",
    "prospect_story",
    "screening",
    "first_meeting",
    "pitch_demo",
    "follow_up_closing",
    "full_sales",
)


class CallTypeThresholds(TypedDict):
    prospect_share_over: float
    pitch_share_over: float
    short_call_ms: int
    little_questions_ms: int


# Proposed test settings from profiles/call_types_v1.json. The owner fixes
# them at Gate 2; they are not approved business semantics.
CALL_TYPE_THRESHOLDS: Final[CallTypeThresholds] = {
    "prospect_share_over": 0.6,
    "pitch_share_over": 0.5,
    "short_call_ms": 600000,
    "little_questions_ms": 120000,
}

_PURPOSES: Final = ("sales", "support", "onboarding", "internal", "personal")
_NOT_SALES: Final = ("support", "onboarding", "internal", "personal")
_PHASES: Final = ("opening", "discovery", "pitch", "objection", "close")
_OUTCOMES: Final = ("won", "lost", "follow_up", "disqualified", "none")
_ADVANCE_OR_STOP: Final = ("follow_up", "disqualified", "lost")


def _finite(value: object) -> TypeGuard[float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _union_ms(spans: list[tuple[float, float]]) -> float:
    total = 0.0
    reach = -math.inf
    for start_ms, end_ms in sorted(spans, key=lambda span: span[0]):
        start = max(start_ms, reach)
        if end_ms > start:
            total += end_ms - start
        reach = max(reach, end_ms)
    return total


def _stage_ms(call: Mapping[str, Any], duration: float) -> dict[str, float] | None:
    """Stage time per phase name.

    A phase ends where the next one starts, the last at the call's end;
    repeated stages add up and never overlap.
    """
    phases = call.get("phases")
    extra = call.get("objection_spans", [])
    if not isinstance(phases, list) or not phases or not isinstance(extra, list):
        return None
    if not all(isinstance(phase, Mapping) for phase in phases):
        return None
    if not all(_finite(phase.get("start_ms")) for phase in phases):
        return None

    def clip(ms: float) -> float:
        return min(max(ms, 0), duration)

    ordered = sorted(phases, key=lambda phase: phase["start_ms"])
    spans: dict[str, list[tuple[float, float]]] = {name: [] for name in _PHASES}
    for index, phase in enumerate(ordered):
        if phase.get("name") not in _PHASES:
            return None
        end = ordered[index + 1]["start_ms"] if index + 1 < len(ordered) else duration
        spans[phase["name"]].append((clip(phase["start_ms"]), clip(end)))
    for span in extra:
        if not isinstance(span, Mapping):
            return None
        start_ms, end_ms = span.get("start_ms"), span.get("end_ms")
        if not _finite(start_ms) or not _finite(end_ms) or end_ms < start_ms:
            return None
        spans["objection"].append((clip(start_ms), clip(end_ms)))
    return {name: _union_ms(spans[name]) for name in _PHASES}


def derive_call_type(call: Mapping[str, Any]) -> CallType:
    t = CALL_TYPE_THRESHOLDS
    purpose = call.get("call_purpose")
    if purpose not in _PURPOSES:
        return "unclear"
    if purpose in _NOT_SALES:
        return "not_sales"

    duration = call.get("duration_ms")
    share = call.get("prospect_talk_share")
    if not _finite(duration) or duration <= 0:
        return "unclear"
    if not _finite(share) or not 0 <= share <= 1:
        return "unclear"
    confirmed = call.get("qualification_confirmed")
    outcome = call.get("outcome_kind")
    if not isinstance(confirmed, list) or outcome not in _OUTCOMES:
        return "unclear"
    ms = _stage_ms(call, duration)
    if ms is None:
        return "unclear"

    def has(name: str) -> bool:
        return ms[name] > 0

    others = [name for name in _PHASES if name != "objection"]
    little_questions = ms["discovery"] <= t["little_questions_ms"]
    moments = call.get("price_moments")
    price_talk = isinstance(moments, int) and not isinstance(moments, bool) and moments > 0

    if has("objection") and all(ms["objection"] > ms[name] for name in others):
        return "objection_negotiation"
    if share > t["prospect_share_over"]:
        return "prospect_story"
    if (
        duration <= t["short_call_ms"]
        and len(confirmed) > 0
        and not has("pitch")
        and outcome in _ADVANCE_OR_STOP
    ):
        return "screening"
    if has("discovery") and not has("pitch") and not has("close"):
        return "first_meeting"
    if ms["pitch"] > duration * t["pitch_share_over"] and little_questions:
        return "pitch_demo"
    if little_questions and (has("close") or price_talk):
        return "follow_up_closing"
    if has("discovery") and has("pitch") and has("close"):
        return "full_sales"
    return "unclear"
