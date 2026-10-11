"""Compact, source-bound six-pillar Report; no score or canonical deal write.

V8 generates this once. Legacy findings project the same validated content.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ac_platform.conversation_intelligence.speaker_roles import validate_speaker_roles

COACHING_PROMPT_V8_MARKER = "REPORT_STRUCTURE: dipak-six-pillars-v8."
REPORT_SPEC_SHA256 = "a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110"
REPORT_SECTION_FIELDS = {
    "1.1": "pillars.outcome",
    "1.2": "pillars.summary + summary_evidence",
    "1.3": "pillars.biggest_influence",
    "1.4": "pillars.strongest_part",
    "1.5": "pillars.biggest_concern",
    "1.6": "pillars.next_step",
    "2.1": "C2 measured metrics (server/browser calculation; never model numbers)",
    "2.2": "pillars.timeline",
    "2.3": "pillars.key_change",
    "2.4": "pillars.key_change.before + after",
    "3.1": "pillars.worked",
    "3.2": "pillars.didnt",
    "4": "pillars.moments",
    "5": "dimensions[].call_state + observation + evidence (eight controlled domains)",
    "5.deep": "pillars.deeper",
    "5.discovery": "pillars.deeper.became_clear + still_unclear + opening_missed",
    "5.presentation": "pillars.deeper.relevant + less_relevant + value_connection",
    "5.decision": "pillars.deeper.price + prospect_response + likely_status",
    "5.communication": "pillars.deeper.listening + communication_note; C2 measured monologue",
    "6.1": "pillars.outcome",
    "6.2": "pillars.deal.position",
    "6.3": "pillars.deal.blocker",
    "6.4": "pillars.deal.prospect_commitments",
    "6.5": "pillars.deal.seller_commitments",
    "6.6": "pillars.deal.next_event",
    "6.7": "pillars.deal.commitment_quality",
    "6.8": "pillars.deal.still_unclear",
    "6.9": "pillars.deal.deal_action (suggestion, separate from coaching_mission)",
}
COACHING_PROMPT_V8_INSTRUCTION = (
    "Return one compact JSON object: pillars (report-pillars/1), summary_evidence, "
    "dimensions (all eight controlled IDs), sensitive_segments, review_status. "
    "Do not repeat content in summary/findings/overview/call_map: the server projects legacy "
    "fields. All evidence selectors are direct {segment_id}; never supply quotation text, "
    "timestamps, numeric evaluation or invented provenance. The server supplies quotes and "
    "timing. Bounds are maxima, never quotas; null and empty lists are honest. "
    "THE BIG PICTURE: outcome has one status, line and evidence, or null when unestablished. "
    "Use Follow-up Set, Decision Pending, Deferred, Meeting Booked, Disqualified, No Clear "
    "Next Step or Still Open; Won/Lost are recorded by a person elsewhere. summary is 3-5 "
    "short everyday sentences: conclusion, what was understood, what changed, what helped, "
    "what hurt, where the call ended. Outcome line and summary have different openings: "
    "never repeat their first five words or add a second overall-verdict paragraph. "
    "The outcome line states only where the call ended; the summary explains the "
    "conversation and its changes. Cite its 1-3 source segments in summary_evidence. "
    "biggest_influence is the ONE biggest influence, positive or negative. strongest_part "
    "and biggest_concern have one short observation, evidence and a <=8-word short label, "
    "or null. next_step is an explicitly agreed action with literal spoken when or null. "
    "HOW THE CALL PLAYED OUT: timeline has plain call-specific labels, such as Business "
    "Context or Price & Decision, with native start_ms from a cited segment. Follow what "
    "actually happened, including returns to discovery; never force a funnel. key_change "
    "is the ONE important switch with evidence and short before/after label+summary+"
    "evidence, or null. Before/after describe the conversation; do not paste quotations "
    "as summaries. Metrics are measured from C2 elsewhere, never model numbers. Talk share "
    "and long turns alone are not weaknesses. Do not infer vocal tone, boredom or emotion "
    "from text. WHAT WORKED AND WHAT DIDN'T: up to 3 supported worked cards (title,what,"
    "evidence,why_it_helped) and 3 didnt cards (title,what,evidence,what_it_affected,"
    "possible_areas). Rank by impact. Judge this conversation, never the person's "
    "character, mastery or history. Each observation cites its own 1-2 segments. "
    "Explain effects briefly; full lessons belong in Coaching. MOMENTS THAT MATTERED: "
    "choose 3-5 distinct useful replays when supported, fewer for short/sparse calls. "
    "Use listed kind labels, title, evidence and why. Important Miss requires a genuine "
    "prospect opening AND the seller's actual chance/response (cite both), moved_toward, "
    "what_was_missed and why it mattered. No generic missing textbook question. "
    "An implementation question is a possible Buying Signal, never a purchase commitment. "
    "price_stated and prospect_response, if present, are exact source phrases in evidence. "
    "YOUR SKILLS ON THIS CALL: all eight domains with status, observation, evidence and "
    "call_state. strongly_demonstrated/observed/needs_attention require observed status and "
    "two distinct source segments. Missing opportunities are not_applicable, never a "
    "weakness; partial/uncertain/conflicting support is insufficient_evidence. No grades, "
    "scores, percentages, mastery or fabricated certainty. deeper is optional: evidence-"
    "backed became_clear/relevant notes, open still_unclear questions, opening_missed, "
    "less_relevant, value_connection (state+evidence), price, prospect_response, tentative "
    "likely_status possibilities, listening and communication_note. Keep possibilities "
    "tentative, not asserted causes. All populated notes/states cite their evidence. "
    "No full Prospect "
    "profile or longitudinal Coaching here. WHERE THE DEAL STANDS: deal has position, "
    "blocker (basis said/inferred), prospect_commitments, seller_commitments, next_event, "
    "commitment_quality, still_unclear questions, deal_action and coaching_mission. "
    "A partner discussion is not automatically a price objection, rejection or blocking "
    "partner. A stated possibility is not acceptance. Prospect commitments cite the "
    "prospect's own frozen-role segments; seller commitments cite seller segments. Assigned "
    "tasks and suggestions are not commitments. Missing roles: abstain from commitments. "
    "Clear requires an agreed specific next event with literal stated timing; Soft means "
    "an agreed action without firm timing; Unclear means no reliable agreement. next_event "
    "and next_step when must occur literally in their cited segments; never invent a date, "
    "combine separate words or convert relative dates. deal_action is one suggested "
    "opportunity follow-up, separate from the one-line coaching_mission (skill practice). "
    "most_important_moment is an index into moments or null. Use only frozen "
    "source_context.speaker_roles, never output-inferred roles or browser state. Address "
    "the account holder as you only from is_account_holder; other seller is salesperson. "
    "Predicted roles stay predicted; no voice identity or speaker-label prose. Say simply "
    "'You explained the offer before finding the cause', never 'moderately successful "
    "consultative interaction'. No example names, prices or dates from the spec. "
    "sensitive_segments has only segment_id and SENSITIVE_FINANCIAL/SENSITIVE_LEGAL, "
    "unique pairs, no quoted text; legal-exposure material only, not ordinary business figures. "
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Text = Annotated[str, Field(min_length=1, max_length=150)]
Short = Annotated[str, Field(min_length=1, max_length=48)]
Question = Annotated[str, Field(min_length=1, max_length=120)]


class PillarEvidence(_Model):
    segment_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=2000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


Refs = Annotated[list[PillarEvidence], Field(min_length=1, max_length=2)]


class PillarNote(_Model):
    text: Text
    evidence: Refs


class PillarHighlight(PillarNote):
    short: Short


class PillarNextStep(PillarNote):
    when: Annotated[str, Field(min_length=1, max_length=60)] | None


class PillarOutcome(_Model):
    status: Literal[
        "Follow-up Set",
        "Decision Pending",
        "Deferred",
        "Meeting Booked",
        "Disqualified",
        "No Clear Next Step",
        "Still Open",
    ]
    line: Text
    evidence: Refs


class PillarPhase(_Model):
    label: Short
    start_ms: int = Field(ge=0, le=2147483647)
    evidence: Annotated[list[PillarEvidence], Field(min_length=1, max_length=1)]


class PillarChangePart(PillarNote):
    label: Short


class PillarChange(PillarNote):
    before: PillarChangePart
    after: PillarChangePart


class PillarWorked(_Model):
    title: Short
    what: Text
    evidence: Refs
    why_it_helped: Text


class PillarIssue(_Model):
    title: Short
    what: Text
    evidence: Refs
    what_it_affected: Text
    possible_areas: list[Question] = Field(max_length=3)


class PillarMoment(_Model):
    kind: Literal[
        "Strong Moment",
        "Turning Point",
        "Buying Signal",
        "Important Miss",
        "Objection",
        "Price Moment",
        "Decision Moment",
        "Trust Moment",
        "Commitment",
        "Risk",
    ]
    title: Short
    evidence: Refs
    why: Text
    moved_toward: Text | None
    what_was_missed: Text | None
    price_stated: Short | None
    prospect_response: Text | None


class PillarBlocker(PillarNote):
    basis: Literal["said", "inferred"]


class PillarDeal(_Model):
    position: PillarNote | None
    blocker: PillarBlocker | None
    prospect_commitments: list[PillarNote] = Field(max_length=2)
    seller_commitments: list[PillarNote] = Field(max_length=2)
    next_event: PillarNextStep | None
    commitment_quality: Literal["Clear", "Soft", "Unclear"]
    still_unclear: list[Question] = Field(max_length=4)
    deal_action: Text | None
    coaching_mission: Text | None


class PillarValueConnection(_Model):
    state: Literal["Established", "Partially established", "Not established"]
    evidence: Refs


class PillarDeeper(_Model):
    became_clear: list[PillarNote] = Field(max_length=2)
    still_unclear: list[Question] = Field(max_length=4)
    opening_missed: PillarNote | None
    relevant: list[PillarNote] = Field(max_length=2)
    less_relevant: PillarNote | None
    value_connection: PillarValueConnection | None
    price: PillarNote | None
    prospect_response: PillarNote | None
    likely_status: list[PillarNote] = Field(max_length=2)
    listening: PillarNote | None
    communication_note: PillarNote | None


class ReportPillars(_Model):
    version: Literal["report-pillars/1"]
    outcome: PillarOutcome | None
    summary: str = Field(min_length=1, max_length=600)
    biggest_influence: PillarNote | None
    strongest_part: PillarHighlight | None
    biggest_concern: PillarHighlight | None
    next_step: PillarNextStep | None
    timeline: list[PillarPhase] = Field(max_length=8)
    key_change: PillarChange | None
    worked: list[PillarWorked] = Field(max_length=3)
    didnt: list[PillarIssue] = Field(max_length=3)
    moments: list[PillarMoment] = Field(max_length=5)
    deeper: PillarDeeper | None
    deal: PillarDeal | None
    most_important_moment: int | None = Field(ge=0, le=4)

    @model_validator(mode="after")
    def source_order(self) -> ReportPillars:
        if self.outcome:
            outcome_words = re.findall(r"\w+", self.outcome.line.casefold())
            summary_words = re.findall(r"\w+", self.summary.casefold())
            if outcome_words == summary_words or (
                len(outcome_words) >= 5
                and len(summary_words) >= 5
                and outcome_words[:5] == summary_words[:5]
            ):
                raise ValueError("report_pillars_duplicate_opening")
        if self.most_important_moment is not None and self.most_important_moment >= len(
            self.moments
        ):
            raise ValueError("report_pillars_moment_invalid")
        if any(
            len(item.short.split()) > 8
            for item in (self.strongest_part, self.biggest_concern)
            if item
        ):
            raise ValueError("report_pillars_short_invalid")
        if any(
            a.start_ms >= b.start_ms for a, b in zip(self.timeline, self.timeline[1:], strict=False)
        ):
            raise ValueError("report_pillars_timeline_invalid")
        return self


def normalize_pillars(
    value: object,
    *,
    transcript: Mapping[str, Any],
    speaker_roles: Mapping[str, Any] | None,
    normalize_evidence: Callable[[Any], dict[str, Any]],
    canonical_read: bool,
) -> ReportPillars:
    """Resolve every selector before accepting content; protect role/timing claims."""

    def resolve(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {
                key: (
                    [normalize_evidence(ref) for ref in child]
                    if key == "evidence" and isinstance(child, list)
                    else resolve(child)
                )
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [resolve(child) for child in item]
        return item

    pillars = ReportPillars.model_validate(resolve(value))
    segments = {s["id"]: s for s in transcript["segments"]}
    roles = (
        {
            s["speaker_id"]: s["role"]
            for s in validate_speaker_roles(speaker_roles, transcript)["speakers"]
        }
        if speaker_roles
        else {}
    )
    if any(
        phase.start_ms != phase.evidence[0].start_ms or phase.start_ms >= transcript["duration_ms"]
        for phase in pillars.timeline
    ):
        raise ValueError("report_pillars_timeline_invalid")
    if pillars.key_change:
        change = pillars.key_change
        if max(e.end_ms for e in change.before.evidence) > min(
            e.start_ms for e in change.evidence
        ) or max(e.end_ms for e in change.evidence) > min(
            e.start_ms for e in change.after.evidence
        ):
            raise ValueError("report_pillars_change_invalid")
    for step in (pillars.next_step, pillars.deal.next_event if pillars.deal else None):
        if step and step.when and not any(step.when in e.quote for e in step.evidence):
            raise ValueError("report_pillars_timing_invalid")
    for moment in pillars.moments:
        if moment.kind == "Important Miss":
            if not moment.moved_toward or not moment.what_was_missed:
                raise ValueError("report_pillars_miss_invalid")
            if not canonical_read and {
                roles.get(segments[e.segment_id]["speaker_id"]) for e in moment.evidence
            } != {"seller", "prospect"}:
                raise ValueError("report_pillars_miss_role_invalid")
        for quoted in (moment.price_stated, moment.prospect_response):
            if quoted and not any(quoted in ref.quote for ref in moment.evidence):
                raise ValueError("report_pillars_quote_invalid")
    if pillars.deal:
        deal = pillars.deal
        if deal.commitment_quality != "Unclear" and deal.next_event is None:
            raise ValueError("report_pillars_agreement_required")
        if deal.commitment_quality == "Clear" and deal.next_event and deal.next_event.when is None:
            raise ValueError("report_pillars_timing_required")
        if not canonical_read:
            for expected, commitments in (
                ("prospect", deal.prospect_commitments),
                ("seller", deal.seller_commitments),
            ):
                if any(
                    roles.get(segments[e.segment_id]["speaker_id"]) != expected
                    for note in commitments
                    for e in note.evidence
                ):
                    raise ValueError("report_pillars_commitment_role_invalid")
    return pillars


def legacy_pillars_payload(pillars: ReportPillars, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility content is copied from validated fields, never re-generated."""

    def finding(item: PillarWorked | PillarIssue) -> dict[str, Any]:
        return {
            "title": item.title,
            "explanation": item.what,
            "evidence": [e.model_dump(mode="json") for e in item.evidence],
        }

    outcome = pillars.outcome
    return {
        "summary": pillars.summary,
        "summary_evidence": raw.get("summary_evidence"),
        "strengths": [finding(item) for item in pillars.worked],
        "improvements": [finding(item) for item in pillars.didnt],
        "missed_opportunities": [
            {
                "title": m.title,
                "explanation": m.what_was_missed,
                "evidence": [e.model_dump(mode="json") for e in m.evidence],
            }
            for m in pillars.moments
            if m.kind == "Important Miss"
        ],
        "objection_analysis": [
            {
                "title": m.title,
                "explanation": m.why,
                "evidence": [e.model_dump(mode="json") for e in m.evidence],
            }
            for m in pillars.moments
            if m.kind == "Objection"
        ],
        "closing_analysis": [],
        "verdict": outcome.line if outcome else pillars.summary,
        "verdict_evidence": [e.model_dump(mode="json") for e in outcome.evidence]
        if outcome
        else raw.get("summary_evidence"),
        "dimensions": raw.get("dimensions"),
        "review_status": raw.get("review_status"),
        "pillars": pillars.model_dump(mode="json"),
        "sensitive_segments": raw.get("sensitive_segments", []),
    }


def project_pillars(pillars: ReportPillars) -> dict[str, Any]:
    """B's optional public contract; internal grounding stays in the saved C5."""
    result = pillars.model_dump(mode="json")
    for phase in result["timeline"]:
        phase.pop("evidence")
    if result["key_change"]:
        for field in ("before", "after"):
            result["key_change"][field].pop("evidence")
    if result["deeper"]:
        deeper = result["deeper"]
        for field in ("became_clear", "relevant", "likely_status"):
            deeper[field] = [note["text"] for note in deeper[field]]
        for field in ("less_relevant", "listening"):
            deeper[field] = deeper[field]["text"] if deeper[field] else None
        deeper["value_connection"] = (
            deeper["value_connection"]["state"] if deeper["value_connection"] else None
        )
    return result
