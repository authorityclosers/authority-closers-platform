"""Prompt, response schema and strict validation for call object extraction.

Pure: no I/O, no provider. The model names segment ids; every quote is copied
from the saved transcript, never from the model. A fact the call does not
support with a segment is dropped, except the AI reads, which are labelled so.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ac_platform.call_data import taxonomy
from ac_platform.call_data.taxonomy import ObjectType
from ac_platform.call_data.values import CallValueError, display, validate_value

MAX_EVIDENCE = 3
MAX_QUOTE = 600
MAX_FACTS = 60
NO_EVIDENCE_CEILING = 0.6


@dataclass(frozen=True, slots=True)
class Segment:
    id: str
    text: str
    start_ms: int
    end_ms: int
    speaker: str


@dataclass(slots=True)
class Draft:
    """A validated object, not yet stored."""

    type_key: str
    category: str
    value: dict[str, Any]
    display: str
    confidence: float
    basis: str  # observed | inferred
    mentions: int
    evidence: list[dict[str, Any]] = field(default_factory=list)


def segments_from_transcript(payload: Mapping[str, Any]) -> list[Segment]:
    """The C2 checkpoint's segments, in order; malformed ones are skipped."""
    result = []
    for item in payload.get("segments") or []:
        if not isinstance(item, Mapping):
            continue
        sid, text = item.get("id"), item.get("text")
        start, end = item.get("start_ms"), item.get("end_ms")
        if (
            isinstance(sid, str)
            and isinstance(text, str)
            and text.strip()
            and type(start) is int
            and type(end) is int
            and 0 <= start < end
        ):
            speaker = item.get("speaker_id")
            result.append(
                Segment(sid, text, start, end, speaker if isinstance(speaker, str) else "unknown")
            )
    return result


def _type_lines(types: Sequence[ObjectType]) -> str:
    lines = []
    for item in types:
        extra = f" One of: {', '.join(item.enum_values)}." if item.enum_values else ""
        many = "many" if item.many else "one"
        lines.append(f"- {item.key} ({item.kind}, {many}): {item.hint}{extra}")
    return "\n".join(lines)


VALUE_SHAPES = """Value shapes by kind:
- text: {"text": "..."}
- numeric: {"text": "as said, e.g. Rs 4-5 lakh a month",
  "interval_shape": "point|range|lower_bound|upper_bound",
  "approximation": "exact|approximate", "lower": "400000", "upper": "500000",
  "lower_inclusive": true, "upper_inclusive": true,
  "currency_code": "INR" or null, "unit": "people" or null,
  "period": "month|year|one_time" or null}
  A point has lower = upper, both inclusive. A range has lower < upper.
  Write lakh and crore as full numbers (1 lakh = 100000).
  Never both currency_code and unit. Leave out keys that do not apply.
- when: {"text": "as said, e.g. Friday 4 PM", "date": "YYYY-MM-DD" or null,
  "time": "HH:MM" (24 h) or null, "purpose": "what it is for" or null}
  Resolve relative days against the call date. Time only with a date.
- enum: {"enum": "one of the listed values"}
- person: {"name": ... or null, "role": ... or null,
  "relation": "partner, spouse, boss..." or null}
- commitment: {"text": "what was promised", "due": a when value or null}
- objection: {"text": "...",
  "kind": "price|timing|authority|need|trust|competition|other",
  "resolved": true/false}
- question: {"text": "...", "answered": true/false}"""


ROLES = ("salesperson", "prospect", "other")


def build_prompt(
    segments: Sequence[Segment],
    *,
    types: Sequence[ObjectType],
    call_date: str,
) -> tuple[str, str]:
    """The extraction instruction (system) and the numbered transcript (user)."""
    system = f"""You extract facts from one sales phone call for a CRM.
The call may be in Hindi, Marathi, English or a mix. Write every value in plain
English, short, as a salesperson would note it. Keep names as said.

Rules:
- Only facts the call states. Each fact cites 1 to 5 segment ids where it is said.
- Never invent a name, company, number or date. If unsure, leave the fact out.
- Never extract phone numbers, email addresses or other contact details.
- confidence: 0 to 1, how sure you are the value is right and is what was meant.
- basis: "observed" when a segment says it; "inferred" only for the AI-read types.
- For "one" types give at most one fact; for "many" types one fact per distinct item.
- The prospect is the customer; the salesperson is the seller. Also say which
  speaker id is the salesperson and which is the prospect.

Call date: {call_date}.

Types:
{_type_lines(types)}

{VALUE_SHAPES}
"""
    lines = (f"[{s.id}] {s.speaker} {s.start_ms // 1000}s: {s.text}" for s in segments)
    user = "Transcript:\n" + "\n".join(lines)
    return system, user


