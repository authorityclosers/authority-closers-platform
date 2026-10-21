"""Accuracy Brain 4.0 review, beta (orchestrator, 21 Oct 2026).

Brain 4.0 is the coaching lead's 18-dimension rubric (``Accuracy Brain 4.0.txt``, 25,465
lines, digest ``SOURCE_SHA256``). The prompt carries a compact digest of it
(``profiles/brain4_compact_v1.txt``), written by the 20 Oct cost research from the full
text and pinned here by its digest. The digest still needs the coaching lead's sign-off
before any of its scores can be official (ADR 0036 D5).

One model answer scores every dimension 1-5, or "-" when it does not apply to this call
or cannot be observed. The answer is its own part of the one-pass review request; this
module builds the part's instructions and schema and checks the answer. Like the pointer
review, the model cites transcript segment ids only; quotes and times are copied here
from the saved transcript.

Nothing here is official (AGENTS.md: no official autonomous scoring before the AC-SVAL
gates). Every result says ``status: beta``. Category roll-ups and calibration are computed
when the review is read, for display only; the saved answer never changes, so a later
roll-up or calibration choice applies to every call without rewriting it.

Pure: no I/O, no provider.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Final

from ac_platform.conversation_intelligence.pointer_review import _refs, _words

VERSION: Final = "brain4-review/1"
RUBRIC_REVISION: Final = "brain4-compact/1"
STATUS: Final = "beta"
# Accuracy Brain 4.0.txt as the coaching lead shared it (Drive, read 20 Oct 2026).
SOURCE_SHA256: Final = "0d122e489a5e056038ce98818703c719a9b22b7ab3a9c6ae60717ec5a4ed3d0c"
RUBRIC_FILE: Final = Path(__file__).with_name("profiles") / "brain4_compact_v1.txt"
RUBRIC_SHA256: Final = "e8938fdfa5f92404fe2f720ee6909d87eb87960a2ae976241e354ebba327e41c"

# The rubric's own categories and dimension names (its table of contents).
CATEGORIES: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("how_you_talk", "How You Talk", ("D01", "D02", "D03", "D04", "D05", "D06", "D07")),
    (
        "understanding_the_buyer",
        "How Well You Understand the Buyer",
        ("D08", "D09", "D10", "D11", "D12"),
    ),
    (
        "moving_the_sale_forward",
        "How Well You Move the Sale Forward",
        ("D13", "D14", "D15", "D16", "D17", "D18"),
    ),
)
LABELS: Final[dict[str, str]] = {
    "D01": "Starting the Call",
    "D02": "Setting the Plan",
    "D03": "Tone, Pace & Pauses",
    "D04": "Listening Well",
    "D05": "Asking the Right Questions",
    "D06": "Building Connection",
    "D07": "Being Professional",
    "D08": "Finding the Decision-Makers",
    "D09": "Understanding Problems & Goals",
    "D10": "Understanding What They're Doing Now",
    "D11": "Understanding the Real Impact",
    "D12": "Understanding How They Will Decide",
    "D13": "Matching the Right Solution",
    "D14": "Explaining the Solution Clearly",
    "D15": "Talking About Price & Budget",
    "D16": "Handling Objections",
    "D17": "Asking for the Decision",
    "D18": "Setting Clear Next Steps",
}
DIMENSION_IDS: Final[tuple[str, ...]] = tuple(LABELS)
CATEGORY_OF: Final[dict[str, str]] = {
    dimension: key for key, _, dimensions in CATEGORIES for dimension in dimensions
}
if tuple(CATEGORY_OF) != DIMENSION_IDS:
    raise RuntimeError("brain4 catalogue mismatch")

APPLICABILITY: Final = ("applicable", "not_applicable", "not_enough_evidence")
CONFIDENCE: Final = ("high", "medium", "low")
ETHICS: Final = ("PASS", "WARN", "FAIL")
# "Identify the call type first ... what is needed depends on it" (rubric, scoring rules).
CALL_TYPES: Final = (
    "inbound",
    "cold",
    "scheduled",
    "follow_up",
    "referral",
    "existing_client",
    "re_engagement",
    "operational",
    "unknown",
)

# Which of the Report's 27 pointers each dimension judges, for the gold evaluation and the
# Report's beta view. "primary": the pointer asks the dimension's question; "related": it
# overlaps part of it (counted apart, never in a dimension's agreement). Two pointers have
# no dimension: question_talk_ratio (the rubric never scores counts or talk ratio) and
# call_control. A proposal for the coaching lead's review, not his mapping.
POINTER_MAP: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "D01": (("call_opening_first_impression", "primary"),),
    "D02": (("purpose_agenda_setting", "primary"),),
    "D03": (
        ("tone_energy", "primary"),
        ("handling_silence", "primary"),
        ("overall_communication", "related"),
    ),
    "D04": (("active_listening", "primary"),),
    "D05": (("open_ended_questions", "primary"), ("enough_questions", "primary")),
    "D06": (("building_rapport", "primary"),),
    "D07": (("professionalism", "primary"),),
    "D08": (("prospect_role", "primary"), ("stakeholders", "primary")),
    "D09": (("needs_challenges", "primary"),),
    "D10": (("current_solution", "primary"), ("handling_competition", "related")),
    "D11": (("business_impact", "primary"), ("creating_value", "related")),
    "D12": (("decision_process", "primary"),),
    "D13": (("solution_value", "primary"), ("creating_value", "related")),
    "D14": (("presenting_solution", "primary"), ("overall_communication", "related")),
    "D15": (("discussing_pricing", "primary"),),
    "D16": (
        ("handling_objections", "primary"),
        ("checking_concerns", "related"),
        ("handling_competition", "related"),
    ),
    "D17": (("closing_attitude", "primary"),),
    "D18": (("next_steps", "primary"),),
}
UNMAPPED_POINTERS: Final = ("call_control", "question_talk_ratio")

# A dimension's rating on the pointer review's four bands, for comparing with the gold
# set (which judged pointer bands). 4 is "worked, nothing went wrong" (rubric), so good.
RATING_BAND: Final[dict[int, str]] = {
    5: "excellent",
    4: "good",
    3: "average",
    2: "needs_improvement",
    1: "needs_improvement",
}

ROLLUPS: Final = ("category_mean", "dimension_mean", "category_equal", "profile_only")
# The source defines no weights and no aggregation (digests A 0.1 and B 9). Until the
# coaching lead chooses, the app shows each category's plain mean of its rated dimensions
# and no overall number; the other methods are offered for that decision.
DEFAULT_ROLLUP: Final = "category_mean"
MIN_RATED_PER_CATEGORY: Final = 2

_LIMITS: Final = {"observed": 360, "coaching": 220}


class Brain4Error(ValueError):
    """Stable code only; never carries transcript or provider text."""


@functools.cache
def rubric() -> str:
    """The compact rubric, refused when its file no longer matches the pinned digest."""
    data = RUBRIC_FILE.read_bytes()
    if hashlib.sha256(data).hexdigest() != RUBRIC_SHA256:
        raise Brain4Error("brain4_rubric_changed")
    return data.decode("utf-8")


@functools.cache
def guide() -> tuple[dict[str, Any], ...]:
    """Each dimension in the rubric's own words, for a reviewer rating it blind: what to
    look at (``about``) and what each rating means (``scale``), unedited from the
    compact rubric; never Brain 4.0's answer."""
    lines = [line.strip() for line in rubric().splitlines()]
    names = {key: name for key, name, _ in CATEGORIES}
    items = []
    for number, dimension in enumerate(DIMENSION_IDS, 1):
        at = next((i for i, line in enumerate(lines) if line.startswith(f"{dimension} ")), None)
        about, scale = "", None
        if at is not None:
            about = lines[at][len(dimension) + 1 :]
            if about.startswith(LABELS[dimension]):
                about = about[len(LABELS[dimension]) :]
            about = about.lstrip(" .+")
            scale = next((line for line in lines[at + 1 : at + 4] if line.startswith("5 ")), None)
        items.append(
            {
                "id": dimension,
                "number": number,
                "label": LABELS[dimension],
                "category": CATEGORY_OF[dimension],
                "category_label": names[CATEGORY_OF[dimension]],
                "about": about,
                "scale": scale,
            }
        )
    return tuple(items)


