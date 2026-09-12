"""Authored synthetic example; no customer recording or generated sales score."""

from typing import Any


def example_report() -> dict[str, Any]:
    return {
        "id": "synthetic-example-v1",
        "title": "A conversation about the next step",
        "duration_ms": 60000,
        "state": "example",
        "provenance": "Authored fictional dialogue for interface testing; not ASR output.",
        "transcript": {
            "revision": "authored-v1",
            "segments": [
                {
                    "id": "u1",
                    "speaker_id": "seller",
                    "start_ms": 0,
                    "end_ms": 10000,
                    "text": (
                        "Before we look at the programme, what would you like to change "
                        "about your sales conversations?"
                    ),
                },
                {
                    "id": "u2",
                    "speaker_id": "prospect",
                    "start_ms": 10000,
                    "end_ms": 23000,
                    "text": (
                        "I can explain the offer, but I struggle "
                        "when someone asks me about the price."
                    ),
                },
                {
                    "id": "u3",
                    "speaker_id": "seller",
                    "start_ms": 23000,
                    "end_ms": 35000,
                    "text": "Could you walk me through the last time that happened?",
                },
                {
                    "id": "u4",
                    "speaker_id": "prospect",
                    "start_ms": 35000,
                    "end_ms": 48000,
                    "text": (
                        "They said they needed to think. I offered a discount before asking "
                        "what they wanted to think about."
                    ),
                },
                {
                    "id": "u5",
                    "speaker_id": "seller",
                    "start_ms": 48000,
                    "end_ms": 60000,
                    "text": (
                        "Let's start with that moment and practise "
                        "one follow-up question together."
                    ),
                },
            ],
        },
        "measurements": {"state": "not_measured", "channels": []},
        "profile": {
            "name": "Dipak · draft methodology",
            "declared_total": 100,
            "source_total": 95,
            "numeric_score": None,
            "state": "review_required",
        },
    }
