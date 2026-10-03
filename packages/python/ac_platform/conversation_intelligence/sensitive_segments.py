"""Pure withheld-text guard for sensitive transcript segments (AUT-519 D3-D5).

No database access and no I/O. The plan holds segment IDs and normalised word
4-grams only, never raw text. ``withhold`` returns a payload of the same shape:
keys, IDs, timings and list lengths are unchanged, and no field is added.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

WITHHELD_MARKER = "[Withheld for privacy]"
GRAM_SIZE = 4

Gram = tuple[str, ...]

_TOKEN = re.compile(r"[\w'-]+")
_EMPTY_GRAMS: frozenset[Gram] = frozenset()


def tokens(text: str) -> list[str]:
    """Normalise ``text`` (NFKC, casefold) and split it into word tokens."""
    return _TOKEN.findall(unicodedata.normalize("NFKC", text).casefold())


def grams(text: str) -> frozenset[Gram]:
    """Return the normalised word 4-grams of ``text``."""
    words = tokens(text)
    return frozenset(tuple(words[i : i + GRAM_SIZE]) for i in range(len(words) - GRAM_SIZE + 1))


@dataclass(frozen=True)
class WithheldPlan:
    """The withheld set W*: segment IDs plus the grams of the marked text."""

    segment_ids: frozenset[str]
    grams: frozenset[Gram]

    @property
    def empty(self) -> bool:
        return not self.segment_ids and not self.grams


EMPTY_PLAN = WithheldPlan(frozenset(), _EMPTY_GRAMS)


def withheld_plan(
    served_segments: Iterable[tuple[str, str]],
    marked_ids: Iterable[str],
    marked_grams: Iterable[Gram],
) -> WithheldPlan:
    """Build W* (plan D4) from ``(segment_id, text)`` pairs of the served transcript.

    ``marked_ids`` are marks on the served revision; ``marked_grams`` are the
    grams of every effective mark's text, on any revision of the recording.
    """
    gram_set = frozenset(marked_grams)
    ids = set(marked_ids)
    if gram_set:
        for segment_id, text in served_segments:
            if segment_id in ids or not isinstance(text, str):
                continue
            if grams(text) & gram_set:
                ids.add(segment_id)
    return WithheldPlan(frozenset(ids), gram_set)


def withhold[T](payload: T, plan: WithheldPlan) -> T:
    """Apply rules A, B and C (plan D5) recursively; identity when the plan is empty."""
    if plan.empty:
        return payload
    return cast(T, _withhold(payload, plan, in_segments=False))


def _shares(value: str, plan: WithheldPlan) -> bool:
    return bool(plan.grams) and bool(grams(value) & plan.grams)


def _withhold(value: Any, plan: WithheldPlan, *, in_segments: bool) -> Any:
    if isinstance(value, str):
        return WITHHELD_MARKER if _shares(value, plan) else value  # rule C
    if isinstance(value, list):
        return [_withhold(item, plan, in_segments=in_segments) for item in value]
    if isinstance(value, tuple):
        return tuple(_withhold(item, plan, in_segments=in_segments) for item in value)
    if not isinstance(value, Mapping):
        return value
    marked_evidence = value.get("segment_id") in plan.segment_ids  # rule A
    marked_segment = in_segments and value.get("id") in plan.segment_ids  # rule B
    result: dict[Any, Any] = {}
    for key, item in value.items():
        if marked_evidence and key in ("quote", "text"):
            result[key] = WITHHELD_MARKER if isinstance(item, str) else item
        elif "segment_id" in value and key in ("quote", "text"):
            result[key] = item  # evidence quotes follow only rule A
        elif marked_segment and key == "text":
            result[key] = WITHHELD_MARKER if isinstance(item, str) else item
        else:
            result[key] = _withhold(item, plan, in_segments=key == "segments")
    return result


def strings(payload: Any) -> Iterator[str]:
    """Yield every string value in ``payload`` (keys excluded), depth first."""
    if isinstance(payload, str):
        yield payload
    elif isinstance(payload, Mapping):
        for item in payload.values():
            yield from strings(item)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            yield from strings(item)


def shared_grams(payload: Any, marked_grams: Iterable[Gram]) -> int:
    """Count the distinct marked 4-grams that appear anywhere in ``payload``."""
    gram_set = frozenset(marked_grams)
    if not gram_set:
        return 0
    found: set[Gram] = set()
    for value in strings(payload):
        found |= grams(value) & gram_set
    return len(found)


def markers(payload: Any) -> int:
    """Count the string values equal to the marker."""
    return sum(1 for value in strings(payload) if value == WITHHELD_MARKER)


_PATH = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def at_path(payload: Any, path: str) -> Any:
    """Resolve ``dimensions[1].evidence[1]``-style paths; ``None`` when absent."""
    current = payload
    for name, index in _PATH.findall(path):
        if index:
            if not isinstance(current, (list, tuple)) or int(index) >= len(current):
                return None
            current = current[int(index)]
        else:
            if not isinstance(current, Mapping):
                return None
            current = current.get(name)
    return current