def part_instructions() -> str:
    """The Brain 4.0 part of a review request (one-pass ``PART brain4``)."""
    return f"""{VERSION} ({RUBRIC_REVISION}, beta).
Score the same call on Authority Closers' Brain 4.0 rubric below: all 18 dimensions,
D01 to D18, each judged on its own effect.
Write to the salesperson as "you" and call the other person "the prospect", in plain,
everyday English. No speaker labels, no names, numbers or facts the call does not give.

Return call_type (inbound, cold, scheduled, follow_up, referral, existing_client,
re_engagement, operational or unknown) and, for every dimension, exactly one entry:
- applicability: applicable when the call shows enough to judge; not_applicable when the
  behaviour is not reasonably required for this type or stage of call; not_enough_evidence
  when it could not be observed (recording starts late or ends early, no opportunity).
- rating: a whole number 1-5 when applicable, null otherwise. 5 needs positive evidence
  that the skill helped the call; "nothing went wrong" is 4; 1 only for clearly observed
  damaging behaviour. Missing evidence is never a low rating.
- confidence: high, medium or low. It never changes the rating.
- evidence: up to 2 segment ids, like "s12", that show it ([] when none).
- observed: one or two sentences on what you did in this call; when not rated, one short
  sentence on why.
- coaching: one specific cue for your next call ("On your next relevant call, ..."), or
  null when not rated or nothing should change.
- ethics_gate: for D07 only, PASS, WARN or FAIL (FAIL goes with rating 1); null for the
  others and when D07 is not rated.
D03 needs audio: from the transcript alone, use not_enough_evidence unless the words
themselves show clear repeated delivery problems, and then rate with low confidence.

{rubric()}"""


