"""``sx.analysis_completed.v1`` body, built exactly per the contract (fictional data)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from ac_platform.partner_events.payload import (
    MAX_BODY_BYTES,
    CallContext,
    Extraction,
    Lead,
    Person,
    body_bytes,
    body_sha256,
    build_event,
    iso,
    summary_text,
)
from ac_platform.partner_events.quote_facts import FACT_TYPES

EVENT = UUID("6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11")
PREVIOUS = UUID("0f0f0f0f-0000-4000-8000-000000000001")
CONTEXT = CallContext(
    tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
    recording_id=UUID("22222222-2222-4222-8222-222222222222"),
    report_draft_id=UUID("33333333-3333-4333-8333-333333333333"),
    submission_id=UUID("44444444-4444-4444-8444-444444444444"),
    completed_at=datetime(2026, 10, 19, 5, 14, 2, 731_000, tzinfo=UTC),
    uploaded_at=datetime(2026, 10, 19, 5, 10, 40, tzinfo=UTC),
    duration_ms=611_600,
    report_language="en",
    summary="  The customer wants a 5 kW system; the salesperson sends a quotation today.  ",
    outcome_kind="follow_up",
    salesperson=Person(
        UUID("55555555-5555-4555-8555-555555555555"),
        "Salesperson A",
        "salesperson.a@example.test",
    ),
    lead=Lead(UUID("66666666-6666-4666-8666-666666666666"), "+910000000000", "Customer A", "Pune"),
    analysis_revision=2,
    supersedes_event_id=PREVIOUS,
)
FACT = {
    "type": "system_size",
    "status": "stated",
    "value": {"stated_as": "5 kW", "quantity": 5, "unit": "kW"},
    "source": {"segment_id": "s41", "t_start_sec": 190, "t_end_sec": 197, "speaker": "customer"},
}
APP = "https://salesxray.example.test/"


def test_golden_event_body() -> None:
    payload = build_event(
        EVENT, CONTEXT, Extraction("complete", "rooftop-solar-quote-v1", [FACT]), app_url=APP
    )
    assert payload == {
        "schema": "sx.analysis_completed.v1",
        "event_id": "6b6b1a0e-5f1c-4c7e-9a1d-2f0c9e3b7a11",
        "event_type": "analysis.completed",
        "occurred_at": "2026-10-19T05:14:02Z",
        "tenant_ref": "ten_11111111111141118111111111111111",
        "analysis_id": "sub_44444444444444448444444444444444",
        "analysis_revision": 2,
        "supersedes_event_id": "0f0f0f0f-0000-4000-8000-000000000001",
        "analysis_url": (
            "https://salesxray.example.test/analysis/calls/44444444-4444-4444-8444-444444444444"
        ),
        "call": {
            "uploaded_at": "2026-10-19T05:10:40Z",
            "duration_sec": 612,
            "report_language": "en",
        },
        "salesperson": {
            "ref": "per_55555555555545558555555555555555",
            "name": "Salesperson A",
            "email": "salesperson.a@example.test",
        },
        "lead": {
            "ref": "lead_66666666666646668666666666666666",
            "phone_e164": "+910000000000",
            "name": "Customer A",
            "city": "Pune",
        },
        # Every number in the summary reads "[n]"; the size arrives as a fact.
        "summary": "The customer wants a [n] kW system; the salesperson sends a quotation today.",
        "outcome": {"kind": "follow_up"},
        "extraction": {
            "profile": "rooftop-solar-quote-v1",
            "status": "complete",
            "looked_for": list(FACT_TYPES),
        },
        "facts": [FACT],
    }
    # Signed bytes are canonical JSON: the same stored payload always gives the same bytes.
    raw = body_bytes(payload)
    assert raw == body_bytes(json.loads(raw))
    assert body_sha256(payload) == hashlib.sha256(raw).hexdigest()
    assert "\\u" not in raw.decode()


def test_no_lead_no_outcome_skipped_and_failed_extractions() -> None:
    context = replace(CONTEXT, lead=None, outcome_kind="won_big", supersedes_event_id=None)
    skipped = build_event(EVENT, context, Extraction("skipped", None), app_url=APP)
    assert skipped["lead"] is None
    assert skipped["outcome"] == {"kind": None}
    assert skipped["supersedes_event_id"] is None
    assert skipped["extraction"] == {"profile": None, "status": "skipped", "looked_for": []}
    assert skipped["facts"] == []
    failed = build_event(
        EVENT, context, Extraction("failed", "rooftop-solar-quote-v1", [FACT]), app_url=APP
    )
    assert failed["extraction"]["status"] == "failed"
    assert failed["extraction"]["looked_for"] == list(FACT_TYPES)
    assert failed["facts"] == []
    unknown_length = build_event(
        EVENT, replace(CONTEXT, duration_ms=None), Extraction("skipped", None), app_url=APP
    )
    assert unknown_length["call"]["duration_sec"] is None


def test_summary_is_cut_to_1500_characters() -> None:
    long = replace(CONTEXT, summary="word " * 1000)
    payload = build_event(EVENT, long, Extraction("skipped", None), app_url=APP)
    assert len(payload["summary"]) == 1500
    assert payload["summary"].endswith("…")
    # Numbers are masked before the cut, so a cut never leaves part of a number.
    priced = build_event(
        EVENT,
        replace(CONTEXT, summary="Quoted ₹3.7L today. " * 200),
        Extraction("skipped", None),
        app_url=APP,
    )
    assert len(priced["summary"]) == 1500 and "3.7" not in priced["summary"]
    assert priced["summary"].startswith("Quoted [n] today. Quoted [n] today.")


@pytest.mark.parametrize(
    "summary,sent",
    [
        # Review 18 Oct, item 1 (blocker): the summary carried prices.
        (
            "Customer wants a 5 kW system; quoted 3.70 lakh plus GST, will pay ₹3,40,000.",
            "Customer wants a [n] kW system; quoted [n] plus GST, will pay [n].",
        ),
        ("Budget teen lakh sattar hazaar, packing 500 extra.", "Budget [n], packing [n] extra."),
        ("ग्राहक का बजट दो लाख साठ हजार है।", "ग्राहक का बजट [n] है।"),
        ("ग्राहकाचे बजेट पाच लाख पन्नास हजार आहे.", "ग्राहकाचे बजेट [n] आहे."),
        ("Deal paune teen lakh mein, sawa do lakh nahi.", "Deal [n] mein, [n] nahi."),
        ("सवा दो लाख तक जा सकते हैं।", "[n] तक जा सकते हैं।"),
        ("Wants it above a lakh; transport 45k, packing 500 rupiya.",
         "Wants it above [n]; transport [n], packing [n]."),
        # Round 3: sizes, years and areas go too; they arrive as facts.
        ("Install a 5 kW system by 2026 on the 1500 sq ft roof.",
         "Install a [n] kW system by [n] on the [n] sq ft roof."),
        # Re-review 18 Oct, B1: rupee-signed per-unit prices (the unit goes with the number).
        ("Salesperson quoted ₹45/W; competitor Rs.45/W, panels ₹55/Wp.",
         "Salesperson quoted [n]; competitor [n], panels [n]."),
        ("Price ₹60,000/kW for 5 kW, or 45 per watt.", "Price [n] for [n] kW, or [n] per watt."),
        ("₹45/watt incl GST, ₹ 50/Wp, ₹50Wp, ₨45/W, ₹ 45 /W.",
         "[n] incl GST, [n], [n], [n], [n] /W."),
        # Re-review 18 Oct, M1: Marathi case endings (report_language mr-Deva+en).
        ("ग्राहकाचे बजेट साडेतीन लाखांपर्यंत आहे.", "ग्राहकाचे बजेट [n] आहे."),
        ("तीन लाखांत 5 kW, सत्तर हजारांचा फरक, पाच लाखांचे बजेट.", "[n] kW, [n] फरक, [n] बजेट."),
        ("Budget 3 laakh, packing 3 hajaar.", "Budget [n], packing [n]."),
        # Re-review 18 Oct, minor: names stay; times, decimals and comma amounts go.
        ("Rupali 3 baje call karegi; quoted 3.70 for the 5 kW system.",
         "Rupali [n] baje call karegi; quoted [n] for the [n] kW system."),
        ("Dongle 1,999 only; one and a half lakh total; Rs: 50 packing.",
         "Dongle [n] only; [n] total; [n] packing."),
        # Check 3: per-watt prices in Hindi and Marathi, prices before their unit, number words.
        ("रेट 45 प्रति वॅट; दर ४५ प्रति वॉट; भाव 45.", "रेट [n] प्रति वॅट; दर [n] प्रति वॉट; भाव [n]."),
        ("Price per watt is 45; rate approx 45; Rs per watt 45; ₹/W 45.",
         "Price per watt is [n]; rate approx [n]; Rs per watt [n]; ₹/W [n]."),
        ("forty five per watt, price is twenty five, पस्तीस हजार, पैंतालीस रुपये प्रति वाट.",
         "[n] per watt, price is [n], [n], [n] प्रति वाट."),
        ("Transport 2000 extra; install on 18/10/2026 at 10:30.",
         "Transport [n] extra; install on [n] at [n]."),
        # Names and places stay.
        ("Rupesh and Lakhan from Kothrud; लाखन, हजारीबाग.",
         "Rupesh and Lakhan from Kothrud; लाखन, हजारीबाग."),
    ],
)  # fmt: skip
def test_every_number_in_the_summary_is_sent_as_n(summary: str, sent: str) -> None:
    payload = build_event(
        EVENT, replace(CONTEXT, summary=summary), Extraction("skipped", None), app_url=APP
    )
    assert payload["summary"] == sent
    assert not any(char.isdigit() for char in payload["summary"])
    assert summary_text(payload["summary"]) == payload["summary"]  # nothing left to mask


def test_a_body_over_256_kb_drops_its_facts_and_reads_failed() -> None:
    many = [
        {**FACT, "type": "load", "value": {"stated_as": "x" * 200}, "source": FACT["source"]}
        for _ in range(2000)
    ]
    payload = build_event(
        EVENT, CONTEXT, Extraction("complete", "rooftop-solar-quote-v1", many), app_url=APP
    )
    assert payload["extraction"]["status"] == "failed"
    assert payload["facts"] == []
    assert len(body_bytes(payload)) <= MAX_BODY_BYTES


def test_times_are_utc_whole_seconds() -> None:
    assert iso(datetime(2026, 10, 19, 10, 44, 2, 999_999)) == "2026-10-19T10:44:02Z"


# --- Check 4, 18 Oct (round 4): robustness and the summary's new cases ----------------------


@pytest.mark.parametrize(
    "summary,sent",
    [
        # Theoretical forms check 4 listed, closed by NFKC and zero-width removal.
        ("⁴⁵ per watt, ₄₅ per watt, ④⑤ per watt", "[n] per watt, [n] per watt, [n] per watt"),
        ("for‍ty five rupees, pach​pan rupaye", "[n], [n]"),
        ("Quoted ⁴⁵/W\ud800, NUL\u0000 here", "Quoted [n], NUL here"),
        # B4 and M1-M3 through the event path.
        ("Customer said saath rupay per watt; rate saath hai; do se teen lakh.",
         "Customer said [n] per watt; rate [n] hai; [n] se [n]."),
        ("Sau. Sunita Patil will decide; budget adhai lakh.",
         "Sau. Sunita Patil will decide; budget [n]."),
    ],
)  # fmt: skip
def test_check_4_summaries(summary: str, sent: str) -> None:
    payload = build_event(
        EVENT, replace(CONTEXT, summary=summary), Extraction("skipped", None), app_url=APP
    )
    assert payload["summary"] == sent
    assert summary_text(payload["summary"]) == payload["summary"]


def test_hostile_strings_anywhere_never_break_the_body() -> None:
    """Rule 4: build_event never raises on a lone surrogate, NUL or control character in
    the summary, the people or the facts."""
    hostile_fact = {
        **FACT,
        "value": {"stated_as": "5 kW\ud800\u0000", "quantity": 5, "unit": "kW"},
    }
    context = replace(
        CONTEXT,
        summary="Quoted\ud83d 45\u0000",
        salesperson=Person(None, "Sales\ud800person", "a\u0007@example.test"),
        lead=Lead(UUID("66666666-6666-4666-8666-666666666666"), "+91\u0000", "Cust\udfff", "Pune"),
    )
    payload = build_event(
        EVENT,
        context,
        Extraction("complete", "rooftop-solar-quote-v1", [hostile_fact]),
        app_url=APP,
    )
    body = json.loads(body_bytes(payload))
    assert body["summary"] == "Quoted [n]"
    assert body["salesperson"]["name"] == "Salesperson"
    assert body["salesperson"]["email"] == "a@example.test"
    assert body["lead"]["name"] == "Cust" and body["lead"]["phone_e164"] == "+91"
    assert body["facts"][0]["value"]["stated_as"] == "5 kW"
