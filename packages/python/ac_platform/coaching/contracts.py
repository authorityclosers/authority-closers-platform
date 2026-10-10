"""Coaching concepts. Qualitative report states never become execution verdicts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

GapType = Literal[
    "knowledge",
    "judgment",
    "execution",
    "habit_recall",
    "confidence",
    "cognitive_load",
    "belief_buy_in",
    "adherence",
    "skill_dependency",
    "context_specific",
    "uncertain",
]
MasteryState = Literal[
    "not_enough_evidence",
    "emerging",
    "developing",
    "consistent",
    "strong",
    "mastered",
    "regression_detected",
    "re_stabilizing",
]
Trend = Literal["improving", "stable", "declining", "not_enough_evidence"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Moment(Model):
    submission_id: UUID
    recording_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcript_revision: str = Field(min_length=1, max_length=256)
    created_at: datetime
    call_label: str = Field(min_length=1, max_length=256)
    segment_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=2000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    observation: str = Field(min_length=1, max_length=4000)
    playable: bool = True

    @model_validator(mode="after")
    def ordered(self) -> "Moment":
        if self.end_ms <= self.start_ms:
            raise ValueError("Evidence must have a positive source span.")
        return self


class Mission(Model):
    skill_id: str
    behavior: str
    context: str
    done_when: str
    cue: str
    active_since: datetime
    origin_submission_id: UUID
    status: Literal["active", "completed", "superseded"] = "active"


class Practice(Model):
    exercise: str
    success_condition: str
    gap_type: GapType = "uncertain"
    estimated_minutes: int | None = None


class SkillObservation(Model):
    skill_id: str
    label: str
    report_status: Literal["observed", "partial"]
    observation: str
    evidence: tuple[Moment, ...] = Field(min_length=1, max_length=8)
    improvement: str | None = None
    why_it_matters: str | None = None
    mission: Mission | None = None
    practice: Practice | None = None

    @model_validator(mode="after")
    def linked_mission(self) -> "SkillObservation":
        if self.mission is not None and (
            self.mission.skill_id != self.skill_id
            or any(
                moment.submission_id != self.mission.origin_submission_id
                for moment in self.evidence
            )
        ):
            raise ValueError("A skill mission must link to its own call evidence.")
        return self


class CallHistory(Model):
    submission_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    comparison_key: str = Field(min_length=1, max_length=256)
    skills: tuple[SkillObservation, ...]

    @model_validator(mode="after")
    def bound_evidence(self) -> "CallHistory":
        if len({skill.skill_id for skill in self.skills}) != len(self.skills) or any(
            moment.submission_id != self.submission_id or moment.source_sha256 != self.source_sha256
            for skill in self.skills
            for moment in skill.evidence
        ):
            raise ValueError("Call evidence cannot cross a source or duplicate a skill.")
        return self


class RootCause(Model):
    hypothesis: str = "We do not yet have enough evidence to say why this happens."
    gap_type: GapType = "uncertain"
    confidence: Literal["high", "medium", "low", "uncertain"] = "uncertain"
    alternatives: tuple[str, ...] = ()
    learner_context: str | None = None


class Pattern(Model):
    relevant_call_count: int = 0
    attention_call_count: int = 0
    summary: str
    # A call-level dimension is not a count of discrete behavior opportunities.
    relevant_opportunities: int | None = None
    occurrence_count: int | None = None
    contexts: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()


class Mastery(Model):
    state: MasteryState = "not_enough_evidence"
    trend: Trend = "not_enough_evidence"
    relevant_count: int | None = None
    correct_count: int | None = None
    baseline: str | None = None
    confidence: str = "uncertain"
    historical_achievement: MasteryState | None = None
    explanation: str = (
        "Your reports contain skill observations, but do not yet record comparable "
        "opportunities and successful execution. A call count cannot establish mastery."
    )


class Regression(Model):
    state: Literal["unknown", "monitor", "reminder", "recurring", "severe", "re_stabilizing"]
    action: str
    evidence: tuple[Moment, ...] = ()


class TextLesson(Model):
    title: str
    quick_idea: str
    framework: tuple[str, ...]
    why_it_matters: str
    good_looks_like: str
    better_direction: str
    example_wording: tuple[str, ...]
    when_to_use: str
    when_not: str
    checklist: tuple[str, ...]
    source: str
    own_call: Moment
    next_call_connection: str


class LearningAsset(Model):
    asset_id: str
    title: str
    kind: Literal["audio", "video"]
    skill_ids: tuple[str, ...]
    topics: tuple[str, ...]
    gap_types: tuple[GapType, ...]
    duration_seconds: int = Field(gt=0)
    url: str
    approved: bool
    relevance: str
    takeaways: tuple[str, ...] = Field(min_length=1, max_length=5)


class Focus(Model):
    skill_id: str
    label: str
    explanation: str
    why_it_matters: str
    selected_reason: str
    selected_at: datetime
    status: Literal["provisional", "active"]
    verdict: str


class Path(Model):
    current: str | None
    likely_next: str | None = None
    maintain: str | None = None
    later: str | None = None
    explanation: str


class LearnerFeedback(Model):
    """A command concept; persistence is required before reporting it as saved."""

    agreement: Literal["agree", "not_completely", "add_context"]
    context: str = Field(default="", max_length=2000)
    reflection_answer: str = Field(default="", max_length=2000)
    focus_skill_id: str
    evidence_submission_ids: tuple[UUID, ...] = Field(min_length=1, max_length=4)
    resolution: Literal["pending", "maintain", "modify", "withdraw"] = "pending"


class CoachingView(Model):
    schema_id: Literal["ac.sales-xray.coaching/1"] = Field(
        default="ac.sales-xray.coaching/1", alias="schema"
    )
    person_id: UUID
    tenant_id: UUID
    authority: Literal["provisional"] = "provisional"
    entitlement: Literal["coaching"] = "coaching"
    entitlement_policy: Literal["AUT-1678-open-access"] = "AUT-1678-open-access"
    state: Literal["not_enough_evidence", "ready"]
    analysed_calls: int
    pending_calls: int = 0
    unavailable_calls: int = 0
    history_limited: bool = False
    focus: Focus | None
    pattern: Pattern
    root_cause: RootCause = RootCause()
    evidence: tuple[Moment, ...] = Field(max_length=4)
    practice: Practice | None
    mission: Mission | None
    mastery: Mastery = Mastery()
    regression: Regression = Regression(
        state="unknown", action="More comparable behavior evidence is needed to assess regression."
    )
    lesson: TextLesson | None
    recommended_media: LearningAsset | None = None
    other_format: LearningAsset | None = None
    development_path: Path
    reflection_question: str | None
    feedback_available: Literal[False] = False
    limitations: tuple[str, ...]
