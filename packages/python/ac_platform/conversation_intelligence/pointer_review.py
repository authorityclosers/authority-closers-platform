"""AI pointer review for the 15 Oct Report (owner decision, 16 Oct 2026).

The owner approved AI scores for the Report (rulebook 693645b0, superseding the
AC-SVAL scoring guardrail for this feature only). One provider call reads one
saved transcript and assesses each of the 27 pointers. The result is an AI
draft, not reviewed by Dipak, and is labelled so wherever it is shown.

The model cites evidence by transcript segment id only; quotes, speakers and
times are copied here from the saved transcript, never from the model. The
overall score is the rounded mean of the scored pointers, so it always matches
the rows. Pointer statuses for scored rows follow the doc's score legend.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from ac_platform.conversation_intelligence.report_structure import POINTERS as STRUCTURE_POINTERS

VERSION = "pointer-review/1"
PROMPT_REVISION = "pointer-review-prompt/2"
MODEL_ID = "gemini-3.8-flash"
MAX_OUTPUT_TOKENS = 8000

SCORED = ("excellent", "good", "average", "needs_improvement")
STAGES = ("Initial Contact", "Discovery", "Solution Presentation", "Negotiation", "Closing")
UNSCORED = ("not_observed", "not_applicable", "insufficient_evidence")
STATUSES = SCORED + UNSCORED

# What each pointer evaluates, in the owner doc's words (image6, image9).
EVALUATES: dict[str, str] = {
    "call_opening_first_impression": "How you introduced yourself and created a positive start.",
    "purpose_agenda_setting": "Whether you set a clear purpose and structure for the call.",
    "tone_energy": "Your tone, confidence and enthusiasm during the call.",
    "active_listening": "Whether you listened without interrupting and showed interest.",
    "open_ended_questions": "Use of open-ended questions to explore the prospect's needs.",
    "enough_questions": "Whether you asked enough questions to understand the bigger picture.",
    "prospect_role": "How well you understood their role, authority and decision-making power.",
    "needs_challenges": "How deeply you explored their key needs and challenges.",
    "current_solution": "Whether you understood their current solution and gaps.",
    "business_impact": "Whether you explored the impact on revenue, cost, time or resources.",
    "decision_process": "How well you explored their decision-making process and timeline.",
    "stakeholders": "Whether you discussed other people involved in the decision.",
    "handling_objections": "How you addressed concerns or objections raised by the prospect.",
    # Kept distinct from presenting_solution (owner: keep all 27): value, not explanation.
    "solution_value": "How clearly you tied the value and results of your solution to their needs.",
    "discussing_pricing": "How confidently and transparently you handled pricing discussions.",
    "handling_competition": "How well you positioned your differentiation against competitors.",
    "checking_concerns": "Whether you asked if they had any other concerns before moving forward.",
    "next_steps": "How clearly you defined and agreed on the next steps.",
    "call_control": "Whether you kept the conversation focused and avoided tangents.",
    "question_talk_ratio": "The balance between the questions you asked and the time you spoke.",
    "handling_silence": "How well you handled pauses and used them effectively.",
    "professionalism": "Your overall professionalism, respect and courtesy.",
    "closing_attitude": "Your confidence and intent to move the deal forward.",
    "building_rapport": "Whether you built rapport and created a comfortable conversation.",
    "presenting_solution": (
        "Whether you explained what your solution is and how it works, in a clear order."
    ),
    "creating_value": "Whether you clearly communicated the value and benefits of your solution.",
    "overall_communication": "Whether your communication was clear, structured and easy to follow.",
}
POINTER_IDS: tuple[str, ...] = tuple(item[0] for item in STRUCTURE_POINTERS)
LABELS: dict[str, str] = {item[0]: item[1] for item in STRUCTURE_POINTERS}
if set(POINTER_IDS) != set(EVALUATES) or len(POINTER_IDS) != 27:
    raise RuntimeError("pointer catalogue mismatch")

BAND_LABEL = {
    "excellent": "Excellent",
    "good": "Good",
    "average": "Average",
    "needs_improvement": "Needs Improvement",
}

_LIMITS = {"what_happened": 360, "why_it_matters": 260, "tip": 180, "topic": 70, "line": 240}
_SPEAKER_LABEL = re.compile(r"\bspeaker[_ ]?\d+\b", re.IGNORECASE)


class PointerReviewError(ValueError):
    """Stable code only; never carries transcript or provider text."""


def band(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "average"
    return "needs_improvement"


def _system_prompt(roles: dict[str, str]) -> str:
    seller = [speaker for speaker, role in roles.items() if role == "rep"]
    prospect = [speaker for speaker, role in roles.items() if role == "prospect"]
    who = (
        f"The salesperson is {', '.join(seller)}. The prospect is {', '.join(prospect)}."
        if seller and prospect
        else "Work out from the conversation who is the salesperson and who is the prospect."
    )
    rows = "\n".join(
        f"- {pointer_id}: {LABELS[pointer_id]}. {EVALUATES[pointer_id]}"
        for pointer_id in POINTER_IDS
    )
    return f"""{PROMPT_REVISION}
