"""Anonymous report suggestions only; no rep's private Coaching is disclosed."""

from collections import Counter
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ac_platform.coaching.contracts import CallHistory, Model

# Fixed approved taxonomy, never a source's title, quote or a person's name.
LABELS = {
    "human_connection_trust": "Human Connection & Trust",
    "discovery_deep_understanding": "Discovery & Deep Understanding",
    "qualification": "Qualification",
    "problem_impact_desire": "Problem, Impact & Desire Clarity",
    "solution_relevance_presentation": "Solution Relevance & Presentation",
    "certainty_objection_intelligence": "Certainty & Objection Intelligence",
    "closing_decision_management": "Closing & Decision Management",
    "communication_tonality": "Communication & Tonality",
    "report_next_step": "Other call report suggestions",
}


class TeamSuggestion(Model):
    skill_id: str
    label: str
    suggestion_calls: int = Field(ge=1)


class TeamRep(Model):
    """A named rep row. Only fictional AC Sandbox reps today; real reps appear
    here only after they share their coaching (owner decision 2)."""

    person_id: UUID
    name: str = Field(min_length=1, max_length=120)
    skill_id: str | None = None
    focus_label: str | None = Field(default=None, max_length=240)
    calls: int = Field(ge=0)
    latest_call_at: datetime | None = None


class TeamCoachingView(Model):
    schema_id: Literal["ac.sales-xray.team-coaching/1"] = Field(
        default="ac.sales-xray.team-coaching/1", alias="schema"
    )
    person_id: UUID  # requesting account only, never a rep identifier
    tenant_id: UUID
    session_id: UUID | None = None
    entitlement: Literal["coaching"] = "coaching"
    entitlement_policy: Literal["AUT-1678-open-access"] = "AUT-1678-open-access"
    scope: Literal["anonymous", "sandbox"] = "anonymous"
    named_rep_details: bool = False
    # Fictional AC Sandbox data, read only by the person who imported it.
    sandbox: bool = False
    analysed_calls: int = Field(ge=0)
    # How many people those calls belong to: a count, never who they are.
    rep_count: int = Field(default=0, ge=0)
    pending_calls: int = Field(ge=0)
    unavailable_calls: int = Field(ge=0)
    history_limited: bool
    # When the newest counted report's call happened; a date, never whose call.
    latest_call_at: datetime | None = None
    suggestions: tuple[TeamSuggestion, ...]
    reps: tuple[TeamRep, ...] = ()
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def names_only_for_fictional_reps(self) -> "TeamCoachingView":
        if (self.named_rep_details or self.reps) and not (
            self.sandbox and self.scope == "sandbox" and self.named_rep_details
        ):
            raise ValueError("Team totals name no real rep until sharing exists.")
        return self


def summarize_team(
    history: tuple[tuple[UUID, CallHistory], ...],
    *,
    person_id: UUID,
    tenant_id: UUID,
    pending_calls: int = 0,
    unavailable_calls: int = 0,
    history_limited: bool = False,
) -> TeamCoachingView:
    """Count source-bound recommendations, not mistakes, success rates or mastery.

    Duplicate uploads count once per owner/source. Report status (including
    `partial`) alone never creates a suggestion. Caller authorizes every report.
    Input text/identifiers are deliberately absent from the response structure.
    """
    unique: dict[tuple[UUID, str], CallHistory] = {}
    for owner, call in sorted(history, key=lambda row: row[1].created_at, reverse=True):
        unique.setdefault((owner, call.source_sha256), call)
    counts: Counter[str] = Counter()
    for call in unique.values():
        counts.update(
            {
                row.skill_id
                for row in call.skills
                if row.skill_id in LABELS and row.improvement and row.mission
            }
        )
    return TeamCoachingView(
        person_id=person_id,
        tenant_id=tenant_id,
        analysed_calls=len(unique),
        rep_count=len({owner for owner, _source in unique}),
        pending_calls=pending_calls,
        unavailable_calls=unavailable_calls,
        history_limited=history_limited,
        latest_call_at=max((call.created_at for call in unique.values()), default=None),
        suggestions=tuple(
            TeamSuggestion(skill_id=skill, label=LABELS[skill], suggestion_calls=count)
            for skill, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ),
        limitations=(
            "Counts describe report suggestions, not proven recurring mistakes or mastery.",
            "No rep's focus, root cause, mission, identity or call evidence is disclosed.",
            "Named coaching requires an explicit, revocable share; sharing is not active yet.",
            "Assigned coach duties are pending. Current organisation owners/admins see aggregates.",
            *(
                ("Only the most recent 40 retained team calls are included.",)
                if history_limited
                else ()
            ),
        ),
    )
