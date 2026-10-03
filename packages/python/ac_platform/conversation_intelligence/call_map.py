"""Pure Python twin of the Sales Xray `call-map/1` contract (AUT-341 plan §3.2).

The web parser is `apps/sales-xray-web/app/call-map-contract.ts`; both sides use
the same failure-code strings. Nothing here judges with a number: every field is
a reading backed by quotes (AGENTS.md, AC-SVAL). Prompt text, storage and the
repair allowlists live in later tasks (B2, B3).

Role rules (AUT-416 plan §3 and the AUT-341 decision brief): seller tasks,
claims and an objection's reply cite a `seller` segment; objection evidence and
prospect facts cite a `prospect` segment. A reply starts at or after the first
evidence segment of its objection and is required unless the objection was
`ignored`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from ac_platform.conversation_intelligence.call_metrics import (
    TranscriptSegment,
    compute_call_metrics,
)
from ac_platform.conversation_intelligence.report_claims import require_qualitative_claims

CALL_MAP_VERSION: Final = "call-map/1"
CALL_MAP_FAILURE_CODES: Final = (
    "call_map_invalid",
    "call_map_evidence_unresolved",
    "call_map_time_out_of_range",
    "call_map_phase_order_invalid",
    "call_map_reference_unknown",
    "call_map_role_mismatch",
    "call_map_qualification_invalid",
    "call_map_word_cap_exceeded",
    "call_map_signal_kind_unknown",
    "call_map_money_invalid",
    "report_speaker_label_leak",
    "ethics_unverifiable_claim_missing",
)
SIGNALS_PATH: Final = Path(__file__).with_name("profiles") / "call_signals_v1.json"
_SIGNALS: Final[dict[str, Any]] = json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))
SIGNAL_KINDS_V1: Final[dict[str, tuple[str, ...]]] = {
    polarity: tuple(_SIGNALS[polarity]) for polarity in ("forward", "risk")
}
OBJECTION_KINDS_V1: Final[tuple[str, ...]] = tuple(_SIGNALS["objection_kinds"])
QUALIFICATION_ITEMS: Final = ("budget", "timeline", "decision_maker", "authority", "need")
PROMISE_MS: Final = (60_000, 14_400_000)
_UNIT_CHARS: Final = 12

# Verdicts are readings, never judgements by number (AGENTS.md, AC-SVAL).
_NUMBER = (
    r"(?:\d+(?:\.\d+)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"fifteen|twenty|thirty|forty|fifty|hundred)"
)
_SCORE_PROSE: Final = re.compile(
    r"\b(?:scor\w*|grad(?:e|es|ed|ing)|rat(?:ing|ings|ed)|percent\w*)\b"
    r"|\d\s*%"
    r"|\bout\s+of\s+(?:\d+|five|ten|hundred)\b"
    rf"|\b{_NUMBER}\s*(?:points?|stars?|marks?)\b"
    r"|\d\s+/\s*\d|\d\s*/\s+\d",
    re.IGNORECASE,
)
_FRACTION: Final = re.compile(r"\d+/\d+(?:/\d+)?")
# Plain day/month dates stay valid: `dated_call` verdicts use them.
_DATE: Final = re.compile(r"^(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])(?:/\d{2,4})?$")
_SPEAKER_LABEL: Final = re.compile(r"\b(?i:speaker|spk)[\s_-]*(?:\d+|[A-Z])\b")

Role = Literal["seller", "prospect", "other"]
Qualification = Literal["budget", "timeline", "decision_maker", "authority", "need"]
DimensionState = Literal[
    "observed", "partial", "insufficient_evidence", "not_applicable", "conflicted", "unknown"
]
Text = Annotated[StrictStr, Field(min_length=1, max_length=400, pattern=r"\S")]
Count = Annotated[int, Field(ge=0)]
Amount = Annotated[float, Field(allow_inf_nan=False)]
PitchId = Annotated[StrictStr, Field(pattern=r"^pi[1-9]\d*$")]
PainId = Annotated[StrictStr, Field(pattern=r"^pn[1-9]\d*$")]
ClaimId = Annotated[StrictStr, Field(pattern=r"^cl[1-9]\d*$")]
SellerTaskId = Annotated[StrictStr, Field(pattern=r"^st[1-9]\d*$")]
ObjectionId = Annotated[StrictStr, Field(pattern=r"^ob[1-9]\d*$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceRef(_Model):
    segment_id: Text
    quote: Text


class Speaker(_Model):
    speaker_id: Text
    role: Role


class Phase(_Model):
    name: Literal["opening", "discovery", "pitch", "objection", "close"]
    start_ms: Count


class TimePromise(_Model):
    promised_ms: Count
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=1)


class Outcome(_Model):
    kind: Literal["won", "lost", "follow_up", "disqualified", "none"]
    next_step_rung: Literal["none", "vague", "dated_call", "invite_sent", "committed"]
    next_step_when: Text | None
    evidence: list[EvidenceRef] = Field(max_length=2)


class CallPurpose(_Model):
    kind: Literal["sales", "support", "onboarding", "internal", "personal", "unclear"]
    evidence: list[EvidenceRef] = Field(max_length=1)


class Signal(_Model):
    polarity: Literal["forward", "risk"]
    kind: Text
    text: Text
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=2)


class PitchItem(_Model):
    id: PitchId
    text: Text
    start_ms: Count
    end_ms: Count
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=2)


class Pain(_Model):
    id: PainId
    text: Text
    raised_by: Text
    times: Annotated[int, Field(ge=1)]
    prospect_intensity: Literal["low", "med", "high"]
    addressed_by: Text | None
    answer_fit: Literal["specific", "generic", "none"]
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=3)


class Money(_Model):
    label: Text
    value_min: Amount
    value_max: Amount
    unit: Text
    period: Literal["once", "day", "week", "month", "year"] | None
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=1)


class Claim(_Model):
    id: ClaimId
    text: Text
    verifiable: Literal["yes", "no", "unclear"]
    seller_error: Literal["factual", "term"] | None
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=2)


class QualificationConfirmed(_Model):
    item: Qualification
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=2)


class ProspectTask(_Model):
    text: Text
    effort_ms: Count | None
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=1)


class SellerTask(_Model):
    id: SellerTaskId
    text: Text
    due_text: Text | None
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=1)


class Objection(_Model):
    id: ObjectionId
    kind: Text
    text: Text
    handling: Literal["answered", "deflected", "ignored", "question_back"]
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=2)
    reply: list[EvidenceRef] = Field(max_length=1)


class ProspectFact(_Model):
    key: Literal["industry", "team_size", "company", "role"]
    text: Text
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=1)


class CallMap(_Model):
    """Strict `call-map/1`; unknown keys and loose types are `call_map_invalid`."""

    version: Literal["call-map/1"]
    verdict_line: Text
    call_purpose: CallPurpose
    speakers: list[Speaker] = Field(min_length=1, max_length=16)
    phases: list[Phase] = Field(min_length=1, max_length=8)
    time_promise: TimePromise | None
    outcome: Outcome
    signals: list[Signal] = Field(max_length=8)
    pitch_items: list[PitchItem] = Field(max_length=8)
    pains: list[Pain] = Field(max_length=6)
    money: list[Money] = Field(max_length=8)
    claims: list[Claim] = Field(max_length=8)
    qualification_gaps: list[Qualification] = Field(max_length=5)
    qualification_confirmed: list[QualificationConfirmed] = Field(max_length=5)
    prospect_tasks: list[ProspectTask] = Field(max_length=4)
    seller_tasks: list[SellerTask] = Field(max_length=6)
    objections: list[Objection] = Field(max_length=6)
    prospect_facts: list[ProspectFact] = Field(max_length=6)


class _Evidenced(Protocol):
    @property
    def evidence(self) -> Sequence[EvidenceRef]: ...


class _WithText(Protocol):
    @property
    def text(self) -> str: ...


class CallMapContractError(ValueError):
    """A call map that fails the contract, named by its content-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_call_map(value: object) -> CallMap:
    """Validate a stored `call_map` shape; any miss is `call_map_invalid`."""
    try:
        return CallMap.model_validate(value)
    except ValidationError as error:
        raise CallMapContractError("call_map_invalid") from error


