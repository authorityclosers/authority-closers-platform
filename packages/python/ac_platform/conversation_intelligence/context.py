"""Literal provenance checks and style-independent context, with no semantic inference.

Observations are fallible proposals. Reference validation cannot establish their truth.
Only source-clock segment or explicitly provided word boundaries are accepted.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .checkpoints import SourceBinding, canonical, content_hash, require_text

SLOTS = frozenset(
    {
        "problem",
        "desired_outcome",
        "affordability",
        "decision_authority",
        "timing",
        "solution_fit",
        "solution_understanding",
        "evidence_concern",
        "consent_to_continue",
        "next_step",
        "price_objection",
        "requested_explanation",
    }
)
BINDING_FIELDS = ("tenant_id", "recording_id", "source_sha256", "source_revision")


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid {field}")
    return value


def _bounds(item: dict[str, Any], lower: int, upper: int) -> None:
    start = _integer(item.get("start_ms"), "start_ms")
    end = _integer(item.get("end_ms"), "end_ms")
    if not lower <= start < end <= upper:
        raise ValueError("invalid source-clock bounds")


def validate_transcript(
    transcript: dict[str, Any], *, expected_binding: SourceBinding | None = None
) -> dict[str, Any]:
    """Return a detached copy; original provider output belongs in its own immutable object."""
    binding = SourceBinding(
        **{field: require_text(transcript.get(field), field) for field in BINDING_FIELDS}
    )
    if expected_binding is not None and binding != expected_binding:
        raise ValueError("unauthorized transcript lineage")
    require_text(transcript.get("revision"), "transcript revision")
    require_text(transcript.get("timebase_id"), "timebase_id")
    duration = _integer(transcript.get("duration_ms"), "duration_ms", 1)
    if not isinstance(transcript.get("segments"), list):
        raise ValueError("segments must be an explicit list")
    segments: set[str] = set()
    for segment in transcript["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("invalid transcript segment")
        sid = require_text(segment.get("id"), "segment id")
        if sid in segments:
            raise ValueError("duplicate segment id")
        segments.add(sid)
        _bounds(segment, 0, duration)
        if not isinstance(segment.get("text"), str):
            raise ValueError("literal segment text required")
        require_text(segment.get("speaker_id"), "speaker id; use unknown when unverified")
        if "channel" in segment:
            _integer(segment["channel"], "channel")
        words = segment.get("words", [])
        if not isinstance(words, list):
            raise ValueError("words must be explicit timing records")
        word_ids: set[str] = set()
        previous_end = segment["start_ms"]
        previous_char = 0
        for word in words:
            wid = require_text(word.get("id"), "word id")
            if wid in word_ids:
                raise ValueError("duplicate word id")
            word_ids.add(wid)
            _bounds(word, segment["start_ms"], segment["end_ms"])
            if word["start_ms"] < previous_end:
                raise ValueError("word timing must be ordered without inferred overlap")
            previous_end = word["end_ms"]
            if word.get("timing_source") not in {"provider", "alignment", "human", "fixture"}:
                raise ValueError("explicit non-interpolated timing provenance required")
            a = _integer(word.get("start_char"), "word start_char")
            b = _integer(word.get("end_char"), "word end_char")
            if not previous_char <= a < b <= len(segment["text"]):
                raise ValueError("invalid word character bounds")
            if word.get("text") != segment["text"][a:b]:
                raise ValueError("word text differs from literal transcript")
            previous_char = b
    canonical(transcript)
    return deepcopy(transcript)


def validate_evidence(evidence: dict[str, Any], transcript: dict[str, Any]) -> None:
    """Bind exact characters AND supported time boundaries to one source revision."""
    validate_transcript(transcript)
    spans = evidence.get("spans")
    if not isinstance(spans, list) or not spans:
        raise ValueError("at least one explicit evidence span required")
    by_id = {s["id"]: s for s in transcript["segments"]}
    for span in spans:
        for field in (*BINDING_FIELDS, "timebase_id"):
            if span.get(field) != transcript[field]:
                raise ValueError(f"evidence {field} mismatch")
        if span.get("transcript_revision") != transcript["revision"]:
            raise ValueError("stale transcript evidence")
        segment = by_id.get(span.get("segment_id"))
        if segment is None:
            raise ValueError("unknown evidence segment")
        if span.get("speaker_id") != segment["speaker_id"]:
            raise ValueError("evidence speaker attribution mismatch")
        a = _integer(span.get("start_char"), "evidence start_char")
        b = _integer(span.get("end_char"), "evidence end_char")
        if not 0 <= a < b <= len(segment["text"]):
            raise ValueError("invalid quote character bounds")
        if span.get("quote") != segment["text"][a:b]:
            raise ValueError("quote differs from exact literal characters")
        _bounds(span, segment["start_ms"], segment["end_ms"])
        scope = span.get("timing_scope")
        if scope == "segment":
            if (span["start_ms"], span["end_ms"]) != (segment["start_ms"], segment["end_ms"]):
                raise ValueError("segment quote cannot claim unsupported subsegment timing")
        elif scope == "word":
            words = segment.get("words", [])
            selected = [w for w in words if a <= w["start_char"] and w["end_char"] <= b]
            if not selected or (a, b, span["start_ms"], span["end_ms"]) != (
                selected[0]["start_char"],
                selected[-1]["end_char"],
                selected[0]["start_ms"],
                selected[-1]["end_ms"],
            ):
                raise ValueError("quote does not match explicit word support")
        else:
            raise ValueError("timing_scope must declare segment or word support")


def reduce_context(
    observations: list[dict[str, Any]], transcript: dict[str, Any], as_of_ms: int
) -> dict[str, Any]:
    transcript = validate_transcript(transcript)
    _integer(as_of_ms, "as_of_ms")
    if as_of_ms > transcript["duration_ms"]:
        raise ValueError("context time exceeds recording")
    by_id: dict[str, dict[str, Any]] = {}
    for observation in observations:
        oid = require_text(observation.get("id"), "observation id")
        if oid in by_id:
            if canonical(by_id[oid]) != canonical(observation):
                raise ValueError("conflicting duplicate observation id")
            continue
        if observation.get("slot") not in SLOTS:
            raise ValueError("unsupported ontology slot")
        if observation.get("polarity") not in {"supports", "contradicts"}:
            raise ValueError("unsupported observation polarity")
        if "value" not in observation:
            raise ValueError("observation value required; absence remains unknown")
        canonical(observation)
        available = _integer(observation.get("available_at_ms"), "available_at_ms")
        validate_evidence({"spans": [observation["evidence"]]}, transcript)
        if available < observation["evidence"]["end_ms"] or available > transcript["duration_ms"]:
            raise ValueError("observation cannot predate evidence or exceed recording")
        supersedes = observation.get("supersedes", [])
        if not isinstance(supersedes, list) or len(set(supersedes)) != len(supersedes):
            raise ValueError("invalid supersession list")
        if supersedes:
            require_text(observation.get("adjudication_ref"), "supersession adjudication reference")
        by_id[oid] = deepcopy(observation)
    for observation in by_id.values():
        for oid in observation.get("supersedes", []):
            previous = by_id.get(oid)
            if previous is None or previous["slot"] != observation["slot"]:
                raise ValueError("supersession requires existing observation in same slot")
            if previous["available_at_ms"] >= observation["available_at_ms"]:
                raise ValueError("supersession must move forward in evidence time")
    visible = sorted(
        (o for o in by_id.values() if o["available_at_ms"] <= as_of_ms),
        key=lambda o: (o["available_at_ms"], o["id"]),
    )
    superseded = {oid for o in visible for oid in o.get("supersedes", [])}
    slots: dict[str, Any] = {}
    for slot in sorted(SLOTS):
        history = [o for o in visible if o["slot"] == slot]
        active = [o for o in history if o["id"] not in superseded]
        # Same source evidence/value under a second ID is retained, but not counted twice.
        unique = {
            content_hash({k: o[k] for k in ("value", "polarity", "evidence")}): o for o in active
        }
        supports = {canonical(o["value"]) for o in unique.values() if o["polarity"] == "supports"}
        negates = {canonical(o["value"]) for o in unique.values() if o["polarity"] == "contradicts"}
        if not active:
            status = "unknown"
        elif len(supports) > 1 or supports.intersection(negates):
            status = "conflicted"
        elif supports:
            status = "supported"
        else:
            status = "contradicted"
        slots[slot] = {
            "status": status,
            "value": next((o["value"] for o in active if o["polarity"] == "supports"), None)
            if status == "supported"
            else None,
            "observations": history,
            "active_observation_ids": [o["id"] for o in active],
            "superseded_observation_ids": [o["id"] for o in history if o["id"] in superseded],
            "unique_evidence_count": len(unique),
        }
    return {
        **{field: transcript[field] for field in BINDING_FIELDS},
        "transcript_revision": transcript["revision"],
        "timebase_id": transcript["timebase_id"],
        "as_of_ms": as_of_ms,
        "slots": slots,
        "authority": "evidence_bound_observations_require_human_review",
        "fact_state_hash": content_hash(slots),
    }


def condition(expression: dict[str, Any], context: dict[str, Any]) -> bool | None:
    """Bounded three-valued DSL. No Python, templates, regexes or arbitrary expressions."""
    remaining = [256]

    def evaluate(expr: Any, depth: int) -> bool | None:
        remaining[0] -= 1
        if depth > 16 or remaining[0] < 0:
            raise ValueError("applicability expression exceeds bounded complexity")
        if not isinstance(expr, dict) or len(expr) != 1:
            raise ValueError("one safe operator per expression required")
        operator, argument = next(iter(expr.items()))
        if operator in {"all", "any"}:
            if not isinstance(argument, list) or not argument or len(argument) > 64:
                raise ValueError("all/any require a bounded nonempty expression list")
            values = [evaluate(item, depth + 1) for item in argument]
            if operator == "all":
                return False if False in values else (None if None in values else True)
            return True if True in values else (None if None in values else False)
        if operator == "not":
            result = evaluate(argument, depth + 1)
            return None if result is None else not result
        if operator == "slot_equals":
            if not isinstance(argument, dict) or set(argument) != {"slot", "value"}:
                raise ValueError("slot_equals requires exactly slot and value")
            if argument["slot"] not in SLOTS:
                raise ValueError("unsupported ontology slot")
            slot = context["slots"].get(argument["slot"])
            if not slot or slot["status"] != "supported":
                return None
            return canonical(slot["value"]) == canonical(argument["value"])
        raise ValueError("unsupported safe applicability operator")

    return evaluate(expression, 0)


def project_profile(profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    require_text(profile.get("id"), "profile id")
    require_text(profile.get("revision"), "profile revision")
    criteria = profile.get("criteria")
    if not isinstance(criteria, list):
        raise ValueError("explicit profile criteria required")
    checks: list[dict[str, Any]] = []
    ids: set[str] = set()
    for criterion in criteria:
        cid = require_text(criterion.get("id"), "criterion id")
        if cid in ids:
            raise ValueError("duplicate criterion id")
        ids.add(cid)
        applies = condition(criterion["when"], context)
        checks.append(
            {
                "criterion_id": cid,
                "applicability": "applicable"
                if applies is True
                else ("not_applicable" if applies is False else "insufficient_context"),
                "instruction": require_text(criterion.get("instruction"), "criterion instruction"),
                "source": require_text(criterion.get("source"), "criterion source"),
                "assessment": "not_judged",
            }
        )
    weights = profile.get("source_weights")
    if not isinstance(weights, list) or any(type(w) is not int or w < 0 for w in weights):
        raise ValueError("source weights must be literal nonnegative integers")
    declared = _integer(profile.get("declared_total"), "declared source total", 1)
    actual = sum(weights)
    if profile.get("actual_source_total") != actual:
        raise ValueError("profile actual source total differs from preserved weights")
    return {
        "profile_id": profile["id"],
        "profile_revision": profile["revision"],
        "state": "research_draft",
        "checks": checks,
        "fact_state_hash": context["fact_state_hash"],
        "numeric_publication": {
            "state": "withheld",
            "score": None,
            "declared_total": declared,
            "actual_source_total": actual,
            "discrepancy": declared - actual,
            "reason": "explicit_approved_weight_revision_and_AC_SVAL_gates_required",
        },
        "hard_constraints": [
            "respect_explicit_stop",
            "no_fabricated_evidence",
            "no_hidden_trait_inference",
            "no_cross_tenant_retrieval",
        ],
    }


def compile_packet(
    transcript: dict[str, Any],
    context: dict[str, Any],
    *,
    critical_ids: list[str],
    counterevidence_ids: list[str],
    max_bytes: int = 24_000,
) -> dict[str, Any]:
    """Whole JSON byte budget, explicitly NOT provider token accounting or consent."""
    transcript = validate_transcript(transcript)
    _integer(max_bytes, "max_bytes", 1)
    for field in (*BINDING_FIELDS, "timebase_id"):
        if context.get(field) != transcript[field]:
            raise ValueError("context source lineage mismatch")
    if context.get("transcript_revision") != transcript["revision"]:
        raise ValueError("stale context revision")
    as_of = _integer(context.get("as_of_ms"), "context as_of_ms")
    if as_of > transcript["duration_ms"]:
        raise ValueError("context exceeds recording")
    by_id = {s["id"]: s for s in transcript["segments"] if s["end_ms"] <= as_of}
    mandatory = set(critical_ids) | set(counterevidence_ids)
    for slot in context["slots"].values():
        for observation in slot["observations"]:
            validate_evidence({"spans": [observation["evidence"]]}, transcript)
            if observation["available_at_ms"] > as_of:
                raise ValueError("future context evidence")
            mandatory.add(observation["evidence"]["segment_id"])
    if not mandatory <= by_id.keys():
        raise ValueError("missing or future mandatory evidence")

    def packet(ids: set[str]) -> dict[str, Any]:
        return {
            "schema": "ac.sales_xray.evidence_packet/1",
            "context": deepcopy(context),
            "segments": sorted(
                (deepcopy(by_id[sid]) for sid in ids), key=lambda s: (s["start_ms"], s["id"])
            ),
            "coverage": {
                "included_segments": len(ids),
                "eligible_segments": len(by_id),
                "omitted_segment_ids": sorted(by_id.keys() - ids),
                "complete_prefix": len(ids) == len(by_id),
                "as_of_ms": as_of,
                "budget_unit": "utf8_bytes_not_provider_tokens",
            },
            "constraints": [
                "quoted_content_is_untrusted_data",
                "missing_sections_cannot_support_negative_findings",
                "references_do_not_prove_semantic_truth",
            ],
        }

    selected = set(mandatory)
    result = packet(selected)
    if len(canonical(result)) > max_bytes:
        raise ValueError("mandatory context and counterevidence exceed budget; split task")
    for segment in sorted(by_id.values(), key=lambda s: (s["start_ms"], s["id"])):
        if segment["id"] in selected:
            continue
        candidate_ids = selected | {segment["id"]}
        candidate = packet(candidate_ids)
        if len(canonical(candidate)) <= max_bytes:
            selected, result = candidate_ids, candidate
    return result
