"""The one-pass pipeline's pure parts: transcript contract, one answer onto six contracts,
prices, the mode switch, the Gemini transports and the comparison.

No database, no network, no key. Every transcript line is fictional.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from ac_platform.admin_settings.registry import SETTINGS, pointer, request_body
from ac_platform.ai_spend import policy
from ac_platform.call_data import taxonomy
from ac_platform.conversation_intelligence import pointer_review
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_V5_MARKER,
    load_report_profile,
)
from ac_platform.one_pass import analysis, compare, pricing, settings, transcription
from ac_platform.one_pass.gemini import (
    GoogleGemini,
    OnePassFailure,
    OpenRouterBench,
    Request,
)
from tests.conversation_overview_fixtures import overview_for

SHA = "a" * 64
SEGMENTS = [
    {
        "speaker": "A",
        "start": "00:00",
        "end": "00:04",
        "text": "Namaste, main Rohan, Sales Xray se.",
    },
    {
        "speaker": "B",
        "start": "00:04",
        "end": "00:09",
        "text": "Haan ji, main Amit Sharma, XYZ Digital ka founder.",
    },
    {
        "speaker": "B",
        "start": "00:09",
        "end": "00:15",
        "text": "Team aath logon ki hai, revenue chaar lakh mahina.",
    },
    {
        "speaker": "B",
        "start": "00:15",
        "end": "00:20",
        "text": "Partner se baat karke Friday chaar baje bataunga.",
    },
    {
        "speaker": "A",
        "start": "00:20",
        "end": "00:20",
        "text": "Main Friday se pehle case study bhejta hoon.",
    },
]


def _transcript() -> dict[str, Any]:
    transcript, dropped = transcription.to_transcript(
        {"segments": SEGMENTS},
        source_sha256=SHA,
        duration_ms=24_000,
        response_sha256="b" * 64,
        model=settings.TRANSCRIPTION_MODEL,
    )
    assert dropped == {}
    return transcript


def _report() -> dict[str, Any]:
    finding = {
        "title": "Ask what the partner needs",
        "explanation": "The prospect will decide with a partner. Ask what would help them decide.",
        "evidence": [{"segment_id": "s4"}],
    }
    dimensions = []
    for index, dimension in enumerate(load_report_profile()["dimensions"]):
        observed = index == 0
        dimensions.append(
            {
                "dimension_id": dimension["id"],
                "status": "observed" if observed else "insufficient_evidence",
                "observation": "You learnt the team size and revenue."
                if observed
                else "The call does not establish this.",
                "evidence": [{"segment_id": "s3"}] if observed else [],
            }
        )
    report = {
        "summary": "A short discovery call; the prospect decides with a partner on Friday.",
        "strengths": [finding],
        "missed_opportunities": [],
        "improvements": [finding],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "Follow up on Friday with the case study.",
        "review_status": "draft_not_dipak_adjudicated",
        "dimensions": dimensions,
    }
    report["overview"] = overview_for(report)
    return report


def _review() -> dict[str, Any]:
    return {
        "score_line": "A friendly start; the next step is clear.",
        "pointers": [
            {
                "id": pointer_id,
                "status": "good" if number % 2 else "not_observed",
                "score": 75 if number % 2 else None,
                "what_happened": "You introduced yourself.",
                "why_it_matters": "It sets the tone." if number % 2 else None,
                "evidence": ["s1"] if number % 2 else [],
                "how_to_improve": ["Say why you are calling."] if number % 2 else [],
                "training_topic": "Openings" if number % 2 else None,
            }
            for number, pointer_id in enumerate(pointer_review.POINTER_IDS, 1)
        ],
        "outcome": {
            "stages": ["Initial Contact", "Discovery"],
            "reasons": ["The partner decides too."],
            "objections": [],
            "next_steps": [
                {"text": "Decide after partner talk", "owner": "prospect", "when": "Friday 4 PM"}
            ],
            "notes": [],
            "suggested_action": "Send the case study before Friday.",
        },
        "buyer_qualification": {
            item: {"state": "unknown", "evidence": [], "note": None}
            for item in pointer_review.QUALIFICATION
        },
        "prospect": {
            "insights": [{"kind": "team", "text": "A team of eight.", "evidence": ["s3"]}],
            "quality": {"score": 7, "reason": "Clear need."},
            "fit": {"value": "possible", "reason": "Small team."},
            "urgency": {"value": "medium", "reason": "Friday decision."},
        },
    }


def _answer() -> dict[str, Any]:
    return {
        "call_data": {
            "speakers": [
                {"speaker_id": "speaker_0", "role": "salesperson"},
                {"speaker_id": "speaker_1", "role": "prospect"},
            ],
            "facts": [
                {
                    "type": "person.name",
                    "value": {"text": "Amit Sharma"},
                    "confidence": 0.97,
                    "basis": "observed",
                    "segments": ["s2"],
                },
                {
                    "type": "company.name",
                    "value": {"text": "XYZ Digital"},
                    "confidence": 0.95,
                    "basis": "observed",
                    "segments": ["s2"],
                },
                {
                    "type": "commitment.follow_up",
                    "value": {
                        "text": "Friday 4 PM",
                        "date": "2026-10-23",
                        "time": "16:00",
                        "purpose": "Decision after partner talk",
                    },
                    "confidence": 0.9,
                    "basis": "observed",
                    "segments": ["s4"],
                },
                {
                    "type": "nonsense.type",
                    "value": {"text": "x"},
                    "confidence": 1,
                    "basis": "observed",
                    "segments": ["s1"],
                },
            ],
        },
        "notes": [
            {"fact": "Team of eight people", "segments": ["s3"]},
            {"fact": "Not in the transcript", "segments": ["s99"]},
        ],
        "review": _review(),
        "report": _report(),
    }


# ----- transcription ------------------------------------------------------------------


def test_clock_reads_minutes_seconds_hours_and_refuses_the_rest() -> None:
    assert transcription.clock_ms("01:02") == 62_000
    assert transcription.clock_ms("75:10") == 4_510_000
    assert transcription.clock_ms("1:02:03") == 3_723_000
    assert transcription.clock_ms("00:01.5") == 1_500
    assert transcription.clock_ms("soon") is None
    assert transcription.clock_ms(12) is None


def test_the_answer_becomes_the_c2_contract() -> None:
    transcript = _transcript()
    segments = transcript["segments"]
    assert [s["id"] for s in segments] == ["s1", "s2", "s3", "s4", "s5"]
    assert [s["speaker_id"] for s in segments] == [
        "speaker_0",
        "speaker_1",
        "speaker_1",
        "speaker_1",
        "speaker_0",
    ]
    # An end that is not after its start is repaired, inside the call.
    assert segments[-1]["start_ms"] == 20_000 and 20_000 < segments[-1]["end_ms"] <= 24_000
    assert transcript["timebase_id"] == transcription.TIMEBASE
    assert transcript["speaker_identity"] == "unverified_provider_labels"
    assert len(transcript["revision"]) == 64 and transcript["source_sha256"] == SHA


def test_transcript_drops_unreadable_rows_and_refuses_an_empty_answer() -> None:
    transcript, dropped = transcription.to_transcript(
        {
            "segments": [
                *SEGMENTS[:2],
                {"speaker": "A", "start": "x", "end": "y", "text": "hi"},
                {"speaker": "A", "start": "00:30", "end": "00:31", "text": "late"},
                {"speaker": "B", "start": "00:01", "text": "  "},
            ]
        },
        source_sha256=SHA,
        duration_ms=24_000,
        response_sha256="c" * 64,
        model="m",
    )
    assert len(transcript["segments"]) == 2
    assert dropped == {"time": 1, "after_end": 1, "empty": 1}
    with pytest.raises(OnePassFailure, match="transcript_empty"):
        transcription.to_transcript(
            {"segments": []}, source_sha256=SHA, duration_ms=None, response_sha256="c", model="m"
        )


# ----- one answer onto the six contracts -------------------------------------------------


def test_two_strict_requests_carry_each_stages_own_instructions_and_schema() -> None:
    requests = analysis.requests(_transcript(), call_date="Tuesday 20 October 2026")
    assert set(requests) == {"facts", "report"}
    facts, report = requests["facts"], requests["report"]
    assert facts.system.startswith("ONE_PASS: " + analysis.PROMPT_REVISION)
    assert pointer_review.PROMPT_REVISION in facts.system  # the pointer review's own
    assert "Value shapes by kind:" in facts.system  # the call data extraction's own
    assert "prospect_profile" not in facts.system  # its facts come from call_data here
    assert COACHING_PROMPT_V5_MARKER in report.system  # the C5 stage's own prompt
    assert COACHING_PROMPT_V5_MARKER not in facts.system
    assert facts.schema is not None and report.schema is not None
    assert facts.schema["required"] == ["call_data", "notes", "review"]
    assert "prospect" in facts.schema["properties"]["review"]["properties"]
    assert "prospect_profile" not in facts.schema["properties"]["review"]["properties"]
    assert report.schema["required"] == ["report"] and "dimension" in report.schema["$defs"]
    types = facts.schema["properties"]["call_data"]["properties"]["facts"]["items"]["properties"]
    assert set(types["type"]["enum"]) == {t.key for t in taxonomy.DEEP_EXTRACT_TYPES}
    # Both read the same transcript rows, sent at once.
    assert facts.user == report.user
    assert facts.user.startswith("Call date: Tuesday 20 October 2026.")
    assert "[s2] speaker_1 00:04: Haan ji" in facts.user
    # The trial may send a refused schema as text; publishing never does.
    assert facts.schema_fallback and report.schema_fallback
    # The instructions are the same for every call: a shared prefix the cache can reuse.
    other = analysis.requests(_transcript(), call_date="Monday 1 January 2027")
    assert other["facts"].system == facts.system and other["report"].system == report.system


def test_the_trial_asks_compact_json_and_lean_text() -> None:
    requests = analysis.requests(_transcript(), call_date="Tuesday 20 October 2026")
    facts, report = requests["facts"], requests["report"]
    compact = "Write the JSON compact, on one line"
    assert compact in facts.system and compact in report.system
    # Shorter pointer text; no tip for an excellent pointer; the topic is the label.
    assert "one short sentence, at most 20 words, on what you did" in facts.system
    assert "one or two sentences on what you did" not in facts.system
    assert "[]\n  when excellent or not judged, 1 when good" in facts.system
    assert "training_topic" not in facts.system
    assert facts.schema is not None
    entry = facts.schema["properties"]["review"]["properties"]["pointers"]["items"]
    assert "training_topic" not in entry["properties"]
    assert "training_topic" not in entry["required"]
    assert set(entry["required"]) == set(entry["properties"])
    # The C5 instructions stay whole; the length limits come after them.
    assert report.system.index(COACHING_PROMPT_V5_MARKER) < report.system.index("LENGTH (one pass)")
    # Publishing and the plan's C4 request keep the review's own text, compact.
    published = analysis.requests(_transcript(), call_date="Tuesday 20 October 2026", publish=True)[
        "facts"
    ]
    for system in (published.system, analysis.stage_system_prompt()):
        assert compact in system
        assert "training_topic: a short lesson title" in system
        assert "LENGTH (one pass)" not in system


def test_the_lean_review_refuses_a_changed_pointer_review_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pointer_review._system_prompt

    def changed(roles: dict[str, str]) -> str:
        return original(roles).replace("one or two sentences", "two sentences")

    analysis.review_instructions.cache_clear()
    monkeypatch.setattr(pointer_review, "_system_prompt", changed)
    try:
        with pytest.raises(analysis.AnalysisError, match="pointer_review_prompt_changed"):
            analysis.review_instructions()
    finally:
        analysis.review_instructions.cache_clear()


def test_a_lean_review_takes_each_pointers_label_as_its_training_topic() -> None:
    transcript = _transcript()
    answer = _answer()
    for entry in answer["review"]["pointers"]:
        entry.pop("training_topic")
    outputs, checks = analysis.map_outputs(answer, transcript)
    assert analysis.contracts_ok(checks) == 6
    pointers = outputs["pointer_review"]["pointers"]
    judged = [p for p in pointers if p["score"] is not None]
    assert judged and all(p["training_topic"] == p["label"] for p in judged)
    assert all(p["training_topic"] is None for p in pointers if p["score"] is None)
    # A review that writes its own topic (publishing, the plan) keeps it.
    outputs, _ = analysis.map_outputs(_answer(), transcript)
    assert {p["training_topic"] for p in outputs["pointer_review"]["pointers"]} == {
        "Openings",
        None,
    }


def test_publishing_asks_one_strict_request_with_the_reviews_own_profile() -> None:
    requests = analysis.requests(_transcript(), call_date="Tuesday 20 October 2026", publish=True)
    assert set(requests) == {"facts"}
    facts = requests["facts"]
    assert not facts.schema_fallback
    assert facts.system.count(pointer_review.PROMPT_REVISION) == 1
    assert "And return prospect_profile" in facts.system  # the review's own, in full
    assert "PART notes" not in facts.system
    assert facts.schema is not None
    assert facts.schema["required"] == ["call_data", "review"]
    assert facts.schema["properties"]["review"] == pointer_review.response_schema()


def test_a_publishing_answer_gives_the_deep_drafts_and_the_reviews_raw_part() -> None:
    transcript = _transcript()
    answer = _answer()
    review = answer["review"]
    review.pop("prospect")
    review["prospect_profile"] = {
        "name": {"value": "Amit Sharma", "evidence": ["s2"]},
        "insights": [{"kind": "team", "text": "A team of eight.", "evidence": ["s3"]}],
    }
    published = analysis.map_publish(
        {"call_data": answer["call_data"], "review": review}, transcript
    )
    assert published.checks == {
        "call_objects": "ok",
        "prospect_facts": "ok",
        "pointer_review": "ok",
    }
    assert {d.type_key for d in published.drafts} == {
        "person.name",
        "company.name",
        "commitment.follow_up",
    }
    assert published.roles == {"speaker_0": "salesperson", "speaker_1": "prospect"}
    raw = published.outputs["review_raw"]
    assert raw["prospect_profile"]["name"]["value"] == "Amit Sharma"
    # Parsed again against the saved report's transcript when it is published.
    again = pointer_review.parse_review(raw, transcript["segments"])
    assert len(again["pointers"]) == 27
    broken = analysis.map_publish({"call_data": {}, "review": {"pointers": []}}, transcript)
    assert broken.checks["call_objects"] == "none_valid" and not broken.drafts
    assert broken.checks["pointer_review"] != "ok" and "review_raw" not in broken.outputs


def test_every_contract_validates_from_one_answer() -> None:
    transcript = _transcript()
    outputs, checks = analysis.map_outputs(_answer(), transcript)
    assert "review_raw" not in outputs  # only a publishing read keeps it
    assert checks == {
        "c2": "ok",
        "call_objects": "ok",
        "prospect_facts": "ok",
        "c5": "ok",
        "c4": "ok",
        "pointer_review": "ok",
    }
    assert analysis.contracts_ok(checks) == 6
    objects = {o["type_key"]: o for o in outputs["call_objects"]}
    assert set(objects) == {"person.name", "company.name", "commitment.follow_up"}
    assert objects["person.name"]["evidence"][0]["quote"] == transcript["segments"][1]["text"]
    assert objects["person.name"]["pipeline"] == "fast"
    assert outputs["call_objects_dropped"] == {"unknown_type": 1}
    assert outputs["roles"] == {"speaker_0": "salesperson", "speaker_1": "prospect"}
    packet = outputs["c4"]
    assert packet["schema"] == "ac.sales-xray.style-independent-facts/1"
    statements = [o["statement"] for o in packet["observations"]]
    assert "Name: Amit Sharma" in statements and "Team of eight people" in statements
    assert "Not in the transcript" not in statements
    assert packet["overview"].startswith("A short discovery call")
    review = outputs["pointer_review"]
    assert len(review["pointers"]) == 27 and review["overall"]["score"] == 75
    profile = review["prospect_profile"]
    assert profile["name"]["value"] == "Amit Sharma"
    assert profile["follow_up"]["when"] == "Friday 4 PM"
    assert profile["fit"]["value"] == "possible"
    assert outputs["c5"]["dimensions"][0]["evidence"][0]["segment_id"] == "s3"
    facts = outputs["prospect_facts"]
    assert facts["schema"] == "prospect-facts/1"
    assert {f["prospect_field"] for f in facts["facts"]} >= {"name", "business"}


def test_a_part_that_fails_its_own_validator_leaves_the_others_standing() -> None:
    answer = _answer()
    answer["report"]["dimensions"] = answer["report"]["dimensions"][:3]
    answer["review"]["pointers"] = answer["review"]["pointers"][:5]
    outputs, checks = analysis.map_outputs(answer, _transcript())
    assert checks["c5"] != "ok" and "c5" not in outputs
    assert checks["pointer_review"] == "pointer_review_pointers_incomplete"
    assert checks["c4"] == "ok" and checks["call_objects"] == "ok"
    # Without a report the fact packet still has an overview.
    assert outputs["c4"]["overview"]


def test_withheld_segments_never_reach_the_contracts() -> None:
    outputs, _ = analysis.map_outputs(_answer(), _transcript(), withheld=frozenset({"s2"}))
    assert {o["type_key"] for o in outputs["call_objects"]} == {"commitment.follow_up"}


# ----- prices ---------------------------------------------------------------------------


def test_usage_and_list_price_rupees() -> None:
    usage = pricing.usage_from_gemini(
        {
            "promptTokenCount": 30_000,
            "candidatesTokenCount": 7_000,
            "thoughtsTokenCount": 200,
            "promptTokensDetails": [
                {"modality": "AUDIO", "tokenCount": 28_800},
                {"modality": "TEXT", "tokenCount": 1_200},
            ],
        }
    )
    assert (usage.prompt, usage.audio, usage.billed_output) == (30_000, 28_800, 7_200)
    # 28,800 audio at $0.50 + 1,200 text at $0.25 + 7,200 out at $1.50, per million, at ₹100.
    assert pricing.cost_inr("gemini-3.1-flash-lite", usage, tier="standard") == Decimal("2.5500")
    assert pricing.cost_inr("gemini-3.1-flash-lite", usage, tier="flex") == Decimal("1.2750")
    cached = pricing.Usage(prompt=10_000, cached=8_000, output=1_000)
    # 2,000 at $0.75 + 8,000 at a tenth + 1,000 at $3.75.
    assert pricing.cost_inr("gemini-3.8-flash", cached, tier="standard") == Decimal("0.5850")
    assert pricing.cost_inr("unknown-model", cached, tier="standard") == Decimal("0.5850")
    assert pricing.per_minute(Decimal("3"), 120_000) == 1.5
    assert pricing.usage_from_gemini(None) == pricing.Usage()


# ----- the switch ------------------------------------------------------------------------


def test_mode_is_classic_by_default_both_on_development_one_pass_where_call_data_runs() -> None:
    assert settings.validate("development", {}) == settings.defaults()
    assert settings.defaults()["mode"] == "classic"
    assert settings.validate("development-live", {"mode": "both"})["mode"] == "both"
    for environment in ("staging", "production"):
        with pytest.raises(settings.SettingsError, match="mode_not_here"):
            settings.validate(environment, {"mode": "both"})
        assert settings.validate(environment, {"mode": "classic"})["mode"] == "classic"
        # Standard only there for now (owner, 21 Oct 2026); Flex after a latency check.
        with pytest.raises(settings.SettingsError, match="analysis_tier_standard_only"):
            settings.validate(environment, {"analysis_tier": "flex"})
    assert settings.validate("staging", {"mode": "one_pass"})["mode"] == "one_pass"
    # Production runs no call data engine: its one-pass saving is the transcription route.
    with pytest.raises(settings.SettingsError, match="mode_not_here"):
        settings.validate("production", {"mode": "one_pass"})
    assert settings.validate("development", {"analysis_tier": "flex"})["analysis_tier"] == "flex"
    assert settings.needs_owner("one_pass")
    assert not settings.needs_owner("classic") and not settings.needs_owner("both")
    for bad in (
        {"mode": "fast"},
        {"surprise": 1},
        {"transcription_tier": "batch"},
        {"max_call_minutes": 0},
        {"max_call_minutes": True},
        {"max_call_minutes": 121},
    ):
        with pytest.raises(settings.SettingsError):
            settings.validate("development", bad)
    view = settings.public("staging", settings.defaults(), None)
    modes = {m["value"]: m for m in view["modes"]}
    assert modes["classic"]["why_not"] is None and modes["both"]["why_not"]
    assert modes["one_pass"]["why_not"] is None and modes["one_pass"]["needs_owner"]
    assert view["confirm"] == "one_pass"
    production = settings.public("production", settings.defaults(), None)
    reasons = {m["value"]: m["why_not"] for m in production["modes"]}
    assert "Flash-Lite" in reasons["one_pass"] and reasons["classic"] is None


@pytest.mark.parametrize("item", [s for s in SETTINGS if s.area == "analysis-pipeline"])
def test_registry_changes_pass_the_switchs_own_validation(item) -> None:
    answer = settings.public("development", settings.defaults(), 2)
    assert item.write is not None
    if item.kind == "int":
        for good in (item.minimum, item.maximum):
            body = request_body(item, answer, good)
            assert body["expected_revision"] == 2
            assert settings.validate("development", body["config"])["max_call_minutes"] == good
        for bad in (item.minimum - 1, item.maximum + 1):
            with pytest.raises(settings.SettingsError):
                settings.validate("development", request_body(item, answer, bad)["config"])
        return
    assert item.options_from is not None
    menu = pointer(answer, item.options_from[0])
    # one_pass is the owner's action on its own page (typed confirm), never a menu pick.
    values = [
        entry[item.options_from[1]]
        for entry in menu
        if not entry.get("why_not") and not entry.get("needs_owner")
    ]
    assert values
    reason = "Owner asked for the comparison" if item.write.needs_reason else None
    for value in values:
        body = request_body(item, answer, value, reason=reason)
        key = item.write.merge.key[0] if item.write.merge else ""
        assert settings.validate("development", body["config"])[key] == value


def test_ai_spend_knows_one_pass_and_starts_its_cap_at_zero() -> None:
    assert "one_pass" in policy.BACKGROUND and "one_pass" in policy.CAPPED_HERE
    for environment in policy.ENVIRONMENTS:
        assert policy.defaults(environment)["feature_caps_inr"]["one_pass"] == 0
    raised = policy.with_cap(policy.defaults("development"), "one_pass", 200)
    assert policy.validate("development", raised)["feature_caps_inr"]["one_pass"] == 200


# ----- transports --------------------------------------------------------------------


def _gemini_answer(payload: dict[str, Any], finish: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": finish}
        ],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


def _request(**overrides: Any) -> Request:
    return Request(
        **{
            "system": "S",
            "user": "U",
            "schema": {"type": "object"},
            "max_output_tokens": 100,
            **overrides,
        }
    )


def test_flex_retries_then_falls_back_to_standard_once() -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("service_tier") == "flex":
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}})
        return httpx.Response(200, json=_gemini_answer({"ok": True}))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    gemini = GoogleGemini("key", client=client, sleep=lambda _: None)
    reply = gemini.generate(model="gemini-3.8-flash", request=_request(), tier="flex")
    assert reply.data == {"ok": True} and reply.tier_used == "flex_fell_back"
    assert [b.get("service_tier") for b in seen] == ["flex", "flex", "flex", None]
    assert seen[-1]["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert reply.usage.prompt == 100 and reply.attempts == 4


def test_a_refused_schema_goes_as_text_and_audio_goes_inline() -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if "responseJsonSchema" in body["generationConfig"]:
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        return httpx.Response(200, json=_gemini_answer({"ok": 1}))

    client = httpx.Client(transport=httpx.MockTransport(handle))
    gemini = GoogleGemini("key", client=client, sleep=lambda _: None)
    reply = gemini.generate(
        model="gemini-3.1-flash-lite",
        request=_request(audio=b"ID3audio", audio_mime="audio/mpeg"),
        tier="standard",
    )
    assert reply.schema_mode == "prompt" and reply.tier_used == "standard"
    parts = seen[-1]["contents"][0]["parts"]
    assert parts[0]["inline_data"]["mime_type"] == "audio/mpeg" and parts[1] == {"text": "U"}
    assert "JSON schema" in seen[-1]["systemInstruction"]["parts"][0]["text"]


def test_publishing_never_sends_a_refused_schema_as_text() -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(OnePassFailure, match="schema_refused"):
        GoogleGemini("key", client=client, sleep=lambda _: None).generate(
            model="gemini-3.8-flash", request=_request(schema_fallback=False), tier="standard"
        )
    assert len(seen) == 1 and "responseJsonSchema" in seen[0]["generationConfig"]


def test_answers_cut_short_or_unreadable_fail_with_fixed_codes() -> None:
    for payload, code in (
        (_gemini_answer({"a": 1}, finish="MAX_TOKENS"), "answer_too_long"),
        ({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}, "unreadable_answer"),
        ({"nothing": True}, "unreadable_response"),
    ):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda _r, p=payload: httpx.Response(200, json=p))
        )
        with pytest.raises(OnePassFailure, match=code):
            GoogleGemini("key", client=client).generate(
                model="gemini-3.8-flash", request=_request(), tier="standard"
            )
    with pytest.raises(OnePassFailure, match="credential_missing"):
        GoogleGemini("").generate(model="m", request=_request(), tier="standard")
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(403, json={})))
    with pytest.raises(OnePassFailure, match="provider_http_403"):
        GoogleGemini("key", client=client).generate(model="m", request=_request(), tier="standard")


def test_the_benchmark_route_stays_on_google_and_counts_audio_tokens() -> None:
    seen: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"segments": []}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2_000, "completion_tokens": 300},
            },
        )

    bench = OpenRouterBench("key", client=httpx.Client(transport=httpx.MockTransport(handle)))
    reply = bench.generate(
        model="gemini-3.1-flash-lite",
        request=_request(audio=b"mp3", audio_mime="audio/mpeg", audio_seconds=60.0),
        tier="standard",
    )
    body = seen[0]
    assert body["model"] == "google/gemini-3.1-flash-lite"
    assert body["provider"] == {
        "order": ["google-ai-studio"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    assert body["messages"][1]["content"][0]["input_audio"]["format"] == "mp3"
    assert reply.usage.audio == 1_920  # 32 tokens a second
    with pytest.raises(OnePassFailure, match="bench_audio_format"):
        bench.generate(
            model="m", request=_request(audio=b"x", audio_mime="audio/flac"), tier="standard"
        )


# ----- comparison --------------------------------------------------------------------


def _side(
    objects: list[dict[str, Any]], statuses: list[str], scores: list[int | None], inr: float
) -> dict[str, Any]:
    return {
        "available": True,
        "audio_ms": 600_000,
        "duration_ms": 90_000,
        "cost_inr": inr,
        "objects": objects,
        "pointers": {
            "overall": 70,
            "rows": [
                {"id": f"p{i}", "label": f"P{i}", "status": s, "score": c}
                for i, (s, c) in enumerate(zip(statuses, scores, strict=True))
            ],
        },
        "coaching": {
            "strengths": ["a"],
            "improvements": ["b"],
            "missed_opportunities": [],
            "objections": [],
            "closing": [],
            "dimensions": [{"id": "d1", "status": "observed"}, {"id": "d2", "status": "unknown"}],
        },
        "transcript": {"words": 10, "speakers": 2, "rows": [{"text": "hello there friend"}]},
        "checks": {
            "c2": "ok",
            "c4": "ok",
            "c5": "ok",
            "pointer_review": "ok",
            "call_objects": "ok",
            "prospect_facts": "ok",
        },
        "judge": {"fact_recall": 0.8},
    }


def test_differences_match_facts_by_wording_and_compare_pointers_and_dimensions() -> None:
    name = {"type": "person.name", "label": "Name"}
    classic = _side(
        [
            {**name, "display": "Amit Sharma"},
            {"type": "company.name", "label": "Company", "display": "XYZ"},
        ],
        ["good", "average", "not_observed"],
        [75, 55, None],
        16.4,
    )
    one = _side(
        [
            {**name, "display": "amit sharma"},
            {"type": "money.budget", "label": "Budget", "display": "4 lakh"},
        ],
        ["good", "good", "not_observed"],
        [80, 72, None],
        4.1,
    )
    result = compare.compare(classic, one)
    differences = result["differences"]
    facts = differences["facts"]
    assert (
        len(facts["both"]) == 1
        and len(facts["only_classic"]) == 1
        and len(facts["only_one_pass"]) == 1
    )
    assert facts["overlap"] == pytest.approx(1 / 3, abs=1e-3)
    pointers = differences["pointers"]
    assert (pointers["same_status"], pointers["compared"]) == (2, 3)
    assert pointers["mean_score_gap"] == 11.0
    assert differences["coaching"]["dimension_agreement"] == 1.0
    assert differences["cost_saving_inr"] == pytest.approx(12.3)
    summary = compare.summarise([{**result, "subject": {"kind": "bench"}}])
    assert summary["calls"] == 1 and summary["audio_minutes"] == 10.0
    assert summary["classic"]["per_minute_inr"] == pytest.approx(1.64)
    assert summary["one_pass"]["per_minute_inr"] == pytest.approx(0.41)
    assert summary["one_pass"]["contracts_passed"] == 6
    assert summary["agreement"]["pointer_status"] == pytest.approx(0.6667, abs=1e-3)
    assert compare.compare(None, one)["one_pass"] is one


def test_a_report_whose_overview_alone_fails_stands_without_it_and_is_marked() -> None:
    answer = _answer()
    answer["report"]["overview"] = {**answer["report"]["overview"], "progress": "doing well"}
    outputs, checks = analysis.map_outputs(answer, _transcript())
    assert checks["c5"] == "ok_without_overview"
    assert checks["c5_overview"].startswith("report_overview")
    assert "overview" not in outputs["c5"] and outputs["c5"]["summary"]
    assert analysis.contracts_ok(checks) == 5  # never counted as a full pass
