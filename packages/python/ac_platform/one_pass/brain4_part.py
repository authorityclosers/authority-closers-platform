"""The Brain 4.0 part of the one-pass C4 request: recipe v2 (``markers.RECIPE_V2``).

Orchestrator, 22 Oct 2026 (P1, planned with the cost research session): the production
one-pass read also answers Brain 4.0's 18-skill review (``conversation_intelligence.brain4``),
so a call's Brain 4.0 block comes from the read its plan already pays for. The Report shows
a review's own ``brain4`` block, and the separate shadow read skips any call whose review
carries one.

v2 is v1's request (call data, notes and the 27-pointer review, ``analysis``) with one more
part, ``brain4``: Brain 4.0's own instructions and strict schema, its answer checked by
``brain4.parse``. The v2 prompt is built from v1's own text, so the two cannot drift; v1's
prompt, schema and sealed configurations are unchanged, and v2 has its own recipe, marker
and Root seal.

Beta only (AGENTS.md: no official autonomous scoring before the AC-SVAL gates): every
parsed block says ``status: beta``.

Pure: no I/O, no provider.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Mapping, Sequence
from typing import Any, Final

from ac_platform.conversation_intelligence import brain4
from ac_platform.one_pass import analysis

PART: Final = "brain4"
_V1_PARTS: Final = ("call_data", "notes", "review")
PARTS: Final = (*_V1_PARTS, PART)


class Brain4PartError(ValueError):
    """A stable code only."""


@functools.cache
def stage_system_prompt() -> str:
    """v1's stage prompt, its header naming the four parts, then the Brain 4.0 part."""
    v1 = analysis.stage_system_prompt()
    head = analysis._header(_V1_PARTS)
    if not v1.startswith(head):
        raise Brain4PartError("one_pass_v1_prompt_changed")
    return (
        analysis._header(PARTS)
        + v1[len(head) :]
        + "\nPART brain4: the Brain 4.0 18-skill review (beta).\n"
        + brain4.part_instructions()
    )


@functools.cache
def _stage_schema() -> dict[str, Any]:
    schema = analysis.stage_schema()
    schema["properties"][PART] = brain4.response_schema()
    schema["required"] = [*schema["required"], PART]
    return schema


def stage_schema() -> dict[str, Any]:
    return copy.deepcopy(_stage_schema())


def parse(
    answer: Mapping[str, Any],
    segments: Sequence[Mapping[str, Any]],
    *,
    withheld: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, str]:
    """The answer's Brain 4.0 block, checked by ``brain4.parse`` against the segments that
    are not withheld (as the shadow read does): ``(block, "parsed")``, or ``(None, code)``
    when it is missing or does not check out. Never raises, so the pointer review the block
    rides with is always kept."""
    visible = [segment for segment in segments if str(segment.get("id")) not in withheld]
    try:
        return brain4.parse(answer.get(PART), visible), "parsed"
    except brain4.Brain4Error as error:
        return None, str(error)[:48]
    except (TypeError, ValueError, KeyError):
        return None, "brain4_invalid"
