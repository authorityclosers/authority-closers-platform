"""Preserve authored sandbox bundles; never infer scores or actual media evidence."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from ac_platform.conversation_intelligence.application import utc

PILLARS = frozenset(
    (
        "the_big_picture",
        "how_the_call_played_out",
        "what_worked_and_what_didnt",
        "moments_that_mattered",
        "your_skills_on_this_call",
        "where_the_deal_stands",
    )
)
COACHING = frozenset(("current_focus", "diagnosis", "teaching", "action", "progress", "direction"))
VERSIONS = frozenset(("synthetic-sales-v1.0", "synthetic-sales-simulation/1"))
SYNTHETIC_KEY = re.compile(r"syn-[A-Za-z0-9][A-Za-z0-9._:-]{0,150}\Z")
MAX_BUNDLE_BYTES = 800 * 1024


def authored_object(value: JsonValue, call_id: str) -> dict[str, JsonValue]:
    if (
        not isinstance(value, dict)
        or value.get("synthetic") is not True
        or not isinstance(value.get("schema_version"), str)
        or value.get("schema_version") not in VERSIONS
        or value.get("call_id") != call_id
    ):
        raise ValueError("Each authored component needs the same explicit synthetic call identity.")
    return value


def no_unverified_playback(
    value: JsonValue, depth: int = 0, *, verified_audio: bool = False
) -> None:
    if depth > 32:
        raise ValueError("The synthetic bundle is too deeply nested.")
    if isinstance(value, dict):
        if value.get("playable") is True and not verified_audio:
            raise ValueError(
                "Text bundles cannot certify playable audio or precise media evidence."
            )
        for item in value.values():
            no_unverified_playback(item, depth + 1, verified_audio=verified_audio)
    elif isinstance(value, list):
        for item in value:
            no_unverified_playback(item, depth + 1, verified_audio=verified_audio)


class SyntheticCallBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["synthetic-call-bundle/1"] = Field(alias="schema")
    synthetic: Literal[True]
    metadata: dict[str, JsonValue]
    transcript: dict[str, JsonValue]
    answer_key: dict[str, JsonValue]
    report: dict[str, JsonValue]
    coaching: dict[str, JsonValue]

    @model_validator(mode="before")
    @classmethod
    def explicit_synthetic(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("synthetic") is not True:
            raise ValueError("Synthetic must be explicitly true.")
        return value

    @model_validator(mode="after")
    def exact_authored_bundle(self) -> SyntheticCallBundle:
        if type(self.synthetic) is not bool:
            raise ValueError("Synthetic must be explicitly true.")
        metadata = self.metadata
        call_id, business = metadata.get("call_id"), metadata.get("business_id")
        if (
            not isinstance(call_id, str)
            or not SYNTHETIC_KEY.fullmatch(call_id)
            or not isinstance(business, str)
            or not SYNTHETIC_KEY.fullmatch(business)
            or not call_id.startswith(business + "-")
            or metadata.get("team_namespace") != business + "-sandbox-synthetic"
        ):
            raise ValueError("Use exact synthetic call, business and isolated team keys.")
        for field in ("journey_id", "company_id", "prospect_id", "rep_id"):
            key = metadata.get(field)
            if (
                not isinstance(key, str)
                or not SYNTHETIC_KEY.fullmatch(key)
                or not key.startswith(business + "-")
            ):
                raise ValueError("Synthetic entities must belong to their exact selling business.")
        when = metadata.get("at")
        if not isinstance(when, str):
            raise ValueError("Provide the authored call date.")
        try:
            occurred = datetime.fromisoformat(when)
            if occurred.tzinfo is None:
                raise ValueError("The authored call date requires its timezone.")
        except ValueError:
            raise ValueError("Provide the authored call date with its timezone.") from None
        if metadata.get("private_coaching") is not True:
            raise ValueError("Synthetic coaching remains private to its importer.")
        verified_audio = metadata.get("audio_file") == "audio.mp3" and (
            metadata.get("audio_status") == "verified"
            and metadata.get("timing_source") in ("spool_exact", "silence_aligned")
        )
        if metadata.get("audio_file") is not None and not verified_audio:
            raise ValueError("Audio requires the exact verified-media handoff.")
        duration = metadata.get("duration_ms")
        if type(duration) is not int or not 1 <= duration <= 3_600_000:
            raise ValueError(
                "Provide a bounded authored duration; it is not native audio measurement."
            )
        for component in (metadata, self.transcript, self.answer_key, self.report, self.coaching):
            authored_object(component, call_id)
            no_unverified_playback(component, verified_audio=verified_audio)
        if not self.report.keys() >= PILLARS or not self.coaching.keys() >= COACHING:
            raise ValueError("Preserve all six authored report pillars and coaching sections.")
        for field, component, sections in (
            ("report", self.report, PILLARS),
            ("per_call_coaching", self.coaching, COACHING),
        ):
            original = self.answer_key.get(field)
            # F wraps the same authored sections in a simulation-version header
            # and call_id. That documented envelope is the only difference.
            if (
                not isinstance(original, dict)
                or original.get("synthetic") is not True
                or not isinstance(original.get("schema_version"), str)
                or original.get("schema_version") not in VERSIONS
                or any(original.get(section) != component[section] for section in sections)
                or set(original) - {"synthetic", "schema_version"} != sections
                or set(component) - {"synthetic", "schema_version", "call_id"} != sections
            ):
                raise ValueError("Report and coaching must preserve the exact authored sections.")
        if self.answer_key.get("as_of") != when:
            raise ValueError("The answer key must describe the call as of its authored date.")
        for field in ("business_id", "journey_id", "rep_id"):
            if self.answer_key.get(field) != metadata[field]:
                raise ValueError("The answer key's synthetic entity lineage must match the call.")
        transcript = self.transcript
        if any(
            transcript.get(field) != metadata[field]
            for field in (
                "business_id",
                "journey_id",
                "company_id",
                "prospect_id",
                "rep_id",
                "at",
                "duration_ms",
            )
        ):
            raise ValueError("Transcript identity, date and authored duration must match metadata.")
        participants, lines = transcript.get("participants"), transcript.get("lines")
        if not isinstance(participants, list) or not 2 <= len(participants) <= 12:
            raise ValueError("Provide the authored synthetic participants.")
        people: set[str] = set()
        for participant in participants:
            if not isinstance(participant, dict):
                raise ValueError("Provide explicit synthetic participant identities.")
            key = participant.get("person_id")
            if (
                participant.get("synthetic") is not True
                or not isinstance(key, str)
                or not SYNTHETIC_KEY.fullmatch(key)
                or not key.startswith(business + "-")
            ):
                raise ValueError("Synthetic participants cannot create real identities.")
            people.add(key)
        if not isinstance(lines, list) or not 1 <= len(lines) <= 2000:
            raise ValueError("Provide a bounded authored transcript.")
        previous_end, seen = 0, set()
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("Provide explicit authored transcript lines.")
            identifier, start, end = line.get("line_id"), line.get("start_ms"), line.get("end_ms")
            text = line.get("text")
            if (
                line.get("synthetic") is not True
                or not isinstance(identifier, str)
                or not identifier.startswith(call_id + ":L")
                or identifier in seen
                or not isinstance(line.get("person_id"), str)
                or line.get("person_id") not in people
                or type(start) is not int
                or type(end) is not int
                or not previous_end <= start < end <= duration
                or not isinstance(text, str)
                or not text.strip()
                or len(text) > 4000
            ):
                raise ValueError(
                    "Authored lines need exact unique identities and bounded estimated times."
                )
            previous_end = end
            seen.add(identifier)
        if (
            len(
                json.dumps(
                    self.model_dump(by_alias=True), ensure_ascii=False, allow_nan=False
                ).encode()
            )
            > MAX_BUNDLE_BYTES
        ):
            raise ValueError("Import one bounded synthetic call bundle per request.")
        return self

    @property
    def occurred_at(self) -> datetime:
        return utc(datetime.fromisoformat(str(self.metadata["at"])))


SyntheticKind = Literal[
    "world",
    "business_history",
    "people",
    "companies",
    "contacts",
    "leads",
    "deals",
    "invoices",
    "payments",
    "calendar",
    "people_events",
    "rep_weeks",
    "sales_events",
    "skills",
    "missions",
    "call_summary",
]


class SyntheticRecordInput(BaseModel):
    """A preserved dataset record; it never creates a real person or payment."""

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: SyntheticKind
    key: str = Field(pattern=r"\A" + SYNTHETIC_KEY.pattern.replace(r"\Z", r"\z"))
    business_id: str = Field(pattern=r"\A" + SYNTHETIC_KEY.pattern.replace(r"\Z", r"\z"))
    revision: int = Field(ge=1, le=1_000_000)
    occurred_at: datetime
    payload: dict[str, JsonValue]

    @field_validator("occurred_at", mode="before")
    @classmethod
    def authored_date(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                raise ValueError("Provide an authored ISO date with its timezone.") from None
        return value

    @model_validator(mode="after")
    def isolated_authored_record(self) -> SyntheticRecordInput:
        if self.occurred_at.tzinfo is None:
            raise ValueError("Synthetic dates need explicit timezones.")
        if self.key != self.business_id and not self.key.startswith(self.business_id + "-"):
            raise ValueError("Synthetic record keys must belong to their exact business.")
        if (
            self.payload.get("synthetic") is not True
            or not isinstance(self.payload.get("schema_version"), str)
            or self.payload.get("schema_version") not in VERSIONS
            or self.payload.get("business_id", self.business_id) != self.business_id
        ):
            raise ValueError("Preserve an explicitly synthetic, business-bound dataset record.")
        no_unverified_playback(self.payload)
        if (
            len(json.dumps(self.payload, ensure_ascii=False, allow_nan=False).encode())
            > MAX_BUNDLE_BYTES
        ):
            raise ValueError("Synthetic records must stay bounded.")
        if self.kind == "call_summary":
            if self.payload.get("call_id") != self.key:
                raise ValueError("A summary needs its exact synthetic call key.")
            report = self.payload.get("report")
            if not isinstance(report, dict) or not report.keys() >= PILLARS:
                raise ValueError("Preserve the six authored summary pillars.")
        return self
