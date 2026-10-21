"""Prompts and JSON schemas for the candidate pipeline shapes (b), (c), (c'), and the fact judge.

The 27 pointers and the 8 dimensions are the product's own (report_structure.POINTERS, coaching_schema), so a
one-pass answer can fill the same Report. Fact types match the benchmark's ground truth vocabulary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FACT_TYPES = ["person_name", "company", "product", "price", "budget", "quantity", "date", "time", "duration",
              "location", "decision_maker", "competitor", "competitor_price", "objection", "commitment", "next_step",
              "timeline", "payment_terms", "discount", "personal_detail", "pain_point", "requirement",
              "contact_preference"]
POINTERS = ["call_opening_first_impression", "purpose_agenda_setting", "tone_energy", "active_listening",
            "open_ended_questions", "enough_questions", "prospect_role", "needs_challenges", "current_solution",
            "business_impact", "decision_process", "stakeholders", "handling_objections", "solution_value",
            "discussing_pricing", "handling_competition", "checking_concerns", "next_steps", "call_control",
            "question_talk_ratio", "handling_silence", "professionalism", "closing_attitude", "building_rapport",
            "presenting_solution", "creating_value", "overall_communication"]
DIMENSIONS = ["human_connection_trust", "discovery_deep_understanding", "qualification", "problem_impact_desire",
              "solution_relevance_presentation", "certainty_objection_intelligence", "closing_decision_management",
              "communication_tonality"]

S = {"type": "string"}
SA = {"type": "array", "items": S}


def transcript_lines(segments: list[dict]) -> str:
    def clock(ms: int) -> str:
        return f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}"

    return "\n".join(f"[{s['id']}] {s['speaker_id']} {clock(s['start_ms'])}: {s['text']}" for s in segments)


ONEPASS_SYSTEM = """You analyse one recorded Indian sales phone call for a sales-coaching product.
The call may be in English, Hindi, Marathi or a mix. Write every output value in plain English (names of people,
companies and places in English letters as they sound), but never translate a number wrongly: keep amounts exact
and normalise Indian units (1 lakh = 100,000; 1 crore = 10,000,000; "saadhe baarah lakh" = 1,250,000).

Return ONE JSON object (schema given) with:
1. speakers: which speaker id is the salesperson, the prospect, or someone else, and their names if said.
2. facts: every concrete fact a salesperson would note in a CRM: people and companies, products, prices, the
   prospect's budget, quantities, dates and times (resolve "next Tuesday" against the call date), durations,
   locations, who decides, competitors and their prices, objections, commitments (who promised what, by when),
   the agreed next step, timelines, payment terms, discounts, personal details the prospect shared, pain points,
   requirements, contact preferences. One fact per distinct item. Cite 1-5 segment ids where it is said.
   - If a speaker corrects themselves, give only the corrected value. If something is withdrawn, mark it.
   - A competitor's price is a competitor_price, never our price.
   - Never invent anything. If unsure, leave it out.
3. pointers: for each of the 27 coaching pointers, status done | partial | missed | not_applicable, a 0-100 score,
   one short evidence-based note, and the segment ids it rests on.
4. report: a short coaching report: summary, up to 3 strengths, up to 3 improvements, up to 5 missed
   opportunities, objection handling, closing, the call outcome, the next step, and the 8 dimensions with a status
   strong | adequate | weak | not_observed and one observation each. Every finding cites segment ids.