def _words(text: str) -> int:
    return len(text.split())


def _squash(text: str) -> str:
    return " ".join(text.split())


def _unique(values: Sequence[str]) -> bool:
    return len(set(values)) == len(values)


def has_score_prose(text: str) -> bool:
    """True when prose judges with a number; plain day/month dates stay allowed."""
    if _SCORE_PROSE.search(text):
        return True
    if any(_DATE.match(fraction) is None for fraction in _FRACTION.findall(text)):
        return True
    try:
        require_qualitative_claims(text)
    except ValueError:
        return True
    return False


def speaker_label_leaks(texts: Iterable[str]) -> list[str]:
    """Return every provider label (`Speaker 0`, `spk_1`, `SPEAKER_00`) found in prose."""
    return [match.group(0) for text in texts for match in _SPEAKER_LABEL.finditer(text)]


def prose_fields(call_map: CallMap) -> list[str]:
    """The call map's own words (never the quotes), for the label-leak check."""
    texted: list[_WithText] = [
        *call_map.signals,
        *call_map.pitch_items,
        *call_map.pains,
        *call_map.claims,
        *call_map.prospect_tasks,
        *call_map.seller_tasks,
        *call_map.objections,
        *call_map.prospect_facts,
    ]
    optional = [call_map.outcome.next_step_when, *(task.due_text for task in call_map.seller_tasks)]
    return [
        call_map.verdict_line,
        *(item.text for item in texted),
        *(money.label for money in call_map.money),
        *(text for text in optional if text is not None),
    ]


