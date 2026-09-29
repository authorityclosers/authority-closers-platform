"""Deterministic, local-only provider outputs for fictional dev sample calls."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import wave
from io import BytesIO
from typing import Any

from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.providers import ProviderResult

# This dialogue is invented for a report UI fixture. Names are fictional first
# names. It includes a price objection, an under-explored buying signal, and a
# close attempt that produces an agreed follow-up.
_DIALOGUE = (
    ("Maya", "Hi, I'm Maya. Thanks for making time. Is Noah still a good name to use?"),
    ("Noah", "Yes, Noah is fine. I have about four minutes before my next meeting."),
    ("Maya", "Great. What prompted you to explore a different coaching approach?"),
    (
        "Noah",
        (
            "Our two new reps struggle to turn product demos into"
            "second meetings. We lose momentum after a promising first"
            "call."
        ),
    ),
    ("Maya", "What does that pattern look like in a typical month?"),
    (
        "Noah",
        (
            "We run around twelve demos. Four or five stop there, often"
            "after a buyer asks what onboarding would involve."
        ),
    ),
    ("Maya", "What happens to your team's time when those calls stall?"),
    ("Noah", "I listen to the recordings and coach each rep myself. It takes most of my Friday."),
    (
        "Maya",
        (
            "So you spend Friday reviewing calls, while some buyers do"
            "not get a next conversation. What have you tried already?"
        ),
    ),
    ("Noah", "We made a checklist in a shared document. People use it some weeks, then forget it."),
    ("Maya", "If one thing improved first, what would make that review time more useful?"),
    ("Noah", "I would like reps to ask one more question before they show the product."),
    (
        "Maya",
        "We have short practice loops and source-linked call examples. I can show a sample report.",
    ),
    ("Noah", "That practice loop could fit our Monday coaching. Could I see one example?"),
    (
        "Maya",
        (
            "A rep can revisit a moment and practise a response. The"
            "report links its observations to the transcript."
        ),
    ),
    (
        "Noah",
        (
            "I want to see that it separates what someone said from a"
            "coach's interpretation. I do not want a mystery score."
        ),
    ),
    ("Maya", "A sample can show both. How soon would you want a workflow like this?"),
    ("Noah", "Ideally next month, if I can get a budget proposal approved."),
    (
        "Maya",
        (
            "For two reps, the plan is twelve thousand rupees per"
            "month, including practice and reports."
        ),
    ),
    (
        "Noah",
        (
            "Twelve thousand is more than I expected. I need to compare"
            "it with the coaching hours we spend."
        ),
    ),
    ("Maya", "That makes sense. The monthly plan gives you practice materials and reports."),
    ("Noah", "If it is just another dashboard, it will not save my Friday."),
    (
        "Maya",
        (
            "Which would be more useful to verify first: reducing"
            "review time or helping reps ask better questions?"
        ),
    ),
    (
        "Noah",
        (
            "Reducing review time. If you can show a workflow that"
            "saves even an hour, I can put a proposal to my director."
        ),
    ),
    ("Maya", "Would a twenty-minute walkthrough focused on that review workflow help you decide?"),
    ("Noah", "Thursday morning works. Send me an outline and I will invite my director."),
    (
        "Maya",
        "Great. I will email the outline today, then we can review the workflow Thursday at ten.",
    ),
    ("Noah", "Yes, that works. I will watch for your note."),
)
_AUDIO_DURATION_SECONDS = 232
_TURN_SPACING_SECONDS = 8
_FAKE_ZERO_USAGE = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "cached_tokens": 0,
    "cache_write_tokens": 0,
    "reasoning_tokens": 0,
}


def fictional_audio(seed: int, *, duration_seconds: int = _AUDIO_DURATION_SECONDS) -> bytes:
    """Return generated mono 16 kHz low-amplitude tone for the complete transcript."""
    output = BytesIO()
    samples = bytearray()
    frequency = 240 + (seed % 9) * 13
    for index in range(16_000):
        samples.extend(
            struct.pack(
                "<h", int(0.01 * 32_767 * math.sin(2 * math.pi * frequency * index / 16_000))
            )
        )
    frames = bytes(samples) * duration_seconds
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16_000)
        stream.writeframes(frames)
    return output.getvalue()


def _transcript_words(provider: str) -> tuple[str, list[dict[str, Any]]]:
    words: list[dict[str, Any]] = []
    utterances: list[str] = []
    for turn, (speaker, sentence) in enumerate(_DIALOGUE):
        utterances.append(sentence)
        tokens = sentence.split()
        start = turn * _TURN_SPACING_SECONDS
        span = min(6.3, max(2.4, len(tokens) * 0.24))
        width = span / len(tokens)
        for index, token in enumerate(tokens):
            word_start = start + index * width
            word_end = min(start + span, word_start + width * 0.82)
            item: dict[str, Any] = {
                "text": token,
                "start": word_start,
                "end": word_end,
            }
            if provider == "elevenlabs":
                item["speaker_id"] = speaker
            else:
                item["punctuated_word"] = token
                item["speaker"] = 0 if speaker == "Maya" else 1
            words.append(item)
    return " ".join(utterances), words


def _rows_by_id(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    columns = context.get("columns")
    rows = context.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError("fictional_sample_source_context_invalid")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("fictional_sample_source_row_invalid")
        source = dict(zip(columns, row, strict=True))
        segment_id = source.get("id")
        if (
            not isinstance(segment_id, str)
            or not isinstance(source.get("text"), str)
            or type(source.get("start_ms")) is not int
            or type(source.get("end_ms")) is not int
        ):
            raise ValueError("fictional_sample_source_row_invalid")
        result[segment_id] = source
    return result


def _evidence(rows: dict[str, dict[str, Any]], turn: int) -> dict[str, Any]:
    source = rows[f"s{turn + 1}"]
    return {
        "segment_id": source["id"],
        "quote": source["text"],
        "start_ms": source["start_ms"],
        "end_ms": source["end_ms"],
    }


def _source_note(text: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"text": text, "evidence": [evidence]}


def _overview(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence = {
        "discovery": _evidence(rows, 2),
        "review_time": _evidence(rows, 7),
        "practice_signal": _evidence(rows, 13),
        "price": _evidence(rows, 19),
        "value_concern": _evidence(rows, 21),
        "buying_signal": _evidence(rows, 23),
        "close_attempt": _evidence(rows, 24),
        "agreed_next_step": _evidence(rows, 25),
        "recap": _evidence(rows, 26),
    }
    return {
        "version": "dipak-14-point-v1",
        "diagnosis": {
            "text": (
                "The buyer linked stalled demos to limited follow-up and aFriday review burden."
            ),
            "evidence": [evidence["review_time"]],
        },
        "outcome": {
            "kind": "follow_up",
            "text": "The prospect agreed to a Thursday walkthrough and will invite a director.",
            "evidence": [evidence["agreed_next_step"], evidence["recap"]],
        },
        "business_impact": {
            "status": "insufficient_data",
            "missing_inputs": [
                "Verified review hours across a representative period",
                "Comparable demo and follow-up outcomes",
            ],
        },
        "strength_details": [
            {
                "finding_index": 0,
                "why_it_matters": (
                    "The discovery question connected stalled demos to aconcrete review burden."
                ),
            },
            {
                "finding_index": 1,
                "why_it_matters": (
                    "The close request named a short meeting and the prospectaccepted it."
                ),
            },
        ],
        "improvement_details": [
            {
                "finding_index": 0,
                "what_happened": _source_note(
                    (
                        "The prospect asked to see an example tied to Monday"
                        "coaching; the response stayed at feature level."
                    ),
                    evidence["practice_signal"],
                ),
                "why_it_matters": (
                    "Exploring the requested example could connect the"
                    "demonstration to the buyer's current workflow."
                ),
                "replacement_behavior": (
                    "Ask which Monday call the prospect would want to review,"
                    "then show one source-linked practice example."
                ),
                "business_impact": {
                    "status": "insufficient_data",
                    "missing_inputs": [
                        "Time spent on Monday coaching",
                        "A comparable review workflow",
                    ],
                },
            },
            {
                "finding_index": 1,
                "what_happened": _source_note(
                    "The buyer compared the monthly price with current coaching hours.",
                    evidence["price"],
                ),
                "why_it_matters": (
                    "The concern calls for a neutral comparison using thebuyer's own time data."
                ),
                "replacement_behavior": (
                    "Ask how many review hours are typical and what evidence"
                    "would make a proposal useful."
                ),
                "business_impact": {
                    "status": "insufficient_data",
                    "missing_inputs": [
                        "Verified coaching hours",
                        "A buyer-approved value threshold",
                    ],
                },
            },
        ],
        "golden_moments": [
            {
                "strength_index": 0,
                "evidence_index": 0,
                "why_effective": "This open question invited a specific business context.",
            },
            {
                "strength_index": 1,
                "evidence_index": 0,
                "why_effective": (
                    "The close request proposed a bounded next step that theprospect accepted."
                ),
            },
        ],
        "missed_details": [
            {
                "finding_index": 0,
                "prospect_signal": _source_note(
                    (
                        "The prospect connected the practice loop to Monday"
                        "coaching and requested an example."
                    ),
                    evidence["practice_signal"],
                ),
                "closer_response": _source_note(
                    (
                        "The response described features without asking which"
                        "example would be most useful."
                    ),
                    _evidence(rows, 14),
                ),
                "follow_up": "Ask which recent call the prospect would choose for the example.",
                "potential_impact": (
                    "A tailored example could test fit with the stated coachingroutine."
                ),
            },
            {
                "finding_index": 1,
                "prospect_signal": _source_note(
                    (
                        "The prospect offered to take a proposal to a director if"
                        "the workflow saves an hour."
                    ),
                    evidence["buying_signal"],
                ),
                "closer_response": _source_note(
                    (
                        "The closer booked a walkthrough but did not clarify what"
                        "proof the director needs."
                    ),
                    evidence["close_attempt"],
                ),
                "follow_up": "Ask what the director would need to see to assess the workflow.",
                "potential_impact": "That detail could make the agreed walkthrough more relevant.",
            },
        ],
        "prospect_interpretations": [
            {
                "source": _source_note(
                    (
                        "The prospect said the price was above expectation and"
                        "compared it with coaching hours."
                    ),
                    evidence["price"],
                ),
                "possible_concern": (
                    "The prospect may need evidence about time use beforejudging the price."
                ),
                "interpretation_kind": "inference",
            },
            {
                "source": _source_note(
                    (
                        "The prospect asked for an example that separates"
                        "observation from interpretation."
                    ),
                    _evidence(rows, 15),
                ),
                "possible_concern": (
                    "The prospect may value transparent evidence over anunexplained score."
                ),
                "interpretation_kind": "inference",
            },
        ],
        "rewatch": [
            {
                **_source_note(
                    "Review the request for a Monday coaching example.", evidence["practice_signal"]
                ),
                "purpose": "must_watch",
            },
            {
                **_source_note("Review the price concern and the response.", evidence["price"]),
                "purpose": "watch",
            },
            {
                **_source_note(
                    "Review the close request and acceptance.", evidence["agreed_next_step"]
                ),
                "purpose": "repeat",
            },
        ],
        "conversation_change": {
            "before": _source_note(
                "The prospect described stalled demos.",
                _evidence(rows, 5),
            ),
            "change": _source_note(
                "The prospect asked to see a practice example.",
                evidence["practice_signal"],
            ),
            "after": _source_note(
                "The prospect agreed to a walkthrough with a director.",
                evidence["agreed_next_step"],
            ),
            "possible_effect": (
                "A focused example could connect the initial problem to theagreed follow-up."
            ),
            "interpretation_kind": "inference",
        },
        "ethics_notes": [
            _source_note(
                "This call and report are fictional development fixtures.",
                evidence["discovery"],
            ),
            _source_note(
                "The report is not an official score or adjudicated assessment.",
                evidence["agreed_next_step"],
            ),
        ],
        "next_call_focus": {
            "improvement_index": 0,
            "behavior": (
                "Ask one question about the prospect's Monday review"
                "workflow before showing a feature."
            ),
            "target": "Use the requested example to test fit with the prospect's stated routine.",
        },
        "practice": {
            "improvement_index": 0,
            "instructions": (
                "Rehearse asking which recent call the prospect would like"
                "to review, then show one source-linked moment."
            ),
            "success_condition": (
                "The question names the buyer's workflow and the exampleaddresses the answer."
            ),
        },
        "progress": None,
        "final_assessment": {
            "repeat": "Keep the focused discovery question and the specific close request.",
            "fix_first": (
                "Explore the requested practice example before continuingthe feature explanation."
            ),
            "next_focus": "Use the buyer's own review workflow to shape the follow-up.",
            "assessment": (
                "Fictional draft for report UI work; not an official scoreor human adjudication."
            ),
        },
    }


def _fictional_report(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence = {
        "discovery": _evidence(rows, 2),
        "review_time": _evidence(rows, 7),
        "practice_signal": _evidence(rows, 13),
        "practice_response": _evidence(rows, 14),
        "score_concern": _evidence(rows, 15),
        "price": _evidence(rows, 19),
        "value_concern": _evidence(rows, 21),
        "buying_signal": _evidence(rows, 23),
        "close_attempt": _evidence(rows, 24),
        "agreed_next_step": _evidence(rows, 25),
        "recap": _evidence(rows, 26),
    }
    report: dict[str, Any] = {
        "summary": (
            "Fictional sample, not an official score: Noah described stalled demos and a Friday "
            "review burden, raised a price concern, and agreed to a Thursday workflow walkthrough."
        ),
        "strengths": [
            {
                "title": "Connects the problem to review time",
                "explanation": (
                    "The question about team time led the prospect to describe"
                    "a Friday review burden."
                ),
                "evidence": [evidence["review_time"]],
            },
            {
                "title": "Makes a clear close attempt",
                "explanation": (
                    "The closer proposed a short workflow walkthrough, and the"
                    "prospect accepted the meeting."
                ),
                "evidence": [evidence["close_attempt"], evidence["agreed_next_step"]],
            },
        ],
        "missed_opportunities": [
            {
                "title": "Explore the requested practice example",
                "explanation": (
                    "The prospect asked to see an example for Monday coaching."
                    "The response described features but did not ask which call"
                    "would make the example useful."
                ),
                "evidence": [evidence["practice_signal"], evidence["practice_response"]],
            },
            {
                "title": "Clarify the director's proof requirement",
                "explanation": (
                    "The prospect offered to bring a proposal to a director if"
                    "the workflow saves an hour. The close moved to scheduling"
                    "without clarifying what evidence the director needs."
                ),
                "evidence": [evidence["buying_signal"], evidence["close_attempt"]],
            },
        ],
        "improvements": [
            {
                "title": "Shape the example around Monday coaching",
                "explanation": (
                    "Ask which recent call the prospect would use, then show"
                    "one source-linked moment from that workflow."
                ),
                "evidence": [evidence["practice_signal"]],
            },
            {
                "title": "Respond to price with the buyer's own time data",
                "explanation": (
                    "Ask how many review hours are typical and what evidence"
                    "would make a proposal useful. No savings estimate is"
                    "established in this fictional call."
                ),
                "evidence": [evidence["price"], evidence["review_time"]],
            },
        ],
        "objection_analysis": [
            {
                "title": "Price exceeded expectation",
                "explanation": (
                    "The prospect said the monthly price was higher than"
                    "expected and wanted to compare it with current coaching"
                    "hours."
                ),
                "evidence": [evidence["price"]],
            },
            {
                "title": "Value must be shown in the workflow",
                "explanation": (
                    "The prospect said another dashboard would not save review"
                    "time. The response would be stronger with a buyer-specific"
                    "example."
                ),
                "evidence": [evidence["value_concern"], evidence["practice_response"]],
            },
        ],
        "closing_analysis": [
            {
                "title": "Specific walkthrough request",
                "explanation": (
                    "The closer proposed a twenty-minute walkthrough focused onreview time."
                ),
                "evidence": [evidence["close_attempt"]],
            },
            {
                "title": "Next step and attendee confirmed",
                "explanation": (
                    "The prospect accepted Thursday morning and offered to"
                    "invite a director; the closer recapped the outline and"
                    "time."
                ),
                "evidence": [evidence["agreed_next_step"], evidence["recap"]],
            },
        ],
        "verdict": (
            "Fictional draft, not an official score: the prospect described the price concern, "
            "named a review-time outcome, and agreed to a walkthrough. The report does not "
            "establish actual savings, conversion impact, or a buying decision."
        ),
        "review_status": "draft_not_dipak_adjudicated",
        "overview": _overview(rows),
    }
    return report


class FictionalReportingBroker:
    """Implements the broker protocol without network access or credentials."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        provider = reservation.quote.provider_id
        if provider in {"elevenlabs", "deepgram"}:
            text, words = _transcript_words(provider)
            if provider == "elevenlabs":
                data: dict[str, Any] = {"text": text, "words": words}
            else:
                data = {
                    "results": {
                        "channels": [{"alternatives": [{"transcript": text, "words": words}]}]
                    }
                }
        else:
            body = json.loads(payload)
            user = (
                body["contents"][0]["parts"][0]["text"]
                if provider == "gemini"
                else body["messages"][1]["content"]
            )
            if user.startswith("{"):
                request = json.loads(user)
                segments = request["segments"]
                observations = [
                    {
                        "fact": "The speaker described a concrete call workflow.",
                        "segment_id": segment["id"],
                        "quote": segment["text"],
                    }
                    for segment in segments[::3]
                ]
                data = {
                    "overview": (
                        "A fictional sales conversation with discovery, a price"
                        "concern, and a proposed next step."
                    ),
                    "observations": observations,
                    "uncertainties": ["Speaker labels are synthetic and not identity evidence."],
                }
            else:
                facts = json.loads(user.split("\n", 1)[1])
                context = facts["source_context"]
                rows = _rows_by_id(context)
                report = _fictional_report(rows)
                text = json.dumps(report, ensure_ascii=False)
                data = (
                    {
                        "candidates": [
                            {
                                "finishReason": "STOP",
                                "content": {"role": "model", "parts": [{"text": text}]},
                            }
                        ]
                    }
                    if provider == "gemini"
                    else {"choices": [{"message": {"content": text}}]}
                )
        raw = canonical(data)
        return ProviderResult(
            provider=provider,
            model=reservation.quote.provider_model,
            request_id=f"fictional-sample-{hashlib.sha256(payload).hexdigest()[:16]}",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=data,
            usage=dict(_FAKE_ZERO_USAGE),
            input_sha256=reservation.quote.input_sha256,
        )
