"""One pass inside the sealed processing plan: the C4 stage as one request.

Owner, 21 Oct 2026: "Then build B together with the Luna route (one-pass in the sealed
plan, beta-labelled calibrated scores, call data written in production)". Today C4 reads
the transcript in fact chunks, the pointer review reads it again and (where it runs) the
call data engine twice more. Here C4 is one request over the whole transcript that
answers the call data, notes and the pointer review together (``analysis``); its C4 fact
packet is checked by C4's own parser and today's C5 reads it as before.

The request is today's C4 envelope (``ac.sales-xray.native-scribe-input/1``, one chunk
covering every segment, with the call's date for relative days), so every existing
envelope, coverage and receipt check applies unchanged. Only the system prompt (it
starts with ``MARKER``), its strict schema and the normaliser differ. A provider
configuration selects it by its facts route's recipe (``RECIPE``), sealed by Root like
any route; the plan then asks one request with this prompt revision.

Pure: no I/O, no provider.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ac_platform.call_data import extraction
from ac_platform.conversation_intelligence import reports
from ac_platform.one_pass import analysis
from ac_platform.one_pass.markers import (
    MARKER,
    MAX_COMPLETION_TOKENS,
    PROMPT_REVISION,
    RECIPE,
    ROUTES,
    call_date,
    is_one_pass,
)

__all__ = [
    "MARKER",
    "MAX_COMPLETION_TOKENS",
    "PROMPT_REVISION",
    "RECIPE",
    "ROUTES",
    "call_date",
    "is_one_pass",
]


class StageError(ValueError):
    """A stable code only."""


def system_prompt() -> str:
    return MARKER + "\n" + analysis.stage_system_prompt()


def schema() -> dict[str, Any]:
    return analysis.stage_schema()


def prompt(
    transcript: Mapping[str, Any],
    *,
    model: str,
    max_completion_tokens: int,
    date: str,
) -> dict[str, Any]:
    """The request in today's C4 prompt shape (one chunk covering every segment)."""
    if type(max_completion_tokens) is not int or not 256 <= max_completion_tokens <= (
        MAX_COMPLETION_TOKENS
    ):
        raise StageError("one_pass_output_budget_invalid")
    if not isinstance(date, str) or not date.strip() or len(date) > 64:
        raise StageError("one_pass_call_date_invalid")
    try:
        validated = reports._validated_transcript(transcript)
    except reports.ReportError as error:
        raise StageError(str(error)) from None
    segments = [dict(segment) for segment in validated["segments"]]
    payload = reports._fact_user_payload(validated, segments, 1, 1)
    payload["call_date"] = date
    return {
        "model": model,
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ],
    }


def drafts(answer: Mapping[str, Any], transcript: Mapping[str, Any]) -> tuple[Any, ...]:
    """The call data part, checked by the call data engine's own validator."""
    segments = extraction.segments_from_transcript(transcript)
    found, _ = extraction.validate_response(
        answer.get("call_data"), segments, types=analysis.TYPES, withheld=frozenset()
    )
    return tuple(found)


def fact_packet(
    answer: Mapping[str, Any],
    transcript: Mapping[str, Any],
    *,
    chunk: reports.TranscriptChunk | None = None,
) -> reports.FactPacket:
    """The C4 fact packet: each call data fact and note as one observation with its
    segments' own words and times, checked by C4's own parser."""
    if not isinstance(answer, Mapping):
        raise reports.ReportError("fact_response_invalid")
    candidate = analysis.fact_candidate(
        drafts(answer, transcript),
        answer.get("notes"),
        transcript,
        overview="",
        withheld=frozenset(),
    )
    return reports.parse_fact_packet(candidate, transcript, chunk=chunk)