5. call: call type, deal stage, outcome.
Be concise: short sentences, no repetition. Every claim must rest on what the transcript says."""


def onepass_schema() -> dict[str, Any]:
    seg = {"type": "array", "items": S, "maxItems": 5}
    finding = {"type": "object", "properties": {"title": S, "explanation": S, "segment_ids": seg},
               "required": ["title", "explanation", "segment_ids"]}
    return {
        "type": "object",
        "properties": {
            "speakers": {"type": "array", "items": {"type": "object", "properties": {
                "speaker_id": S, "role": {"type": "string", "enum": ["salesperson", "prospect", "other"]},
                "name": S}, "required": ["speaker_id", "role"]}},
            "facts": {"type": "array", "items": {"type": "object", "properties": {
                "type": {"type": "string", "enum": FACT_TYPES}, "value": S, "normalized": S,
                "said_by_role": {"type": "string", "enum": ["salesperson", "prospect", "other"]},
                "withdrawn": {"type": "boolean"}, "segment_ids": seg},
                "required": ["type", "value", "segment_ids"]}},
            "pointers": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string", "enum": POINTERS},
                "status": {"type": "string", "enum": ["done", "partial", "missed", "not_applicable"]},
                "score": {"type": "integer"}, "note": S, "segment_ids": seg},
                "required": ["id", "status", "score"]}},
            "report": {"type": "object", "properties": {
                "summary": S, "strengths": {"type": "array", "items": finding, "maxItems": 3},
                "improvements": {"type": "array", "items": finding, "maxItems": 3},
                "missed_opportunities": {"type": "array", "items": finding, "maxItems": 5},
                "objection_handling": S, "closing": S, "outcome": S, "next_step": S,
                "dimensions": {"type": "array", "items": {"type": "object", "properties": {
                    "id": {"type": "string", "enum": DIMENSIONS},
                    "status": {"type": "string", "enum": ["strong", "adequate", "weak", "not_observed"]},
                    "observation": S, "segment_ids": seg}, "required": ["id", "status", "observation"]}}},
                "required": ["summary", "strengths", "improvements", "missed_opportunities", "outcome",
                             "next_step", "dimensions"]},
            "call": {"type": "object", "properties": {"call_type": S, "deal_stage": S, "outcome": S}},
        },
        "required": ["speakers", "facts", "pointers", "report", "call"],
    }


ONEPASS2_SYSTEM = ONEPASS_SYSTEM.replace(
    "Be concise: short sentences, no repetition. Every claim must rest on what the transcript says.",
    "Facts must be EXHAUSTIVE: a salesperson's CRM needs every concrete detail, not a summary. List every person and "
    "company named, every price, budget, amount, quantity, date, time, duration, place, competitor, objection, "
    "commitment, next step, payment term, discount, requirement, pain point and personal detail, each as its own fact "
    "(a 15-minute call usually has 30-60 facts; a 3-minute call 15-25). Keep each fact's value short and exact.\n"
    "Everything else (pointers, report) is concise: short sentences, no repetition. Every claim must rest on what "
    "the transcript says.")
assert ONEPASS2_SYSTEM != ONEPASS_SYSTEM

# Round 2: the first prompt's fact instructions plus a coaching walk-through drawn from the product's pointer set
# (handling_objections, discussing_pricing, closing, needs_challenges, active_listening, building_rapport, ...).
ONEPASS3_SYSTEM = ONEPASS_SYSTEM.replace(
    "Be concise: short sentences, no repetition. Every claim must rest on what the transcript says.",
    "Coaching: before you write the report, walk through the call in order and note every coaching moment: each "
    "objection or concern and exactly how the salesperson answered it; anything the salesperson said that was wrong, "
    "inconsistent with what was said elsewhere in the call, or unverifiable; when price, discounts or concessions came "
    "up relative to the value shown and to the prospect's commitment; buying signals and whether the salesperson acted "
    "on them; discovery questions the situation called for that nobody asked; interrupting or talking over the "
    "prospect; how rapport was built. The report's strengths, improvements and missed_opportunities are the most "
    "important of these concrete moments, each tied to the segments where it happened, saying what the salesperson "
    "should have done instead. No generic advice.\n"
    "Be concise: short sentences, no repetition. Every claim must rest on what the transcript says.")
assert ONEPASS3_SYSTEM != ONEPASS_SYSTEM


def onepass_messages(segments: list[dict], call_date: str, version: int = 1) -> tuple[str, str]:
    # Transcript first and instructions after would maximise prefix caching across several passes; with one pass
    # it makes no difference, so the system prompt carries the instructions.
    system = {2: ONEPASS2_SYSTEM, 3: ONEPASS3_SYSTEM}.get(version, ONEPASS_SYSTEM)
    return system, f"Call date: {call_date}.\nTranscript (segment id, speaker id, time, words):\n" + \
        transcript_lines(segments)


ASR_PROMPT = """Transcribe this recorded phone call verbatim, every word, from start to end.
- Speakers: label them A, B, C… consistently by voice (the first voice heard is A).
- Language: write exactly what is said. Hindi and Marathi in Devanagari script; English words (including English
  words inside Hindi/Marathi sentences) in Latin script. Do not translate, correct, summarise or skip anything.
