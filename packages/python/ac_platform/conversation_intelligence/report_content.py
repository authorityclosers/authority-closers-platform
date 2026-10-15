"""Offline C5 Report candidate; source binding grants no scoring/runtime authority."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ac_platform.conversation_intelligence.report_overview import OverviewEvidence
from ac_platform.conversation_intelligence.speaker_roles import validate_speaker_roles

REPORT_C5_REVISION = "report-c5-v1"
SPEC_SHA256 = "a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110"
Outcome = Literal[
    "Won",
    "Lost",
    "Follow-up Set",
    "Decision Pending",
    "Deferred",
    "Meeting Booked",
    "Disqualified",
    "No Clear Next Step",
    "Still Open",
]

REPORT_INSTRUCTION = (
    "REPORT_CONTENT: report-content/1; offline candidate report-c5-v1. Determine call purpose "
    "first (setter, discovery, closing, client_review), judge only that purpose; no closing "
    "penalty for a setter/discovery/client review. Return report_content in addition to the "
    "unchanged Coaching fields. Report is what happened, never a coaching lesson. Summary is "
    "3-5 short sentences (summary_sentences); cover what worked, what weakened and the ending. "
    "Each note has actor_id and evidence:[{segment_id}]; cite that person's own complete turns, "
    "in time order. Use names only from the supplied speaker map, otherwise neutral labels, "
    "and use the reader's language/script. Never cut quotes or emit offsets/times. Facts do not "
    "assert emotion, intent or causation. Titles describe events, not instructions. "
    "Outcome uses exactly Won, Lost, Follow-up Set, Decision Pending, Deferred, Meeting Booked, "
    "Disqualified, No Clear Next Step, Still Open. This is a call observation, never a saved "
    "deal result; ambiguous facts are null. Biggest influence is one supported observation. "
    "Strongest part/concern have their own turns. Phases follow the actual call, including "
    "returns to discovery; turning_point has before/turn/after, not an invented textbook arc. "
    "Separate prospect/seller commitments from assigned tasks; cite each person's own agreement. "
    "next_event is null unless both parties agreed; preserve literal relative date/time, "
    "null if absent. Clear commitment_quality requires agreed action plus date and time; "
    "Soft means action without firm timing; Unclear means no reliable next step. "
    "unknowns are unanswered buyer questions, action is deal-specific, never skill coaching. "
    "Dimensions explicitly emit call_state: strongly_demonstrated, observed, needs_attention, "
    "insufficient_evidence, not_applicable. No default observed: state and observation must "
    "agree; supported states cite the seller's own turns with status observed, other states "
    "preserve absent/irrelevant evidence without a performance judgment. Missed chances are "
    "0-N: opening is a genuine prospect turn, response_opportunity is a later seller turn, "
    "relevance explains the call-specific reason it mattered with evidence. All three are "
    "required; no quotas, generic hypothetical questions or v5 missed_details conversion. "
    "Use report_content schema. New summary must equal joined summary_sentences.text."
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Note(_Strict):
    text: str = Field(min_length=1, max_length=1200)
    actor_id: str = Field(min_length=1, max_length=256)
    evidence: list[OverviewEvidence] = Field(min_length=1, max_length=3)


class Purpose(Note):
    kind: Literal["setter", "discovery", "closing", "client_review"]


class CallOutcome(Note):
    status: Outcome


class Finding(_Strict):
    title: str = Field(min_length=1, max_length=160)
    observation: Note
    effect: Note | None


class Moment(Finding):
    kind: Literal[
        "Strong Moment",
        "Turning Point",
        "Buying Signal",
        "Objection",
        "Price Moment",
        "Decision Moment",
        "Trust Moment",
        "Commitment",
        "Risk",
    ]


class Miss(_Strict):
    title: str = Field(min_length=1, max_length=160)
    opening: Note
    response_opportunity: Note
    relevance: Note


class Turn(_Strict):
    before: Note
    turn: Note
    after: Note


class Event(_Strict):
    observation: Note
    date_text: str | None = Field(max_length=120)
    time_text: str | None = Field(max_length=120)
    agreement_evidence: list[OverviewEvidence] = Field(min_length=2, max_length=4)


class ReportContent(_Strict):
    version: Literal["report-content/1"]
    # Server-bound attribution retained for canonical reads, never provider role inference.
    roles: dict[str, Literal["seller", "prospect", "other"]]
    purpose: Purpose | None
    outcome: CallOutcome | None
    summary_sentences: list[Note] = Field(min_length=3, max_length=5)
    influence: Note | None
    strongest: Note | None
    concern: Note | None
    next_step: Note | None
    phases: list[Note] = Field(max_length=12)
    turning_point: Turn | None
    worked: list[Finding] = Field(max_length=5)
    didnt: list[Finding] = Field(max_length=3)
    moments: list[Moment] = Field(max_length=12)
    missed_chances: list[Miss] = Field(max_length=10)
    position: Note | None
    blocker: Note | None
    prospect_commitments: list[Note] = Field(max_length=8)
    seller_commitments: list[Note] = Field(max_length=8)
    next_event: Event | None
    commitment_quality: Literal["Clear", "Soft", "Unclear"] | None
    unknowns: list[Note] = Field(max_length=8)
    action: Note | None


def report_content_schema() -> dict[str, Any]:
    """Direct whole-turn selectors only; timing/quote/roles are resolved locally."""
    schema: dict[str, Any] = deepcopy(ReportContent.model_json_schema())
    schema["properties"].pop("roles")
    schema["required"].remove("roles")

    def wire(node: Any, *, named_map: bool = False) -> Any:
        if isinstance(node, dict):
            # properties/$defs keys are data names, not schema annotations.
            result = {
                key: wire(v, named_map=key in {"properties", "$defs"})
                for key, v in node.items()
                if named_map or key != "title"
            }
            if "const" in result:
                result["enum"] = [result.pop("const")]
            return result
        if isinstance(node, list):
            return [wire(v) for v in node]
        return node

    schema = wire(schema)
    schema["$defs"]["OverviewEvidence"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"segment_id": {"type": "string"}},
        "required": ["segment_id"],
    }
    return schema


def bind_report_content(
    value: Any,
    transcript: Mapping[str, Any],
    *,
    speaker_roles: Mapping[str, Any] | None,
    canonical_read: bool = False,
) -> ReportContent:
    """Reject wrong actors, truncated quotes, unordered refs and unproved agreements."""
    if not isinstance(value, dict):
        raise ValueError("report_content_invalid")
    if canonical_read:
        roles = value.get("roles")
    else:
        if speaker_roles is None or "roles" in value:
            raise ValueError("report_content_roles_required")
        snapshot = validate_speaker_roles(speaker_roles, transcript)
        roles = {row["speaker_id"]: row["role"] for row in snapshot["speakers"]}
    segments = {row["id"]: row for row in transcript["segments"]}
    known = {row["speaker_id"] for row in segments.values()}
    if not isinstance(roles, dict) or not set(roles) <= known:
        raise ValueError("report_content_roles_invalid")

    def evidence(refs: Any, actor: str | None = None) -> list[dict[str, Any]]:
        if not isinstance(refs, list):
            raise ValueError("report_content_evidence_invalid")
        bound = []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("report_content_evidence_invalid")
            row = segments.get(ref.get("segment_id"))
            if row is None or (actor is not None and row["speaker_id"] != actor):
                raise ValueError("report_content_actor_mismatch")
            full = {
                "segment_id": row["id"],
                "quote": row["text"],
                "start_ms": row["start_ms"],
                "end_ms": row["end_ms"],
            }
            if (not canonical_read and set(ref) != {"segment_id"}) or (
                canonical_read and ref != full
            ):
                raise ValueError("report_content_complete_turn_required")
            bound.append(full)
        keys = [(row["start_ms"], row["segment_id"]) for row in bound]
        if len(set(keys)) != len(keys) or keys != sorted(keys):
            raise ValueError("report_content_evidence_order")
        return bound

    def visit(node: Any) -> Any:
        if isinstance(node, list):
            return [visit(child) for child in node]
        if not isinstance(node, dict):
            return node
        result = {
            key: visit(child)
            for key, child in node.items()
            if key not in {"evidence", "agreement_evidence"}
        }
        if "evidence" in node:
            actor = node.get("actor_id")
            if not isinstance(actor, str) or actor not in roles:
                raise ValueError("report_content_actor_required")
            result["evidence"] = evidence(node["evidence"], actor)
        if "agreement_evidence" in node:
            result["agreement_evidence"] = evidence(node["agreement_evidence"])
        return result

    content = ReportContent.model_validate({**visit(value), "roles": roles})
    for notes, role in [
        (content.prospect_commitments, "prospect"),
        (content.seller_commitments, "seller"),
    ]:
        if any(roles[n.actor_id] != role for n in notes):
            raise ValueError("report_content_commitment_role")
    if any(roles[n.observation.actor_id] != "seller" for n in content.worked + content.didnt):
        raise ValueError("report_content_finding_role")
    for miss in content.missed_chances:
        if (
            roles[miss.opening.actor_id] != "prospect"
            or roles[miss.response_opportunity.actor_id] != "seller"
            or miss.response_opportunity.evidence[0].start_ms < miss.opening.evidence[-1].end_ms
        ):
            raise ValueError("report_content_missed_chance_gate")
    for notes in [
        content.phases,
        [m.observation for m in content.moments],
        [m.opening for m in content.missed_chances],
    ]:
        times = [n.evidence[0].start_ms for n in notes]
        if times != sorted(set(times)):
            raise ValueError("report_content_timeline_order")
    if content.turning_point:
        t = content.turning_point
        if not (
            t.before.evidence[-1].end_ms <= t.turn.evidence[0].start_ms
            and t.turn.evidence[-1].end_ms <= t.after.evidence[0].start_ms
        ):
            raise ValueError("report_content_turn_order")
    event = content.next_event
    if event:
        participants = {
            roles.get(segments[e.segment_id]["speaker_id"]) for e in event.agreement_evidence
        }
        quotes = " ".join(e.quote for e in event.agreement_evidence).casefold()
        if not {"seller", "prospect"} <= participants or any(
            text is not None and (not text.strip() or text.casefold() not in quotes)
            for text in [event.date_text, event.time_text]
        ):
            raise ValueError("report_content_event_unconfirmed")
    if content.commitment_quality == "Clear" and (
        event is None or not event.date_text or not event.time_text
    ):
        raise ValueError("report_content_commitment_quality")
    return content