You are a senior sales coach at Authority Closers. Assess one sales call against
each of the 27 pointers below, using only what was said in the transcript.
{who}

Write to the salesperson as "you" and call the other person "the prospect".
Use plain, everyday English: short sentences a 14-year-old understands. No
jargon, no speaker labels, no made-up names, numbers or facts.

For every pointer return exactly one entry:
- status: excellent, good, average or needs_improvement when the call gives
  enough to judge; not_observed when the topic never came up; not_applicable
  when it does not fit this type or stage of call; insufficient_evidence when
  it came up but too briefly to judge fairly.
- score: a whole number 0-100 for judged pointers (90-100 excellent, 70-89
  good, 50-69 average, below 50 needs_improvement); null otherwise. Be honest
  and specific; do not inflate scores.
- what_happened: one or two sentences on what you did in this call. For a
  pointer that is not judged, one short sentence on why.
- why_it_matters: one sentence on why this matters for the sale (null when not judged).
- evidence: up to 2 segment ids, like "s12", from the transcript that show it ([] when none).
- how_to_improve: up to 2 short, specific actions for the next call ([] when
  not judged or when nothing should change).
- training_topic: a short lesson title for this skill (null when not judged).

Also return score_line: one sentence that sums up how the call went overall.

And return outcome, about where the deal stands after this call:
- stages: which of these the call covered, in order: Initial Contact,
  Discovery, Solution Presentation, Negotiation, Closing.
- reasons: up to 4 short reasons the deal stands where it does.
- objections: up to 4 concerns the prospect raised; handled is true when you
  answered it well on the call.
- next_steps: up to 4 agreed actions; owner is "you" or "prospect"; when is the
  time said on the call (like "Friday 4 PM"), or null if none was said.
- notes: up to 3 other useful facts from the call.
- suggested_action: one sentence on the best next move for you.
Only include what the call says; leave a list empty rather than guess.

