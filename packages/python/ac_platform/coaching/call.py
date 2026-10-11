"""One authorized report → one call's coaching; never rotate the learner mission."""

from collections import OrderedDict
from datetime import datetime
from time import monotonic
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ac_platform.coaching.contracts import (
    ClipSuggestion,
    Focus,
    Mission,
    Model,
    Moment,
    Practice,
    RootCause,
    TextLesson,
)
from ac_platform.coaching.lessons import lesson_for
from ac_platform.coaching.report_adapter import _moments, _refs, _text, from_report
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER


class CallCoachingView(Model):
    schema_id: Literal["ac.sales-xray.call-coaching/1"] = Field(
        default="ac.sales-xray.call-coaching/1", alias="schema"
    )
    person_id: UUID
    tenant_id: UUID
    session_id: UUID | None = None
    submission_id: UUID
    recording_id: UUID
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcript_revision: str
    report_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_label: str
    authority: Literal["provisional"] = "provisional"
    entitlement: Literal["coaching"] = "coaching"
    entitlement_policy: Literal["AUT-1678-open-access"] = "AUT-1678-open-access"
    state: Literal["ready", "unavailable"]
    basis: Literal["skill_evidence", "report_suggestion", "general_practice", "unavailable"]
    focus: Focus | None
    evidence: tuple[Moment, ...] = Field(max_length=4)
    root_cause: RootCause = RootCause()
    lesson: TextLesson | None
    practice: Practice | None
    mission: Mission | None
    media_clips: tuple[ClipSuggestion, ...] = Field(default=(), max_length=3)
    recommended_media: None = None
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def own_call(self) -> "CallCoachingView":
        moments = (
            *self.evidence,
            *([self.lesson.own_call] if self.lesson and self.lesson.own_call else []),
        )
        if any(
            moment.submission_id != self.submission_id
            or moment.recording_id != self.recording_id
            or moment.source_sha256 != self.source_sha256
            or moment.transcript_revision != self.transcript_revision
            for moment in moments
        ):
            raise ValueError("Call coaching evidence must belong to this exact call source.")
        if self.state == "ready":
            if not self.focus or not self.lesson or not self.practice or not self.mission:
                raise ValueError(
                    "Ready call coaching requires a focus, lesson, practice and mission."
                )
            if (
                self.mission.origin_submission_id != self.submission_id
                or self.mission.skill_id != self.focus.skill_id
                or self.lesson.next_call_connection != self.mission.behavior
            ):
                raise ValueError("Call coaching must keep one source-bound mission.")
        elif (
            self.focus
            or self.evidence
            or self.lesson
            or self.practice
            or self.mission
            or self.media_clips
        ):
            raise ValueError("Unavailable coaching must not retain private evidence.")
        return self