def response_schema(types: Sequence[ObjectType]) -> dict[str, Any]:
    """A loose JSON schema for the provider's structured output; validation is ours."""
    return {
        "type": "object",
        "properties": {
            "speakers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker_id": {"type": "string"},
                        "role": {"type": "string", "enum": list(ROLES)},
                    },
                    "required": ["speaker_id", "role"],
                },
            },
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": [t.key for t in types]},
                        "value": {"type": "object"},
                        "confidence": {"type": "number"},
                        "basis": {"type": "string", "enum": ["observed", "inferred"]},
                        "segments": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "value", "confidence", "basis", "segments"],
                },
            },
        },
        "required": ["speakers", "facts"],
    }


def parse_roles(raw: object, segments: Sequence[Segment]) -> dict[str, str]:
    """Speaker id to role, only for speakers present in the transcript."""
    present = {s.speaker for s in segments}
    speakers = raw.get("speakers") if isinstance(raw, Mapping) else None
    roles: dict[str, str] = {}
    for item in speakers if isinstance(speakers, list) else []:
        if not isinstance(item, Mapping):
            continue
        sid, role = item.get("speaker_id"), item.get("role")
        if isinstance(sid, str) and sid in present and role in ROLES:
            roles[sid] = str(role)
    return roles


def _evidence(ids: Iterable[str], by_id: Mapping[str, Segment]) -> list[Segment]:
    seen: list[Segment] = []
    for sid in ids:
        segment = by_id.get(sid)
        if segment is not None and segment not in seen:
            seen.append(segment)
    return seen


def validate_response(
    raw: object,
    segments: Sequence[Segment],
    *,
    types: Sequence[ObjectType],
    withheld: frozenset[str] = frozenset(),
) -> tuple[list[Draft], dict[str, int]]:
    """Validated drafts plus counts of what was dropped and why (no content)."""
    dropped: dict[str, int] = {}

    def drop(code: str) -> None:
        dropped[code] = dropped.get(code, 0) + 1

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return [], {"not_json": 1}
    facts = raw.get("facts") if isinstance(raw, Mapping) else None
    if not isinstance(facts, list):
        return [], {"no_facts": 1}
    allowed = {t.key: t for t in types}
    usable = {s.id: s for s in segments if s.id not in withheld}
    drafts: list[Draft] = []
    for item in facts[:MAX_FACTS]:
        if not isinstance(item, Mapping):
            drop("shape")
            continue
        kind_type = allowed.get(str(item.get("type")))
        if kind_type is None:
            drop("unknown_type")
            continue
        try:
            value = validate_value(kind_type, item.get("value"))
        except CallValueError as error:
            drop(error.code)
            continue
        ids = item.get("segments")
        cited = _evidence(ids if isinstance(ids, list) else [], usable)
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            drop("confidence")
            continue
        confidence = max(0.0, min(1.0, float(confidence)))
        if cited:
            basis = "observed" if item.get("basis") != "inferred" else "inferred"
        elif kind_type.ai_read or kind_type.category == "outcome":
            basis = "inferred"
            confidence = min(confidence, NO_EVIDENCE_CEILING)
        else:
            drop("no_evidence")
            continue
        drafts.append(
            Draft(
                type_key=kind_type.key,
                category=kind_type.category,
                value=value,
                display=display(kind_type, value),
                confidence=round(confidence, 3),
                basis=basis,
                mentions=len(cited),
                evidence=[
                    {
                        "segment_id": s.id,
                        "quote": s.text[:MAX_QUOTE],
                        "start_ms": s.start_ms,
                        "end_ms": s.end_ms,
                        "speaker": s.speaker,
                    }
                    for s in cited[:MAX_EVIDENCE]
                ],
            )
        )
    return _dedupe(drafts, drop), dropped


def _dedupe(drafts: list[Draft], drop: Any) -> list[Draft]:
    best: dict[tuple[str, str], Draft] = {}
    for draft in drafts:
        kind_type = taxonomy.TYPES[draft.type_key]
        key = (
            draft.type_key,
            "" if not kind_type.many else " ".join(draft.display.casefold().split()),
        )
        held = best.get(key)
        if held is None:
            best[key] = draft
            continue
        drop("duplicate")
        if draft.confidence > held.confidence:
            draft.mentions = max(draft.mentions, held.mentions)
            best[key] = draft
        else:
            held.mentions = max(draft.mentions, held.mentions)
    return sorted(best.values(), key=lambda d: (taxonomy.TYPES[d.type_key].priority, d.display))