Pointers:
{rows}
"""


def _clock(ms: int) -> str:
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def build_prompt(segments: list[dict[str, Any]], roles: dict[str, str]) -> tuple[str, str]:
    """System and user text for one call. Segments: id, speaker_id, start_ms, text."""
    lines = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        speaker = segment.get("speaker_id") or "unknown"
        lines.append(f"[{segment['id']}] {speaker} {_clock(int(segment['start_ms']))}: {text}")
    if not lines:
        raise PointerReviewError("pointer_review_transcript_empty")
    return _system_prompt(roles), "Transcript:\n" + "\n".join(lines)


def response_schema() -> dict[str, Any]:
    nullable_text = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    entry = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(POINTER_IDS)},
            "status": {"type": "string", "enum": list(STATUSES)},
            "score": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "what_happened": nullable_text,
            "why_it_matters": nullable_text,
            "evidence": {"type": "array", "items": {"type": "string"}},
            "how_to_improve": {"type": "array", "items": {"type": "string"}},
            "training_topic": nullable_text,
        },
        "required": [
            "id",
            "status",
            "score",
            "what_happened",
            "why_it_matters",
            "evidence",
            "how_to_improve",
            "training_topic",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "score_line": {"type": "string"},
            "outcome": {
                "type": "object",
                "properties": {
                    "stages": {"type": "array", "items": {"type": "string", "enum": list(STAGES)}},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "objections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "handled": {"type": "boolean"},
                            },
                            "required": ["text", "handled"],
                        },
                    },
                    "next_steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "owner": {"type": "string", "enum": ["you", "prospect"]},
                                "when": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            },
                            "required": ["text", "owner", "when"],
                        },
                    },
                    "notes": {"type": "array", "items": {"type": "string"}},
                    "suggested_action": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                },
                "required": [
                    "stages",
                    "reasons",
                    "objections",
                    "next_steps",
                    "notes",
                    "suggested_action",
                ],
            },
            "pointers": {"type": "array", "items": entry},
        },
        "required": ["score_line", "pointers", "outcome"],
    }


def gemini_body(system: str, user: str) -> dict[str, Any]:
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseJsonSchema": response_schema(),
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
        },
    }


def prompt_sha256(system: str, user: str) -> str:
    return hashlib.sha256(
        json.dumps([MODEL_ID, system, user], ensure_ascii=False).encode()
    ).hexdigest()


def decode_gemini(response: dict[str, Any]) -> dict[str, Any]:
    try:
        candidate = response["candidates"][0]
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        value = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise PointerReviewError("pointer_review_response_invalid") from None
    if not isinstance(value, dict):
        raise PointerReviewError("pointer_review_response_invalid")
    return value


def _words(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _SPEAKER_LABEL.sub("the speaker", " ".join(value.split()))
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def parse_review(raw: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate one model answer against the saved transcript; never trust its quotes."""
    by_id = {str(segment["id"]): segment for segment in segments}
    entries = raw.get("pointers")
    if not isinstance(entries, list):
        raise PointerReviewError("pointer_review_pointers_missing")
    seen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") not in EVALUATES:
            continue
        if entry["id"] in seen:
            raise PointerReviewError("pointer_review_duplicate_pointer")
        seen[entry["id"]] = entry
    if len(seen) != len(POINTER_IDS):
        raise PointerReviewError("pointer_review_pointers_incomplete")
    pointers: list[dict[str, Any]] = []
    scores: list[int] = []
    for number, pointer_id in enumerate(POINTER_IDS, 1):
        entry = seen[pointer_id]
        status = entry.get("status")
        score = entry.get("score")
        if status not in STATUSES:
            raise PointerReviewError("pointer_review_status_invalid")
        if status in SCORED:
            if type(score) is not int or not 0 <= score <= 100:
                raise PointerReviewError("pointer_review_score_invalid")
            # The doc's legend decides the label, so a row never contradicts its score.
            status = band(score)
        else:
            score = None
        evidence: list[dict[str, Any]] = []
        for reference in entry.get("evidence") or []:
            segment = by_id.get(str(reference).strip())
            if segment is None or any(item["segment_id"] == segment["id"] for item in evidence):
                continue
            quote = " ".join(str(segment.get("text") or "").split())
            if not quote:
                continue
            evidence.append(
                {
                    "segment_id": str(segment["id"]),
                    "quote": quote[:600],
                    "start_ms": int(segment["start_ms"]),
                    "end_ms": int(segment["end_ms"]),
                }
            )
            if len(evidence) == 2:
                break
        tips = [
            tip
            for tip in (_words(item, _LIMITS["tip"]) for item in entry.get("how_to_improve") or [])
            if tip
        ][:2]
        judged = status in SCORED
        topic = _words(entry.get("training_topic"), _LIMITS["topic"]) if judged else None
        if score is not None:
            scores.append(score)
        pointers.append(
            {
                "id": pointer_id,
                "number": number,
                "label": LABELS[pointer_id],
                "status": status,
                "score": score,
                "what_happened": _words(entry.get("what_happened"), _LIMITS["what_happened"]),
                "why_it_matters": (
                    _words(entry.get("why_it_matters"), _LIMITS["why_it_matters"])
                    if judged
                    else None
                ),
                "evidence": evidence,
                "how_to_improve": tips if judged else [],
                "training_topic": topic,
            }
        )
    overall = round(sum(scores) / len(scores)) if scores else None
    return {
        "version": VERSION,
        "overall": {
            "score": overall,
            "label": BAND_LABEL[band(overall)] if overall is not None else None,
            "line": _words(raw.get("score_line"), _LIMITS["line"]),
            "method": "mean_of_scored_pointers",
            "scored_pointers": len(scores),
        },
        "pointers": pointers,
        "outcome": _outcome(raw.get("outcome")),
    }