def check_call_map(
    call_map: CallMap | object, segments: list[TranscriptSegment], duration_ms: int | None
) -> list[str]:
    """Return the §3.2 failure codes for a call map, in the web parser's order."""
    if not isinstance(call_map, CallMap):
        try:
            call_map = parse_call_map(call_map)
        except CallMapContractError as error:
            return [error.code]
    codes: list[str] = []

    def fail(ok: bool, code: str = "call_map_invalid") -> None:
        if not ok and code not in codes:
            codes.append(code)

    by_id = {segment["id"]: segment for segment in segments}
    roles = {speaker.speaker_id: speaker.role for speaker in call_map.speakers}

    def start_of(ref: EvidenceRef) -> int | None:
        segment = by_id.get(ref.segment_id)
        return None if segment is None else segment["start_ms"]

    def role_fits(ref: EvidenceRef, wanted: Role) -> bool:
        segment = by_id.get(ref.segment_id)
        role = None if segment is None else roles.get(segment["speaker_id"] or "")
        return role is None or role == wanted  # unknown refs are reported elsewhere

    for ids in (
        [item.id for item in call_map.pitch_items],
        [item.id for item in call_map.pains],
        [item.id for item in call_map.claims],
        [item.id for item in call_map.seller_tasks],
        [item.id for item in call_map.objections],
    ):
        fail(_unique(ids))
    fail(all(len(o.reply) == 1 or o.handling == "ignored" for o in call_map.objections))

    evidenced: list[_Evidenced] = [
        call_map.call_purpose,
        call_map.outcome,
        *call_map.signals,
        *call_map.pitch_items,
        *call_map.pains,
        *call_map.money,
        *call_map.claims,
        *call_map.qualification_confirmed,
        *call_map.prospect_tasks,
        *call_map.seller_tasks,
        *call_map.objections,
        *call_map.prospect_facts,
    ]
    refs = [
        *(call_map.time_promise.evidence if call_map.time_promise else []),
        *(ref for item in evidenced for ref in item.evidence),
        *(ref for objection in call_map.objections for ref in objection.reply),
    ]
    for ref in refs:
        segment = by_id.get(ref.segment_id)
        fail(
            segment is not None and _squash(ref.quote) in _squash(segment["text"]),
            "call_map_evidence_unresolved",
        )
    outcome = call_map.outcome
    fail(
        bool(outcome.evidence) or (outcome.kind == "none" and outcome.next_step_rung == "none"),
        "call_map_evidence_unresolved",
    )

    end = compute_call_metrics(segments, duration_ms)["time_used_ms"]

    def inside(ms: int) -> bool:
        return 0 <= ms <= end

    promise = call_map.time_promise.promised_ms if call_map.time_promise else PROMISE_MS[0]
    fail(
        all(inside(phase.start_ms) for phase in call_map.phases)
        and all(p.start_ms < p.end_ms and inside(p.end_ms) for p in call_map.pitch_items)
        and PROMISE_MS[0] <= promise <= PROMISE_MS[1],
        "call_map_time_out_of_range",
    )
    for objection in call_map.objections:
        raised = start_of(objection.evidence[0])
        replied = [start_of(ref) for ref in objection.reply]
        fail(
            raised is None or all(at is None or at >= raised for at in replied),
            "call_map_time_out_of_range",
        )
    phases = call_map.phases
    fail(
        all(
            index == 0
            or (
                phase.start_ms > phases[index - 1].start_ms and phase.name != phases[index - 1].name
            )
            for index, phase in enumerate(phases)
        ),
        "call_map_phase_order_invalid",
    )

    speakers = {s["speaker_id"] for s in segments if s["speaker_id"] is not None}
    named = [speaker.speaker_id for speaker in call_map.speakers]
    pitch_ids = {item.id for item in call_map.pitch_items}
    fail(
        _unique(named)
        and set(named) == speakers
        and all(
            pain.raised_by in speakers
            and (pain.addressed_by is None or pain.addressed_by in pitch_ids)
            for pain in call_map.pains
        ),
        "call_map_reference_unknown",
    )
    seller_cited: list[_Evidenced] = [*call_map.claims, *call_map.seller_tasks]
    prospect_cited: list[_Evidenced] = [*call_map.objections, *call_map.prospect_facts]
    fail(
        all(role_fits(ref, "seller") for item in seller_cited for ref in item.evidence)
        and all(role_fits(ref, "seller") for o in call_map.objections for ref in o.reply)
        and all(role_fits(ref, "prospect") for item in prospect_cited for ref in item.evidence),
        "call_map_role_mismatch",
    )

    items = [*call_map.qualification_gaps, *(q.item for q in call_map.qualification_confirmed)]
    fail(
        len(items) == len(QUALIFICATION_ITEMS) and set(items) == set(QUALIFICATION_ITEMS),
        "call_map_qualification_invalid",
    )

    texted: list[_WithText] = [
        *call_map.pitch_items,
        *call_map.pains,
        *call_map.claims,
        *call_map.prospect_tasks,
        *call_map.seller_tasks,
        *call_map.objections,
    ]
    capped: list[tuple[str, int]] = [
        (call_map.verdict_line, 12),
        *((ref.quote, 20) for ref in refs),
        *((signal.text, 8) for signal in call_map.signals),
        *((item.text, 12) for item in texted),
        *((money.label, 6) for money in call_map.money),
        *((task.due_text, 6) for task in call_map.seller_tasks if task.due_text is not None),
        *((fact.text, 8) for fact in call_map.prospect_facts),
    ]
    if outcome.next_step_when is not None:
        capped.append((outcome.next_step_when, 6))
    fail(all(_words(text) <= cap for text, cap in capped), "call_map_word_cap_exceeded")
    fail(not has_score_prose(call_map.verdict_line))

    fail(
        all(
            0 <= money.value_min <= money.value_max and len(money.unit) <= _UNIT_CHARS
            for money in call_map.money
        ),
        "call_map_money_invalid",
    )
    fail(
        all(signal.kind in SIGNAL_KINDS_V1[signal.polarity] for signal in call_map.signals)
        and all(objection.kind in OBJECTION_KINDS_V1 for objection in call_map.objections),
        "call_map_signal_kind_unknown",
    )
    return codes


def _segment_id(item: Mapping[str, object] | EvidenceRef | str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, EvidenceRef):
        return item.segment_id
    return str(item["segment_id"])


def dimension_state_ceiling(
    state: DimensionState, evidence: Iterable[Mapping[str, object] | EvidenceRef | str]
) -> DimensionState:
    """Lower a dimension state to what its evidence supports (plan D8); never raise it."""
    if state in ("not_applicable", "conflicted", "unknown"):
        return state
    cited = {_segment_id(item) for item in evidence}
    if not cited:
        return "insufficient_evidence"
    if len(cited) == 1 and state == "observed":
        return "partial"
    return state


def unverifiable_claims_cited(call_map: CallMap, ethics_notes: Sequence[Mapping[str, Any]]) -> bool:
    """Defect 6: when a claim is `no` or `unclear`, an ethics note must cite one of them."""
    flagged = {
        ref.segment_id
        for claim in call_map.claims
        if claim.verifiable != "yes"
        for ref in claim.evidence
    }
    if not flagged:
        return True
    return any(
        str(ref.get("segment_id")) in flagged
        for note in ethics_notes
        for ref in note.get("evidence", ())
    )
