"""Report settings with versions (owner order, 19 Oct 2026).

How the Report, Prospect and Coaching tabs present a call: a report style,
which parts, sections and data show, how much detail (complexity), and what is
on or off. Settings live in numbered, immutable versions:

- Version 1 is today's Report, Prospect and Coaching, frozen in code. It can't
  be edited; every later version starts from an earlier one.
- Admins create versions and choose which one applies to an organisation, as
  the default for an industry, or as the general default. Every choice is a new
  event (append-only), so rolling back is choosing an earlier version again and
  the history says who changed what and why.
- An organisation's version: its own choice, else its industry's default, else
  the general default, else version 1. An industry is one of the lead-stage
  profiles (lead_desk/journey/templates.py): the organisation's industry is the
  profile its newest lead stages were built from, so the Report and the lead
  stages are tailored by the same generic industry ids (orchestrator, 20 Oct).

Auto-tuning (AUT-2116, not built): every parameter below declares its bounds,
whether it is tunable, and which telemetry or outcome signals would tune it. A
tuner proposes a new version with ``origin='tuner'``; it never assigns one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ac_platform.lead_desk.journey.templates import DEFAULT_TEMPLATE, TEMPLATES

SCHEMA = "ac.sales-xray.report-settings/1"
VERSION_1_ID = UUID("6f1e0f3a-0b7c-5e3d-9a52-7d1c0e7a0001")
VERSION_1_CREATED_AT = datetime(2026, 10, 19, tzinfo=UTC)
# Every lead-stage profile but "Any business", which is the general default itself.
INDUSTRY_PROFILES: dict[str, str] = {
    profile.id: profile.name for profile in TEMPLATES if profile.id != DEFAULT_TEMPLATE
}

Complexity = Literal["simple", "standard", "expert"]
ReportStyle = Literal["guided", "compact", "scorecard"]
CoachingTone = Literal["supportive", "direct"]

# The Report's 27 pointers in the order the app shows them (xray-report/model.ts).
POINTER_IDS: tuple[str, ...] = (
    "call_opening",
    "purpose_agenda",
    "tone_energy",
    "active_listening",
    "open_ended_questions",
    "enough_questions",
    "prospect_role",
    "needs_challenges",
    "current_solution",
    "business_impact",
    "decision_process",
    "stakeholders",
    "objections",
    "solution_value",
    "pricing",
    "competition",
    "concerns_check",
    "next_steps",
    "call_control",
    "question_talk_ratio",
    "handling_silence",
    "professionalism",
    "closing_attitude",
    "building_rapport",
    "presenting_solution",
    "creating_value",
    "overall_communication",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ReportParts(_Strict):
    overview: bool = True
    analysis: bool = True
    outcome: bool = True

    @model_validator(mode="after")
    def _one_part(self) -> ReportParts:
        if not (self.overview or self.analysis or self.outcome):
            raise ValueError("Keep at least one part of the Report.")
        return self


class ReportSurface(_Strict):
    style: ReportStyle = "guided"
    complexity: Complexity = "standard"
    parts: ReportParts = ReportParts()
    pointers: tuple[str, ...] = POINTER_IDS
    max_pointers: int = Field(default=27, ge=3, le=27)
    show_scores: bool = True
    show_evidence: bool = True
    show_how_to_improve: bool = True

    @field_validator("pointers", mode="before")
    @classmethod
    def _pointer_list(cls, value: Any) -> Any:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("pointers")
    @classmethod
    def _known_pointers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("Show at least one pointer.")
        if len(set(value)) != len(value) or not set(value) <= set(POINTER_IDS):
            raise ValueError("Pointers must be distinct names from the Report's 27.")
        return value


class ProspectSections(_Strict):
    quality: bool = True
    chips: bool = True
    facts: bool = True
    problem: bool = True
    wants: bool = True
    blockers: bool = True
    personal: bool = True
    follow_up: bool = True
    next_action: bool = True
    buyer_info: bool = True


class ProspectSurface(_Strict):
    enabled: bool = True
    complexity: Complexity = "standard"
    sections: ProspectSections = ProspectSections()
    show_inferred: bool = True


class CoachingSurface(_Strict):
    enabled: bool = True
    complexity: Complexity = "standard"
    show_moments: bool = True
    max_moments: int = Field(default=5, ge=1, le=10)
    show_across_calls: bool = True
    tone: CoachingTone = "supportive"


class ReportSettings(_Strict):
    report: ReportSurface = ReportSurface()
    prospect: ProspectSurface = ProspectSurface()
    coaching: CoachingSurface = CoachingSurface()

    def document(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **self.model_dump(mode="json")}

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.document(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


VERSION_1 = ReportSettings()


def settings_from_document(document: Mapping[str, Any]) -> ReportSettings:
    """A saved version's settings; the schema line is checked, not stored twice."""

    if document.get("schema") != SCHEMA:
        raise ValueError("unknown_report_settings_schema")
    body = {key: value for key, value in document.items() if key != "schema"}
    return ReportSettings.model_validate(body, strict=False)