def _outcome(value: Any) -> dict[str, Any] | None:
    """The call's own facts about where the deal stands; never the outcome itself."""
    if not isinstance(value, dict):
        return None

    def texts(items: Any, count: int, limit: int) -> list[str]:
        found = [_words(item, limit) for item in items] if isinstance(items, list) else []
        return [item for item in found if item][:count]

    raw_stages = value.get("stages")
    stages: list[Any] = raw_stages if isinstance(raw_stages, list) else []
    objections = []
    for item in value.get("objections") or []:
        words = _words(item.get("text"), 240) if isinstance(item, dict) else None
        if words:
            objections.append({"text": words, "handled": item.get("handled") is True})
    steps = []
    for item in value.get("next_steps") or []:
        words = _words(item.get("text"), 200) if isinstance(item, dict) else None
        if words:
            owner = item.get("owner")
            steps.append(
                {
                    "text": words,
                    "owner": owner if owner in {"you", "prospect"} else None,
                    "when": _words(item.get("when"), 60),
                }
            )
    return {
        "stages": [stage for stage in STAGES if stage in stages],
        "reasons": texts(value.get("reasons"), 4, 240),
        "objections": objections[:4],
        "next_steps": steps[:4],
        "notes": texts(value.get("notes"), 3, 240),
        "suggested_action": _words(value.get("suggested_action"), 240),
    }


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def merge_into_structure(structure: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    """Overlay one saved review on the report-structure/1 projection."""
    merged = deepcopy(structure)
    overall = review.get("overall") or {}
    overview = merged.setdefault("overview", {})
    if overall.get("score") is not None:
        overview["score"] = overall["score"]
        overview["score_label"] = overall.get("label")
        overview["score_line"] = overall.get("line")
        overview["score_status"] = "ai_draft"
        overview["score_method"] = overall.get("method")
    by_id = {pointer["id"]: pointer for pointer in review.get("pointers") or []}
    for pointer in merged.get("pointers") or []:
        item = by_id.get(pointer.get("id"))
        if item is None:
            continue
        pointer["status"] = item["status"]
        pointer["status_reason"] = None
        pointer["score"] = item["score"]
        # Assessed by the AI review, scored or not: an AI draft either way.
        pointer["score_status"] = "ai_draft"
        pointer["rating"] = BAND_LABEL.get(item["status"])
        pointer["coverage"] = "ai_pointer_review"
        pointer["what_happened"] = item["what_happened"]
        pointer["why_it_matters"] = item["why_it_matters"]
        if item["evidence"]:
            pointer["evidence"] = deepcopy(item["evidence"])
        pointer["how_to_improve"] = list(item["how_to_improve"])
        pointer["training_video"] = (
            {"title": item["training_topic"], "url": None, "minutes": None}
            if item.get("training_topic")
            else None
        )
    if review.get("outcome"):
        merged["call_outcome_details"] = deepcopy(review["outcome"])
    merged["review_status"] = "ai_draft_not_dipak_reviewed"
    return merged


async def latest_review(database: Any, envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Newest saved review for exactly this run, source and transcript revision."""
    from uuid import UUID

    from sqlalchemy import select

    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    try:
        recording_id = UUID(str(envelope["recording_id"]))
        run_id = UUID(str(envelope["run_id"]))
        source = str(envelope["source_sha256"])
        revision = str(envelope["transcript_revision"])
    except (KeyError, ValueError):
        return None
    row = await database.scalar(
        select(ConversationPointerReview)
        .where(
            ConversationPointerReview.recording_id == recording_id,
            ConversationPointerReview.run_id == run_id,
            ConversationPointerReview.source_sha256 == source,
            ConversationPointerReview.transcript_revision == revision,
            ConversationPointerReview.version == VERSION,
            ConversationPointerReview.erased_at.is_(None),
        )
        .order_by(ConversationPointerReview.created_at.desc())
        .limit(1)
    )
    if row is None or row.payload is None or payload_sha256(row.payload) != row.payload_sha256:
        return None
    return dict(row.payload)


async def erase_pointer_reviews_for_recording(
    database: Any, recording_id: Any, now: datetime
) -> int:
    """Canonical erasure: empty every saved review version of one call.

    The row keeps its minimal provenance (ids, digests, model, tokens, times).
    Repeating it is a no-op.
    """
    from sqlalchemy import select

    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    rows = (
        await database.scalars(
            select(ConversationPointerReview).where(
                ConversationPointerReview.recording_id == recording_id,
                ConversationPointerReview.erased_at.is_(None),
            )
        )
    ).all()
    for row in rows:
        row.payload, row.erased_at = None, now
    return len(rows)


_ERASED_CALL_COUNT = """
    SELECT count(*)
    FROM conversation_pointer_reviews r
    JOIN conversation_recordings c ON c.id = r.recording_id
    LEFT JOIN conversation_report_drafts d ON d.id = r.report_draft_id
    WHERE r.erased_at IS NULL
      AND (c.state IN ('deleting', 'deleted') OR d.erased_at IS NOT NULL OR d.id IS NULL)
"""
_ERASED_CALL_ERASE = """
    UPDATE conversation_pointer_reviews SET payload = NULL, erased_at = now()
    WHERE id IN (
      SELECT r.id
      FROM conversation_pointer_reviews r
      JOIN conversation_recordings c ON c.id = r.recording_id
      LEFT JOIN conversation_report_drafts d ON d.id = r.report_draft_id
      WHERE r.erased_at IS NULL
        AND (c.state IN ('deleting', 'deleted') OR d.erased_at IS NOT NULL OR d.id IS NULL)
    )
"""


def erase_reviews_of_erased_calls(connection: Any, *, apply: bool) -> dict[str, int]:
    """One-off cleanup (AUT-2010): reviews whose call or report was already erased.

    Dry run by default; with apply it empties them in the caller's transaction.
    """
    from sqlalchemy import text

    count = int(connection.execute(text(_ERASED_CALL_COUNT)).scalar_one())
    erased = connection.execute(text(_ERASED_CALL_ERASE)).rowcount if apply and count else 0
    return {"found": count, "erased": int(erased or 0)}


def save_review(
    connection: Any,
    *,
    report: dict[str, Any],
    review: dict[str, Any],
    prompt_digest: str,
    usage: dict[str, Any],
    created_by: str,
    now: datetime,
) -> bool:
    """Save one review unless its call or report was erased meanwhile.

    The recording row is locked FOR SHARE, which waits for (and is fenced by)
    canonical erasure's FOR UPDATE, so a late provider answer never restores
    content after erasure began. Returns False when it refuses.
    """
    from uuid import uuid4

    from sqlalchemy import insert, text

    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    state = connection.execute(
        text("SELECT state FROM conversation_recordings WHERE id = :id FOR SHARE"),
        {"id": report["recording_id"]},
    ).scalar()
    draft_live = connection.execute(
        text("SELECT erased_at IS NULL FROM conversation_report_drafts WHERE id = :id FOR SHARE"),
        {"id": report["draft_id"]},
    ).scalar()
    if state is None or state in {"deleting", "deleted"} or draft_live is not True:
        return False
    connection.execute(
        insert(ConversationPointerReview).values(
            id=uuid4(),
            tenant_id=report["tenant_id"],
            recording_id=report["recording_id"],
            run_id=report["run_id"],
            report_draft_id=report["draft_id"],
            source_sha256=report["source_sha256"],
            transcript_revision=report["transcript_revision"],
            version=VERSION,
            model_id=MODEL_ID,
            prompt_sha256=prompt_digest,
            payload=review,
            payload_sha256=payload_sha256(review),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            created_by=created_by,
            created_at=now,
        )
    )
    return True
