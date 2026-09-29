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


def fictional_audio(seed: int) -> bytes:
    """One second of a generated tone. No recording is loaded or stored in source."""
    output = BytesIO()
    samples = bytearray()
    frequency = 430 + (seed % 7) * 17
    for index in range(48_000):
        samples.extend(
            struct.pack(
                "<h", int(0.2 * 32_767 * math.sin(2 * math.pi * frequency * index / 48_000))
            )
        )
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48_000)
        stream.writeframes(bytes(samples))
    return output.getvalue()


def _overview(report: dict[str, Any]) -> dict[str, Any]:
    improvements = report["improvements"]
    return {
        "version": "dipak-14-point-v1",
        "diagnosis": None,
        "outcome": None,
        "strength_details": [
            {"finding_index": i, "why_it_matters": "A synthetic reason to repeat this."}
            for i, _ in enumerate(report["strengths"])
        ],
        "improvement_details": [
            {
                "finding_index": i,
                "what_happened": {"text": item["explanation"], "evidence": item["evidence"]},
                "why_it_matters": "The stated barrier needs clarification.",
                "replacement_behavior": "Ask one question about the stated barrier.",
                "business_impact": {
                    "status": "insufficient_data",
                    "missing_inputs": ["Comparable conversion history", "Lead volume"],
                },
            }
            for i, item in enumerate(improvements)
        ],
        "golden_moments": [],
        "missed_details": [],
        "prospect_interpretations": [],
        "rewatch": [],
        "conversation_change": None,
        "ethics_notes": [],
        "next_call_focus": None,
        "practice": None,
        "progress": None,
        "final_assessment": {
            "repeat": "Keep the supported strength.",
            "fix_first": "Not established.",
            "next_focus": "Not established.",
            "assessment": "Fictional sample draft for human review.",
        },
    }


class FictionalReportingBroker:
    """Implements the broker protocol without network access or credentials."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        provider = reservation.quote.provider_id
        if provider == "elevenlabs":
            data: dict[str, Any] = {
                "text": "hello buyer",
                "words": [
                    {"text": "hello", "start": 0.0, "end": 0.5, "speaker_id": "speaker_1"},
                    {"text": "buyer", "start": 0.5, "end": 0.9, "speaker_id": "speaker_1"},
                ],
            }
        elif provider == "deepgram":
            data = {
                "results": {
                    "channels": [
                        {
                            "alternatives": [
                                {
                                    "transcript": "hello buyer",
                                    "words": [
                                        {"word": "hello", "start": 0.0, "end": 0.5, "speaker": 0},
                                        {"word": "buyer", "start": 0.5, "end": 0.9, "speaker": 0},
                                    ],
                                }
                            ]
                        }
                    ]
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
                segment = json.loads(user)["segments"][0]
                data = {
                    "overview": "A fictional greeting is present.",
                    "observations": [
                        {
                            "fact": "The speaker greeted the buyer.",
                            "segment_id": segment["id"],
                            "quote": segment["text"],
                        }
                    ],
                    "uncertainties": ["The speaker labels have not been verified."],
                }
            else:
                facts = json.loads(user.split("\n", 1)[1])
                context = facts["source_context"]
                rows = {
                    row[0]: dict(zip(context["columns"], row, strict=True))
                    for row in context["rows"]
                }
                evidence = []
                for reference in facts["observations"][0]["evidence"]:
                    segment = rows[reference["segment_id"]]
                    evidence.append(
                        {
                            "segment_id": segment["id"],
                            "quote": segment["text"][
                                reference["quote_start"] : reference["quote_end"]
                            ],
                            "start_ms": segment["start_ms"],
                            "end_ms": segment["end_ms"],
                        }
                    )
                report: dict[str, Any] = {
                    "summary": "Fictional sample report for route verification.",
                    "strengths": [
                        {
                            "title": "A greeting is present",
                            "explanation": "This fictional transcript contains a greeting.",
                            "evidence": evidence,
                        }
                    ],
                    "missed_opportunities": [],
                    "improvements": [],
                    "objection_analysis": [],
                    "closing_analysis": [],
                    "verdict": "Fictional draft; human review is required.",
                    "review_status": "draft_not_dipak_adjudicated",
                }
                report["overview"] = _overview(report)
                data = report
            text = json.dumps(data, ensure_ascii=False)
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
            usage={},
            input_sha256=reservation.quote.input_sha256,
        )