def response_schema() -> dict[str, Any]:
    """The part's strict schema (Gemini and OpenAI structured output alike)."""
    text_or_null = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    entry = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(DIMENSION_IDS)},
            "applicability": {"type": "string", "enum": list(APPLICABILITY)},
            "rating": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "confidence": {"type": "string", "enum": list(CONFIDENCE)},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "observed": {"type": "string"},
            "coaching": text_or_null,
            "ethics_gate": {"anyOf": [{"type": "string", "enum": list(ETHICS)}, {"type": "null"}]},
        },
        "required": [
            "id",
            "applicability",
            "rating",
            "confidence",
            "evidence",
            "observed",
            "coaching",
            "ethics_gate",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "call_type": {"type": "string", "enum": list(CALL_TYPES)},
            "dimensions": {"type": "array", "items": entry},
        },
        "required": ["call_type", "dimensions"],
    }


def parse(raw: Any, segments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Check one model answer against the saved transcript and the rubric's hard rules.

    The rules applied here are the rubric's own, each recorded on the dimension it moved:
    a 5 without evidence becomes 4 (``five_needs_evidence``); a 1 without evidence is
    not enough evidence (``one_needs_evidence``); a delivery rating above 3 from the
    transcript alone is not enough evidence (``delivery_needs_audio``); and the ethics
    gate and D07's rating agree (FAIL with 1, ``ethics_fail_is_one``).
    """
    if not isinstance(raw, Mapping):
        raise Brain4Error("brain4_missing")
    entries = raw.get("dimensions")
    if not isinstance(entries, list):
        raise Brain4Error("brain4_dimensions_missing")
    seen: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("id") not in LABELS:
            continue
        if entry["id"] in seen:
            raise Brain4Error("brain4_duplicate_dimension")
        seen[entry["id"]] = entry
    if len(seen) != len(DIMENSION_IDS):
        raise Brain4Error("brain4_dimensions_incomplete")
    by_id = {str(segment["id"]): dict(segment) for segment in segments}
    dimensions: list[dict[str, Any]] = []
    for number, dimension in enumerate(DIMENSION_IDS, 1):
        entry = seen[dimension]
        applicability = entry.get("applicability")
        if applicability not in APPLICABILITY:
            raise Brain4Error("brain4_applicability_invalid")
        rating = entry.get("rating")
        evidence = _refs(entry.get("evidence"), by_id)
        adjustments: list[str] = []
        if applicability == "applicable":
            if type(rating) is not int or not 1 <= rating <= 5:
                raise Brain4Error("brain4_rating_invalid")
        else:
            rating = None
        stated = entry.get("ethics_gate") if dimension == "D07" else None
        if stated == "FAIL" and rating is not None and rating != 1:
            rating = 1
            adjustments.append("ethics_fail_is_one")
        if rating == 5 and not evidence:
            rating = 4
            adjustments.append("five_needs_evidence")
        if rating == 1 and not evidence:
            rating, applicability = None, "not_enough_evidence"
            adjustments.append("one_needs_evidence")
        if dimension == "D03" and rating is not None and rating > 3:
            rating, applicability = None, "not_enough_evidence"
            adjustments.append("delivery_needs_audio")
        confidence = entry.get("confidence")
        confidence = confidence if confidence in CONFIDENCE else "low"
        if dimension == "D03" and rating is not None:
            confidence = "low"
        gate: str | None = None
        if dimension == "D07" and rating is not None:
            if rating == 1:
                gate = "FAIL"
                if stated != "FAIL":
                    adjustments.append("ethics_fail_is_one")
            else:
                gate = stated if stated in ("PASS", "WARN") else "PASS"
        rated = rating is not None
        dimensions.append(
            {
                "id": dimension,
                "number": number,
                "label": LABELS[dimension],
                "category": CATEGORY_OF[dimension],
                "applicability": applicability,
                "rating": rating,
                "confidence": confidence,
                "evidence": evidence,
                "observed": _words(entry.get("observed"), _LIMITS["observed"]),
                "coaching": _words(entry.get("coaching"), _LIMITS["coaching"]) if rated else None,
                "ethics_gate": gate,
                "adjustments": adjustments,
            }
        )
    call_type = raw.get("call_type")
    d07 = dimensions[DIMENSION_IDS.index("D07")]
    return {
        "version": VERSION,
        "rubric_revision": RUBRIC_REVISION,
        "rubric_sha256": RUBRIC_SHA256,
        "status": STATUS,
        "call_type": call_type if call_type in CALL_TYPES else "unknown",
        "ethics_gate": d07["ethics_gate"],
        "rated": sum(1 for item in dimensions if item["rating"] is not None),
        "dimensions": dimensions,
    }


def payload_sha256(review: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(review, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


# ---------- display: roll-ups and calibration (read time, never saved over the answer) ----


def rollup(review: Mapping[str, Any], method: str = DEFAULT_ROLLUP) -> dict[str, Any]:
    """Category (and, for some methods, overall) numbers from the rated dimensions.

    - ``category_mean``: each category's mean of its rated dimensions; no overall.
    - ``dimension_mean``: the same, and an overall mean of every rated dimension.
    - ``category_equal``: the same, and an overall mean of the category means.
    - ``profile_only``: no numbers beyond the dimensions themselves.

    A category with fewer than ``MIN_RATED_PER_CATEGORY`` rated dimensions shows no
    number. "-" never counts as a rating. The ethics gate is never averaged: it is
    returned beside the numbers, as the rubric requires.
    """
    if method not in ROLLUPS:
        raise Brain4Error("brain4_rollup_unknown")
    ratings: dict[str, int] = {
        str(item.get("id")): int(item["rating"])
        for item in review.get("dimensions") or []
        if isinstance(item, Mapping) and type(item.get("rating")) is int
    }
    categories: list[dict[str, Any]] = []
    for key, label, dimensions in CATEGORIES:
        rated = [ratings[d] for d in dimensions if d in ratings]
        shown = method != "profile_only" and len(rated) >= MIN_RATED_PER_CATEGORY
        categories.append(
            {
                "id": key,
                "label": label,
                "rated": len(rated),
                "of": len(dimensions),
                "score": round(mean(rated), 1) if shown else None,
            }
        )
    overall: float | None = None
    if method == "dimension_mean" and ratings:
        overall = round(mean(ratings.values()), 1)
    elif method == "category_equal":
        means = [float(c["score"]) for c in categories if c["score"] is not None]
        overall = round(mean(means), 1) if len(means) == len(CATEGORIES) else None
    return {
        "method": method,
        "status": STATUS,
        "categories": categories,
        "overall": overall,
        "ethics_gate": review.get("ethics_gate"),
    }


@dataclass(frozen=True)
class Calibration:
    """A display-only map from a dimension's rating to the rating shown, per dimension.

    Fitted from the gold set (``brain4_eval.fit_calibration``) and committed as a new
    revision; revision 0 changes nothing. Never applied to the saved answer.
    """

    revision: str = "brain4-calibration/0"
    maps: Mapping[str, Mapping[int, int]] = field(default_factory=dict)
    basis: str = "identity"


IDENTITY: Final = Calibration()


def calibrate(review: Mapping[str, Any], calibration: Calibration = IDENTITY) -> dict[str, Any]:
    """The review with each dimension's ``shown_rating`` and the calibration named."""
    result: dict[str, Any] = json.loads(json.dumps(dict(review)))
    for item in result.get("dimensions") or []:
        rating = item.get("rating")
        mapping = calibration.maps.get(str(item.get("id"))) or {}
        item["shown_rating"] = mapping.get(rating, rating) if type(rating) is int else None
    result["calibration"] = {
        "revision": calibration.revision,
        "basis": calibration.basis,
        "label": STATUS,
    }
    return result


def pointer_dimensions() -> dict[str, list[tuple[str, str]]]:
    """For each pointer, the dimensions that judge it and how (primary or related)."""
    found: dict[str, list[tuple[str, str]]] = {}
    for dimension, pointers in POINTER_MAP.items():
        for pointer, kind in pointers:
            found.setdefault(pointer, []).append((dimension, kind))
    return found


__all__ = [
    "APPLICABILITY",
    "CALL_TYPES",
    "CATEGORIES",
    "DEFAULT_ROLLUP",
    "DIMENSION_IDS",
    "IDENTITY",
    "LABELS",
    "POINTER_MAP",
    "RATING_BAND",
    "ROLLUPS",
    "RUBRIC_REVISION",
    "STATUS",
    "UNMAPPED_POINTERS",
    "VERSION",
    "Brain4Error",
    "Calibration",
    "calibrate",
    "guide",
    "parse",
    "part_instructions",
    "payload_sha256",
    "pointer_dimensions",
    "response_schema",
    "rollup",
    "rubric",
]