def build_call_coaching(
    envelope: dict[str, Any],
    *,
    submission_id: UUID,
    created_at: datetime,
    person_id: UUID,
    tenant_id: UUID,
) -> CallCoachingView:
    """Caller supplies the freshly authorized and withheld report, never a raw C5."""
    projection = envelope.get("report")
    if (
        envelope.get("submission_id") != str(submission_id)
        or not isinstance(projection, dict)
        or projection.get("access") != "claimed_account"
        or not isinstance(projection.get("content"), dict)
    ):
        raise ValueError("An authorized account report is required.")
    report = projection["content"]
    call = from_report(
        envelope,
        submission_id=submission_id,
        created_at=created_at,
        comparison_key=f"call:{submission_id}",
    )
    row = next((s for s in call.skills if s.mission), None) if call else None
    evidence: tuple[Moment, ...] = ()
    label, explanation, why, skill_id = "", "", "", "report_next_step"
    mission, practice = None, None
    basis: Literal["skill_evidence", "report_suggestion", "general_practice", "unavailable"] = (
        "general_practice"
    )
    if row:
        label, explanation = row.label, row.improvement or row.observation
        why = row.why_it_matters or row.observation
        evidence, mission, practice = row.evidence[:4], row.mission, row.practice
        skill_id, basis = row.skill_id, row.basis
    else:
        # A clean call, missing overview or missing timestamp field is still a
        # useful lesson. Use a retained finding; do not invent its assessed skill.
        for section in ("improvements", "missed_opportunities", "strengths"):
            findings = report.get(section)
            if not isinstance(findings, list):
                continue
            for finding in findings:
                if not isinstance(finding, dict) or WITHHELD_MARKER in str(finding):
                    continue
                title, text = (
                    _text(finding.get("title"), 240),
                    _text(finding.get("explanation"), 4000),
                )
                if title and text:
                    label, explanation, why = title, text, text
                    evidence = _moments(
                        envelope, _refs(finding.get("evidence")), text, submission_id, created_at
                    )[:4]
                    basis = "report_suggestion"
                    break
            if label:
                break
        if not label and call and call.skills:
            observed = call.skills[0]
            label, explanation, why = observed.label, observed.observation, observed.observation
            evidence, skill_id, basis = observed.evidence[:4], observed.skill_id, "skill_evidence"

    common = dict(
        person_id=person_id,
        tenant_id=tenant_id,
        submission_id=submission_id,
        recording_id=envelope["recording_id"],
        source_sha256=envelope["source_sha256"],
        transcript_revision=envelope["transcript_revision"],
        report_revision=content_hash(projection),
        call_label=_text(envelope.get("source_label"), 256) or "Sales call",
    )
    if not label and WITHHELD_MARKER in str(report):
        return CallCoachingView(
            **common,
            state="unavailable",
            basis="unavailable",
            focus=None,
            evidence=(),
            lesson=None,
            practice=None,
            mission=None,
            limitations=(
                "This call's coaching evidence is withheld. "
                "Open the call for available information.",
            ),
        )
    if not label:
        label = "Make the next step clear"
        explanation = (
            "This report has no retained coaching recommendation. "
            "Start with one small practice for your next call."
        )
        why = "A clear, agreed next step helps both people understand what happens after the call."
    if mission is None:
        mission = Mission(
            skill_id=skill_id,
            behavior=(
                "Practise one alternative response to the report's observation in your own words, "
                "then try it in one comparable moment on your next call."
                if basis != "general_practice"
                else "Before ending your next call, confirm the agreed next step "
                "and who will do what."
            ),
            context=f"When a comparable situation relates to: {label}"
            if basis != "general_practice"
            else "When the conversation is ending and a next step is relevant.",
            done_when=(
                "Retain one moment where you tried the behavior so you can review what happened."
            ),
            cue="One useful change. Check the situation. Keep your own words.",
            active_since=created_at,
            origin_submission_id=submission_id,
        )
    return CallCoachingView(
        **common,
        state="ready",
        basis=basis,
        focus=Focus(
            skill_id=skill_id,
            label=label,
            explanation=explanation,
            why_it_matters=why,
            selected_reason=(
                "Selected from this call's retained report. "
                "Your across-call mission stays unchanged."
                if basis != "general_practice"
                else "General practice from approved guidance; "
                "no assessed weakness is inferred from this call."
            ),
            selected_at=created_at,
            status="provisional",
            verdict=mission.behavior,
        ),
        evidence=evidence,
        lesson=lesson_for(skill_id, evidence[0] if evidence else None, mission),
        practice=practice
        or Practice(
            exercise="Review the call in context. Say one useful response aloud in your own words.",
            success_condition=mission.done_when,
        ),
        mission=mission,
        limitations=(
            "This coaching is specific to one call; "
            "it does not establish a recurring pattern or mastery.",
            "The call suggestion stays linked to this report. "
            "It does not replace your across-call mission.",
            "A relevant reviewed Dipak clip is not available yet; use the structured text lesson.",
        ),
    )


class CallCoachingCache:
    """Bounded process memory, AFTER current source access/withholding checks.

    No response/CDN cache and no database writes. Changed report or withholding
    payloads use a different key; the cached result cannot authorize a read.
    """

    def __init__(self, *, capacity: int = 128, ttl_seconds: float = 120) -> None:
        self.capacity, self.ttl_seconds = capacity, ttl_seconds
        self._entries: OrderedDict[str, tuple[float, CallCoachingView]] = OrderedDict()

    def read(
        self,
        envelope: dict[str, Any],
        *,
        submission_id: UUID,
        created_at: datetime,
        person_id: UUID,
        tenant_id: UUID,
    ) -> CallCoachingView:
        key = content_hash(
            [str(person_id), str(tenant_id), str(submission_id), created_at.isoformat(), envelope]
        )
        now = monotonic()
        for stale in [k for k, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[stale]
        cached = self._entries.get(key)
        if cached:
            self._entries.move_to_end(key)
            return cached[1]
        view = build_call_coaching(
            envelope,
            submission_id=submission_id,
            created_at=created_at,
            person_id=person_id,
            tenant_id=tenant_id,
        )
        self._entries[key] = (now + self.ttl_seconds, view)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
        return view