- Numbers: write amounts, dates and times as digits when spoken as numbers ("12.5 lakh", "27 October", "2:30").
- One segment per speaker turn; split a turn longer than ~30 seconds. start and end are MM:SS from the start.
- If something is inaudible write [inaudible]; never guess words."""


def asr_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"segments": {"type": "array", "items": {
        "type": "object", "properties": {"speaker": S, "start": S, "end": S, "text": S},
        "required": ["speaker", "start", "end", "text"]}}}, "required": ["segments"]}


AUDIO_ONECALL_PROMPT = ASR_PROMPT + """

Then analyse the call. Return ONE JSON object with "transcript" (the segments above, each with an id s1, s2, …)
and the analysis keys (speakers, facts, pointers, report, call) as described below, citing your own segment ids.

""" + ONEPASS_SYSTEM


def audio_onecall_schema() -> dict[str, Any]:
    sch = onepass_schema()
    seg_item = {"type": "object", "properties": {"id": S, "speaker": S, "start": S, "end": S, "text": S},
                "required": ["id", "speaker", "start", "end", "text"]}
    sch["properties"] = {"transcript": {"type": "array", "items": seg_item}, **sch["properties"]}
    sch["required"] = ["transcript", *sch["required"]]
    return sch


JUDGE_SYSTEM = """You are a strict benchmark judge. You compare facts extracted by a system from a sales call with
the ground-truth fact sheet of that call. The transcript is given for context.

For EACH ground-truth fact decide:
- "correct": the system states this fact with the right value (after normalising units/wording: 12.5 lakh =
  ₹1,250,000 = "12.5 L"; "27 Oct" = "27 October"; transliterated names that sound the same are the same).
