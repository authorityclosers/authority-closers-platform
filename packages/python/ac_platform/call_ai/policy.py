"""The levels of AI on a seller's calls and the rules that pick one (pure).

Cheapest first:

- ``off``: the call is saved and logged against its lead; no model reads it.
- ``data_only``: transcription (C2), then the call data engine's facts for the CRM
  (lead fields, next step, follow-ups: what WhatsApp and automations act on). No facts
  and coaching stages (C4, C5), so no Report, no pointer review and no one-pass read.
- ``auto``: the call-type router picks per call (phase 2). Until it exists, Auto runs
  in full.
- ``full``: today's analysis.

An organisation has a default (full until an owner or admin changes it) and each
person may have their own level, which beats the default. "Get full report" upgrades
one call. Release checks (canary calls) always run in full.

Short calls (owner, 21 Oct 2026: "calls under 1 minute (and no-conversation calls) get
only the transcript and lead details, with Get full report on tap"): in an
organisation, a call whose level would run in full keeps its transcript and the call
data engine's lead details, and stops before facts and coaching, when its transcript
is under a minute, or shows no conversation (under 20 seconds, or under 8 seconds of
talk from the quieter of its two main speakers). Get full report runs it in full.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Literal
from uuid import UUID

Level = Literal["off", "data_only", "auto", "full"]
LEVELS: Final[tuple[str, ...]] = ("off", "data_only", "auto", "full")
DEFAULT_LEVEL: Final = "full"
# Plain names, as the app shows them.
NAMES: Final[dict[str, str]] = {
    "off": "Off",
    "data_only": "Data only",
    "auto": "Auto",
    "full": "Full",
}
# The processing plan's hold codes: why a call stopped before a paid stage.
SKIP_CODES: Final[dict[str, str]] = {"off": "ai_off", "data_only": "ai_data_only"}
# Why a call stopped: its level, or the short-call rule (owner, 21 Oct 2026).
REASONS: Final[tuple[str, ...]] = ("level", "short_call", "no_conversation")
SHORT_CODES: Final[dict[str, str]] = {
    "short_call": "ai_short_call",
    "no_conversation": "ai_no_conversation",
}
FAILURE_CODES: Final[frozenset[str]] = frozenset((*SKIP_CODES.values(), *SHORT_CODES.values()))
# The short-call rule's limits, on the call's own transcript.
SHORT_CALL_MS: Final = 60_000
NO_CONVERSATION_MS: Final = 20_000
TWO_SIDED_TALK_MS: Final = 8_000
# Environments whose full-pipeline proofs use seconds-long fixture audio: the rule is
# off there (its own tests turn it on).
SHORT_RULE_OFF: frozenset[str] = frozenset({"test"})
# The first stage each level leaves out (Off: transcription; Data only: facts).
FIRST_SKIPPED: Final[dict[str, str]] = {"off": "C2", "data_only": "C4"}
# A settings document stays small: one line per person.
MAX_PEOPLE: Final = 2_000


class SettingsError(ValueError):
    """A settings document that can't be saved, in words the app can show."""


def effective(level: str) -> str:
    """What runs today for a chosen level: Auto runs in full until phase 2's router."""
    return DEFAULT_LEVEL if level == "auto" else level


def skipped_from(level: str) -> str | None:
    """The first stage this level leaves out, or None when every stage runs."""
    return FIRST_SKIPPED.get(effective(level))


def defaults() -> dict[str, Any]:
    return {"default": DEFAULT_LEVEL, "people": {}}


def validate(config: Mapping[str, Any]) -> dict[str, Any]:
    """The checked settings document: a default level and each person's own level."""
    if not isinstance(config, Mapping) or set(config) - {"default", "people"}:
        raise SettingsError("Settings hold a default level and people's own levels only.")
    default = config.get("default", DEFAULT_LEVEL)
    if default not in LEVELS:
        raise SettingsError("Choose Off, Data only, Auto or Full.")
    people = config.get("people") or {}
    if not isinstance(people, Mapping) or len(people) > MAX_PEOPLE:
        raise SettingsError("Too many people's own levels.")
    checked: dict[str, str] = {}
    for key, level in people.items():
        try:
            person = str(UUID(str(key)))
        except ValueError:
            raise SettingsError("A person's own level names an unknown person.") from None
        if level not in LEVELS:
            raise SettingsError("Choose Off, Data only, Auto or Full.")
        checked[person] = str(level)
    return {"default": str(default), "people": dict(sorted(checked.items()))}


def with_person(config: Mapping[str, Any], person_id: UUID, level: str | None) -> dict[str, Any]:
    """The document with one person's own level set, or removed when ``level`` is None."""
    people = dict(config.get("people") or {})
    if level is None:
        people.pop(str(person_id), None)
    else:
        people[str(person_id)] = level
    return validate({"default": config.get("default", DEFAULT_LEVEL), "people": people})


def resolve(config: Mapping[str, Any], person_id: UUID | None) -> tuple[str, str]:
    """(level, source) for one person: their own level, else the organisation's default.

    ``source`` is ``person`` or ``organisation``; a call with no known person (a guest
    upload) follows the organisation's default.
    """
    people = config.get("people") or {}
    if person_id is not None and str(person_id) in people:
        return str(people[str(person_id)]), "person"
    return str(config.get("default", DEFAULT_LEVEL)), "organisation"


def short_rule_applies(environment: object) -> bool:
    """On in every named environment but those in ``SHORT_RULE_OFF`` (tests)."""
    return isinstance(environment, str) and environment not in SHORT_RULE_OFF


def short_call_reason(transcript: Mapping[str, Any]) -> str | None:
    """``no_conversation``, ``short_call`` or None for one saved C2 transcript.

    Length is the transcript's ``duration_ms`` (else its last segment's end). Two-sided
    talk is the speaking time of the quieter of the two speakers who talk most, so a
    voicemail, a ring-out or one person talking is no conversation."""
    segments = [item for item in transcript.get("segments") or [] if isinstance(item, Mapping)]
    talk: dict[str, int] = {}
    last_end = 0
    for item in segments:
        try:
            start, end = int(item.get("start_ms") or 0), int(item.get("end_ms") or 0)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        speaker = str(item.get("speaker_id") or item.get("speaker") or "")
        talk[speaker] = talk.get(speaker, 0) + (end - start)
        last_end = max(last_end, end)
    try:
        duration = int(transcript.get("duration_ms") or 0) or last_end
    except (TypeError, ValueError):
        duration = last_end
    spoken = sorted(talk.values(), reverse=True)
    two_sided = spoken[1] if len(spoken) > 1 else 0
    if duration < NO_CONVERSATION_MS or two_sided < TWO_SIDED_TALK_MS:
        return "no_conversation"
    if duration < SHORT_CALL_MS:
        return "short_call"
    return None