# ---------- the parameters, for the Admin form and a future tuner ----------


@dataclass(frozen=True)
class Parameter:
    key: str
    surface: Literal["report", "prospect", "coaching"]
    label: str
    help: str
    kind: Literal["choice", "toggle", "number", "pointers"]
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    # display: how the app presents a saved call; generation: how the AI writes it.
    applies: Literal["display", "generation"] = "display"
    # True when the Sales X-Ray app follows it (every display setting since
    # 20 Oct); a generation setting changes how the AI writes, not the app.
    in_app: bool = True
    tunable: bool = False
    signals: tuple[str, ...] = ()

    def view(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "surface": self.surface,
            "label": self.label,
            "help": self.help,
            "kind": self.kind,
            "choices": [{"value": value, "label": label} for value, label in self.choices],
            "minimum": self.minimum,
            "maximum": self.maximum,
            "applies": self.applies,
            "in_app": self.in_app,
            "tunable": self.tunable,
            "signals": list(self.signals),
        }


COMPLEXITY = (("simple", "Simple"), ("standard", "Standard"), ("expert", "Expert"))
READ = ("sx.report_opened", "sx.pillar_read")

PARAMETERS: tuple[Parameter, ...] = (
    Parameter(
        "report.style",
        "report",
        "Report style",
        "How the Report reads: guided (three parts with explanations), compact, or a scorecard.",
        "choice",
        choices=(("guided", "Guided"), ("compact", "Compact"), ("scorecard", "Scorecard")),
        tunable=True,
        signals=READ + ("sx.coaching_opened",),
    ),
    Parameter(
        "report.complexity",
        "report",
        "Report detail",
        "How much each pointer explains.",
        "choice",
        choices=COMPLEXITY,
        tunable=True,
        signals=READ,
    ),
    Parameter(
        "report.parts.overview",
        "report",
        "Overview & Score",
        "Part 1 of the Report.",
        "toggle",
        in_app=True,
    ),
    Parameter(
        "report.parts.analysis",
        "report",
        "Detailed Call Analysis",
        "Part 2 of the Report: the pointers.",
        "toggle",
        in_app=True,
    ),
    Parameter(
        "report.parts.outcome",
        "report",
        "Final Call Outcome",
        "Part 3 of the Report.",
        "toggle",
        in_app=True,
    ),
    Parameter(
        "report.pointers",
        "report",
        "Pointers shown",
        "Which of the 27 pointers the Detailed Call Analysis lists.",
        "pointers",
        tunable=True,
        signals=("sx.pillar_read", "gold.agreement"),
    ),
    Parameter(
        "report.max_pointers",
        "report",
        "Most pointers at once",
        'The most pointers listed before "show all".',
        "number",
        minimum=3,
        maximum=27,
        tunable=True,
        signals=READ,
    ),
    Parameter("report.show_scores", "report", "Scores", "AI scores out of 100.", "toggle"),
    Parameter(
        "report.show_evidence",
        "report",
        "Evidence quotes",
        "Quotes and moments from the call under each pointer.",
        "toggle",
        tunable=True,
        signals=("sx.clip_played",),
    ),
    Parameter(
        "report.show_how_to_improve",
        "report",
        "How to improve",
        "Tips under each pointer.",
        "toggle",
        tunable=True,
        signals=("sx.mission_started",),
    ),
    Parameter(
        "prospect.enabled",
        "prospect",
        "Prospect tab",
        "Show the Prospect tab.",
        "toggle",
        in_app=True,
    ),
    Parameter(
        "prospect.complexity",
        "prospect",
        "Prospect detail",
        "How much each section says.",
        "choice",
        choices=COMPLEXITY,
        tunable=True,
        signals=("sx.prospect_edited",),
    ),
    *(
        Parameter(
            f"prospect.sections.{key}",
            "prospect",
            label,
            "A section of the Prospect tab.",
            "toggle",
            tunable=True,
            signals=("sx.prospect_edited", "sx.outcome_set"),
        )
        for key, label in (
            ("quality", "Quality ring"),
            ("chips", "Deal, urgency and fit"),
            ("facts", "Facts grid"),
            ("problem", "Biggest problem"),
            ("wants", "What they want"),
            ("blockers", "What's stopping them"),
            ("personal", "Personal context"),
            ("follow_up", "Next follow-up"),
            ("next_action", "Suggested next action"),
            ("buyer_info", "Additional buyer information"),
        )
    ),
    Parameter(
        "prospect.show_inferred",
        "prospect",
        "Inferred facts",
        "Show facts the AI inferred, labelled, as well as what was said.",
        "toggle",
        tunable=True,
        signals=("sx.prospect_edited",),
    ),
    Parameter(
        "coaching.enabled",
        "coaching",
        "Coaching tab",
        "Show the Coaching tab.",
        "toggle",
        in_app=True,
    ),
    Parameter(
        "coaching.complexity",
        "coaching",
        "Coaching detail",
        "How much each tip explains.",
        "choice",
        choices=COMPLEXITY,
        tunable=True,
        signals=("sx.coaching_opened",),
    ),
    Parameter(
        "coaching.show_moments",
        "coaching",
        "Moments",
        "Clips of the moments to work on.",
        "toggle",
        tunable=True,
        signals=("sx.clip_played",),
    ),
    Parameter(
        "coaching.max_moments",
        "coaching",
        "Most moments",
        "The most moments shown.",
        "number",
        minimum=1,
        maximum=10,
        tunable=True,
        signals=("sx.clip_played",),
    ),
    Parameter(
        "coaching.show_across_calls",
        "coaching",
        "Across your calls",
        "Patterns across the rep's other calls.",
        "toggle",
        tunable=True,
        signals=("sx.coaching_opened",),
    ),
    Parameter(
        "coaching.tone",
        "coaching",
        "Coaching tone",
        "How the AI words its coaching.",
        "choice",
        choices=(("supportive", "Supportive"), ("direct", "Direct")),
        applies="generation",
        # How the AI writes, not how the app shows a saved call.
        in_app=False,
        tunable=True,
        signals=("sx.mission_completed",),
    ),
)