- "wrong_value": the system states this slot but with a different value (a different number, date, name, or the
  pre-correction value of a self-correction, or a competitor's price given as ours).
- "missing": not stated.
For EACH system fact decide:
- "matches": the id of the ground-truth fact it expresses (or several), or
- "extra_supported": not in the sheet but clearly supported by the transcript, or
- "unsupported": not supported by the transcript (invented, or a wrong number/name/date) — a hallucination.
Be exact about numbers, dates and names. Return JSON only."""


def judge_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {
        "ground_truth": {"type": "array", "items": {"type": "object", "properties": {
            "id": S, "verdict": {"type": "string", "enum": ["correct", "wrong_value", "missing"]},
            "system_fact": {"type": "integer"}}, "required": ["id", "verdict"]}},
        "system": {"type": "array", "items": {"type": "object", "properties": {
            "index": {"type": "integer"}, "verdict": {"type": "string",
                                                     "enum": ["matches", "extra_supported", "unsupported"]},
            "ground_truth_ids": SA}, "required": ["index", "verdict"]}}},
        "required": ["ground_truth", "system"]}


# Round 4: one pass scored on the coaching lead's Brain 4.0 rubric (18 dimensions), compacted from the source document.
BRAIN4_RUBRIC = (Path(__file__).with_name("brain4_rubric.txt")).read_text(encoding="utf-8")
DIM_IDS = [f"D{i:02d}" for i in range(1, 19)]

BRAIN4_SYSTEM = """You analyse one recorded Indian sales phone call for a sales-coaching product, using the company's
Brain 4.0 rubric below. The call may be in English, Hindi, Marathi or a mix.
Write every output in simple, plain English that a salesperson understands at a glance: short sentences, everyday
words, "you" for the salesperson. Names of people, companies and places in English letters as they sound. Keep
amounts exact and normalise Indian units (1 lakh = 100,000; 1 crore = 10,000,000).

Return ONE JSON object (schema given) with:
1. speakers: which speaker id is the salesperson, the prospect, or someone else, and their names if said.
2. call: call type (inbound, cold, scheduled, follow-up, referral, existing client, re-engagement, operational),
   deal stage, outcome.
3. facts: every concrete fact a salesperson would note in a CRM: people and companies, products, prices, budget,
   quantities, dates and times, durations, locations, who decides, competitors and their prices, objections,
   commitments (who promised what, by when), the agreed next step, payment terms, discounts, personal details,
   pain points, requirements. One fact per item, citing 1-5 segment ids. Corrected values only; never invent.
4. dimensions: all 18 (D01-D18) scored by the rubric: rating 1-5 or null for "-", applicability, confidence,
   1-4 evidence items (segment ids, MM:SS time, one-line observation, positive or negative), the reason for the
   rating, and one specific coaching point. D07 also gives the ethics gate.
5. report: a 3-4 sentence summary; strengths and improvements (up to 6 each), each one concrete moment with its
   MM:SS time, what happened and why it mattered, and for improvements what to do instead ("On your next call,
   ..."); missed opportunities (up to 4); the next step; the single most important coaching focus.
Every claim cites segment ids and rests on what the transcript says.

RUBRIC
""" + BRAIN4_RUBRIC


COACH_NOTES_INSTRUCTION = """

COACH NOTES: also write "coach_notes", 10-20 notes in time order, the way an experienced sales coach writes while
listening to the call: every moment worth telling the salesperson, both the good habits to keep and the things
to change, plus the buyer's notable signals. Each note: MM:SS time, kind (strength,
improvement or observation), one or two plain sentences, and for improvements the better move. Give strengths their
full due: a strong call should get mostly strengths."""


def brain4_schema(notes: bool = False) -> dict[str, Any]:
    base = onepass_schema()
    seg = {"type": "array", "items": S, "maxItems": 5}
    evidence = {"type": "object", "properties": {"segment_ids": seg, "time": S, "observation": S,
                                                 "polarity": {"type": "string", "enum": ["positive", "negative"]}},
                "required": ["segment_ids", "observation", "polarity"]}
    finding = {"type": "object", "properties": {"time": S, "title": S, "explanation": S, "segment_ids": seg},
               "required": ["time", "title", "explanation", "segment_ids"]}
    props = {k: base["properties"][k] for k in ("speakers", "facts", "call")}
    props["dimensions"] = {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string", "enum": DIM_IDS}, "rating": {"type": ["integer", "null"]},
        "applicability": {"type": "string", "enum": ["applicable", "not_applicable", "not_enough_evidence"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "array", "items": evidence, "maxItems": 4}, "reason": S, "coaching": S,
        "ethics_gate": {"type": "string", "enum": ["PASS", "WARN", "FAIL"]}},
        "required": ["id", "rating", "applicability", "confidence", "evidence", "reason", "coaching"]}}
    props["report"] = {"type": "object", "properties": {
        "summary": S, "strengths": {"type": "array", "items": finding, "maxItems": 6},
        "improvements": {"type": "array", "items": finding, "maxItems": 6},
        "missed_opportunities": {"type": "array", "items": finding, "maxItems": 4},
        "next_step": S, "coaching_focus": S},
        "required": ["summary", "strengths", "improvements", "missed_opportunities", "next_step", "coaching_focus"]}
    required = ["speakers", "call", "facts", "dimensions", "report"]
    if notes:
        props["coach_notes"] = {"type": "array", "maxItems": 20, "items": {"type": "object", "properties": {
            "time": S, "kind": {"type": "string", "enum": ["strength", "improvement", "observation"]}, "note": S,
            "better_move": S, "segment_ids": seg}, "required": ["time", "kind", "note", "segment_ids"]}}
        required.append("coach_notes")
    return {"type": "object", "properties": props, "required": required}
