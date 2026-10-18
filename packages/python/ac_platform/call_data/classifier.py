"""Segment classifier (deep pipeline): every transcript segment gets typed labels.

Semantic: what the segment is doing in the sale (intent, topics). Syntactic:
the kind of utterance (question, answer, commitment...). Plus sentiment and
tone, labelled as the AI's read. Long calls go in chunks with a few segments of
context either side. Pure: prompt, schema and strict validation only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ac_platform.call_data import taxonomy
from ac_platform.call_data.extraction import Draft, Segment
from ac_platform.call_data.values import CallValueError, display, from_model

CHUNK = 120
CONTEXT = 4
SEGMENT_TYPE = taxonomy.TYPES["conversation.segment"]


def chunks(segments: Sequence[Segment], size: int = CHUNK) -> list[tuple[int, int]]:
    """[start, end) index ranges to label, each at most ``size`` segments."""
    return [(start, min(start + size, len(segments))) for start in range(0, len(segments), size)]


def build_prompt(
    segments: Sequence[Segment], start: int, end: int, *, roles: Mapping[str, str]
) -> tuple[str, str]:
    system = f"""You label each segment of a sales phone call transcript.
The call may be in Hindi, Marathi, English or a mix; labels are always the
listed English words. Label ONLY the segments marked LABEL; the others are
context.

For each labelled segment give:
- segment_id: the id in square brackets at the start of its line (e.g. s12),
  never the segment's words.
- intent: what it does in the sale. One of: {", ".join(taxonomy.SEGMENT_INTENTS)}.
- act: the kind of utterance. One of: {", ".join(taxonomy.SEGMENT_ACTS)}.
- sentiment: {", ".join(taxonomy.SENTIMENTS)}.
- tone: {", ".join(taxonomy.TONES)}.
- topics: up to 3 short English topic words (e.g. price, team, timeline), or [].
"""
    who = ", ".join(f"{sid} = {role}" for sid, role in sorted(roles.items()))
    lines = []
    for index in range(max(0, start - CONTEXT), min(len(segments), end + CONTEXT)):
        segment = segments[index]
        mark = "LABEL" if start <= index < end else "context"
        lines.append(f"[{segment.id}] {mark} {segment.speaker}: {segment.text}")
    user = f"Speakers: {who or 'unknown'}.\n" + "\n".join(lines)
    return system, user


def response_schema() -> dict[str, Any]:
    text = {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "segment_id": text,
                        "intent": {"type": "string", "enum": list(taxonomy.SEGMENT_INTENTS)},
                        "act": {"type": "string", "enum": list(taxonomy.SEGMENT_ACTS)},
                        "sentiment": {"type": "string", "enum": list(taxonomy.SENTIMENTS)},
                        "tone": {"type": "string", "enum": list(taxonomy.TONES)},
                        "topics": {"type": "array", "items": text},
                    },
                    "required": [
                        "segment_id",
                        "intent",
                        "act",
                        "sentiment",
                        "tone",
                        "topics",
                    ],
                },
            }
        },
        "required": ["labels"],
    }


def _match(
    item: Mapping[str, Any], wanted: Mapping[str, Segment], by_text: Mapping[str, Segment]
) -> Segment | None:
    """The labelled segment: by id (brackets and stray words tolerated), else by its exact words."""
    raw = item.get("segment_id", item.get("segment"))
    if not isinstance(raw, (str, int)) or isinstance(raw, bool):
        return None
    value = str(raw).strip()
    token = value.strip("[]").split(" ")[0].strip("[]:")
    if token.isdigit():
        token = f"s{token}"
    return wanted.get(token) or by_text.get(" ".join(value.split()))


def validate_labels(
    raw: object,
    segments: Sequence[Segment],
    start: int,
    end: int,
    *,
    withheld: frozenset[str] = frozenset(),
) -> tuple[list[Draft], dict[str, int]]:
    """One segment object per labelled segment of this chunk; the rest dropped with a code."""
    wanted = {s.id: s for s in segments[start:end] if s.id not in withheld}
    by_text = {" ".join(s.text.split()): s for s in wanted.values()}
    dropped: dict[str, int] = {}
    labels = raw.get("labels") if isinstance(raw, Mapping) else None
    drafts: dict[str, Draft] = {}
    for item in labels if isinstance(labels, list) else []:
        if not isinstance(item, Mapping):
            dropped["shape"] = dropped.get("shape", 0) + 1
            continue
        segment = _match(item, wanted, by_text)
        if segment is None or segment.id in drafts:
            dropped["segment"] = dropped.get("segment", 0) + 1
            continue
        try:
            value = from_model(SEGMENT_TYPE, dict(item))
        except CallValueError as error:
            dropped[error.code] = dropped.get(error.code, 0) + 1
            continue
        drafts[segment.id] = Draft(
            type_key=SEGMENT_TYPE.key,
            category=SEGMENT_TYPE.category,
            value=value,
            display=display(SEGMENT_TYPE, value),
            confidence=0.8,
            basis="inferred",
            mentions=1,
            evidence=[
                {
                    "segment_id": segment.id,
                    "quote": segment.text[:600],
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "speaker": segment.speaker,
                }
            ],
        )
    missing = len(wanted) - len(drafts)
    if missing:
        dropped["unlabelled"] = missing
    order = {s.id: i for i, s in enumerate(segments)}
    return sorted(drafts.values(), key=lambda d: order[d.evidence[0]["segment_id"]]), dropped