def flatten(settings: ReportSettings) -> dict[str, Any]:
    """Dotted keys to values, matching ``PARAMETERS`` keys."""

    flat: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else key, item)
        else:
            flat[prefix] = list(value) if isinstance(value, tuple) else value

    walk("", settings.model_dump(mode="json"))
    return flat


def changes(base: ReportSettings, settings: ReportSettings) -> list[dict[str, Any]]:
    """What a version changes against the version it started from."""

    before, after = flatten(base), flatten(settings)
    return [
        {"key": key, "from": before.get(key), "to": value}
        for key, value in after.items()
        if before.get(key) != value
    ]


# ---------- which version applies ----------


@dataclass(frozen=True)
class Choice:
    """The newest event for one scope: a version, or None to inherit again."""

    version: int | None
    at: datetime


def effective_version(
    *,
    organisation: Choice | None,
    industry: Choice | None,
    general: Choice | None,
) -> tuple[int, str]:
    """(version number, where it came from) for one organisation."""

    for source, choice in (
        ("organisation", organisation),
        ("industry", industry),
        ("general", general),
    ):
        if choice is not None and choice.version is not None:
            return choice.version, source
    return 1, "built_in"


def valid_industry(code: str | None) -> str | None:
    """A lead-stage profile id, e.g. real_estate; None for no industry."""

    if code is None:
        return None
    value = code.strip().lower()
    if value not in INDUSTRY_PROFILES:
        raise ValueError(
            "Choose an industry from the lead-stage profiles: " + ", ".join(INDUSTRY_PROFILES)
        )
    return value


def industry_of(profile: Any) -> str | None:
    """An organisation's industry: the lead-stage profile its newest stages came from."""

    if not isinstance(profile, str) or not profile:
        return None
    try:
        return valid_industry(profile)
    except ValueError:
        return None


def parameter_keys() -> Iterable[str]:
    return (parameter.key for parameter in PARAMETERS)


__all__ = [
    "PARAMETERS",
    "POINTER_IDS",
    "SCHEMA",
    "VERSION_1",
    "VERSION_1_CREATED_AT",
    "VERSION_1_ID",
    "INDUSTRY_PROFILES",
    "Choice",
    "Parameter",
    "ReportSettings",
    "changes",
    "effective_version",
    "flatten",
    "industry_of",
    "settings_from_document",
    "valid_industry",
]
