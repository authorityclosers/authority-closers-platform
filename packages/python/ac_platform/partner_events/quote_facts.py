"""Quote facts for a partner's quotation draft (profile ``wiselife-quote-v1``).

One provider call reads one saved transcript and lists what was said about
the system, add-ons, prices, promises, next steps and objections. The model
is never trusted:

- it cites transcript segment ids only; unknown ids are dropped, and times
  and speakers are copied from the saved transcript;
- ``stated_as`` (and ``next_step.when_text``) must appear in a cited segment
  as whole words (case-insensitive, whitespace-normalised; no letter, digit
  or decimal point on either side, and no neighbour that makes it part of a
  longer number: "five years" is not in "twenty five years", "3.70 lakh" is
  not in "13.70 lakh", "3 lakh" is not in "3 lakh 70 thousand"), else the
  fact is dropped (a one-per-call type then reads ``unknown``). Ordinary
  words next to a number ("we can do 5 kW", "one 5 kW inverter", "aap teen
  lakh do") do not count. A neighbour that may or may not belong to the
  number ("3 lakh" in "3 lakh 70", "teen lakh" in "do teen lakh") keeps the
  fact with its number read as null (``amount_inr``, ``quantity``, ``qty``,
  ``years``);
- every enum is checked; a count or a year is kept only when that number was
  said in ``stated_as`` (an add-on count at most 100, never a number next to
  a money or cost word);
- sizes and rupee amounts come from our own reader (``amounts``), never from
  the model; ``mentioned_price.basis`` is read from its own ``stated_as``
  only; ``mentioned_price.use`` is always ``flag_only``;
- no other fact type may carry a price.

Withheld (sensitive) segments are never in the prompt, so they can never be
cited. Nothing here calls the network; the runner supplies the provider call.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Literal

from ac_platform.partner_events.amounts import (
    PLAIN_PRICE_FLOOR,
    amount_inr,
    carries_money,
    clean_text,
    counts_in,
    gst_basis,
    mentions_price,
    number_join,
    numbers_in,
    system_size,
)
from ac_platform.partner_events.summary_mask import mask_numbers, mask_when

Match = Literal["whole", "ambiguous"]

PROFILE_DIR = Path(__file__).with_name("profiles")
PROFILES = {"wiselife-quote-v1": "wiselife_quote_v1.json"}

# The v1 contract (sx.analysis_completed.v1, 18 Oct 2026). A profile must match it exactly.
FACT_TYPES = (
    "system_size",
    "product_mention",
    "load",
    "add_on",
    "battery_type",
    "warranty",
    "site",
    "delivery_basis",
    "mentioned_price",
    "promise",
    "next_step",
    "objection",
)
SINGLE_TYPES = ("system_size", "battery_type", "warranty", "site", "delivery_basis")
VOCABULARIES: dict[str, tuple[str, ...]] = {
    "add_on.kind": (
        "dongle",
        "packing",
        "extended_warranty",
        "acdb",
        "dcdb",
        "battery",
        "panel",
        "structure",
        "earthing",
        "lightning_arrestor",
        "other",
    ),
    "system_size.unit": ("kW", "kVA"),
    "battery_type.kind": ("lithium", "tubular", "other"),
    "delivery_basis.kind": ("delivered_to_site", "from_godown"),
    "mentioned_price.applies_to": ("system", "add_on", "installation", "transport", "other"),
    "speaker": ("salesperson", "customer", "unknown"),
    "next_step.action": ("send_quotation", "site_visit", "call_back", "meeting", "other"),
    "objection.kind": (
        "price_concern",
        "affordability_gap",
        "time_constraint",
        "stall",
        "competitor_or_status_quo",
        "decision_maker_absent",
        "trust_concern",
        "other",
    ),
    "outcome.kind": ("closed", "follow_up", "no_sale", "future_date", "disqualified", "unclear"),
}
MAX_PER_LIST_TYPE = 10
MAX_ALTERNATIVES = 3
_LIMITS = {"stated_as": 200, "text": 240, "when_text": 80}


class QuoteFactsError(ValueError):
    """Stable code only; never carries transcript or provider text."""


@dataclass(frozen=True)
class Profile:
    name: str
    prompt_revision: str
    model_id: str
    max_output_tokens: int
    looked_for: tuple[str, ...]
    instructions: str
    response_schema: dict[str, Any]


@cache
def load_profile(name: str) -> Profile:
    """A checked-in profile; refuses one whose vocabularies differ from the v1 contract."""
    if name not in PROFILES:
        raise QuoteFactsError("quote_facts_profile_unknown")
    raw = json.loads((PROFILE_DIR / PROFILES[name]).read_text(encoding="utf-8"))
    vocabularies = {key: tuple(values) for key, values in raw["vocabularies"].items()}
    if (
        raw["profile"] != name
        or tuple(raw["looked_for"]) != FACT_TYPES
        or tuple(raw["single_types"]) != SINGLE_TYPES
        or vocabularies != VOCABULARIES
    ):
        raise QuoteFactsError("quote_facts_profile_contract_mismatch")
    return Profile(
        name=name,
        prompt_revision=str(raw["prompt_revision"]),
        model_id=str(raw["model_id"]),
        max_output_tokens=int(raw["max_output_tokens"]),
        looked_for=tuple(raw["looked_for"]),
        instructions="\n".join(raw["instructions"]),
        response_schema=dict(raw["response_schema"]),
    )


def speaker_label(role: str | None) -> str:
    """Sales X-Ray speaker-map roles as the partner's speaker vocabulary."""
    if role in {"you", "salesperson", "seller", "rep"}:
        return "salesperson"
    if role == "prospect":
        return "customer"
    return "unknown"


def _clock(ms: int) -> str:
    seconds = max(0, ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def build_prompt(
    profile: Profile, segments: list[dict[str, Any]], speakers: dict[str, str]
) -> tuple[str, str]:
    """System and user text. ``segments`` must already exclude withheld segments."""
    lines = []
    for segment in segments:
        words = " ".join(str(segment.get("text") or "").split())
        if not words:
            continue
        who = speakers.get(str(segment.get("speaker_id")), "unknown")
        lines.append(f"[{segment['id']}] {who} {_clock(int(segment['start_ms']))}: {words}")
    if not lines:
        raise QuoteFactsError("quote_facts_transcript_empty")
    system = f"{profile.prompt_revision}\n{profile.instructions}"
    return system, "Transcript:\n" + "\n".join(lines)


def gemini_body(profile: Profile, system: str, user: str) -> dict[str, Any]:
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "candidateCount": 1,
            "maxOutputTokens": profile.max_output_tokens,
            "responseMimeType": "application/json",
            "responseJsonSchema": profile.response_schema,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
        },
    }


def prompt_sha256(profile: Profile, system: str, user: str) -> str:
    return hashlib.sha256(
        json.dumps([profile.model_id, system, user], ensure_ascii=False).encode()
    ).hexdigest()


def decode_gemini(response: dict[str, Any]) -> dict[str, Any]:
    try:
        candidate = response["candidates"][0]
        text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
        value = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        raise QuoteFactsError("quote_facts_response_invalid") from None
    if not isinstance(value, dict) or not isinstance(value.get("facts"), list):
        raise QuoteFactsError("quote_facts_response_invalid")
    return value


def payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _fold(text: str) -> str:
    """Case-insensitive, whitespace-normalised comparison form (NFKC, no control or
    zero-width characters)."""
    return " ".join(clean_text(text).casefold().split())


def _words(value: Any, limit: int) -> str | None:
    """Model text as kept: NFKC, without lone surrogates, control or zero-width characters
    (round 4), whitespace collapsed; None when empty or too long."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(clean_text(value).split())
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


def _seconds(segment: dict[str, Any], speakers: dict[str, str]) -> dict[str, Any]:
    start, end = int(segment["start_ms"]), int(segment["end_ms"])
    return {
        "segment_id": str(segment["id"]),
        "t_start_sec": start // 1000,
        "t_end_sec": -(-end // 1000),
        "speaker": speakers.get(str(segment.get("speaker_id")), "unknown"),
    }


def _cited(evidence: Any, by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Known cited segments, in the model's order; unknown ids are dropped."""
    found: list[dict[str, Any]] = []
    for reference in evidence if isinstance(evidence, list) else []:
        segment = by_id.get(str(reference).strip())
        if segment is not None and segment not in found:
            found.append(segment)
    return found


_PIECE = re.compile(r"[0-9०-९]+(?:[.,][0-9०-९]+)*|[a-z]+|[ऀ-ॣॱ-ॿ]+")
_JOINING = re.compile(r"[\s\-–]+")


def _word_char(char: str) -> bool:
    """A letter, digit or combining mark (Devanagari vowel signs are marks)."""
    return char.isalnum() or char == "_" or unicodedata.category(char).startswith("M")


def _piece_before(text: str) -> str | None:
    """The word or number that ``text`` ends with, when only spaces or hyphens follow it."""
    pieces = list(_PIECE.finditer(text))
    if not pieces:
        return None
    gap = text[pieces[-1].end() :]
    return pieces[-1].group() if gap and _JOINING.fullmatch(gap) else None


def _pieces_after(text: str, limit: int = 2) -> list[str]:
    """Up to ``limit`` words or numbers that ``text`` starts with: the first after only
    spaces or hyphens, each next one after spaces, hyphens or nothing ("70k")."""
    found: list[str] = []
    rest = text
    while len(found) < limit:
        piece = _PIECE.search(rest)
        if piece is None:
            break
        gap = rest[: piece.start()]
        if not (_JOINING.fullmatch(gap) if gap else found):
            break
        found.append(piece.group())
        rest = rest[piece.end() :]
    return found


def _whole(haystack: str, start: int, end: int) -> Match | None:
    """Whether ``haystack[start:end]`` stands as whole words and as a whole number.

    "whole": yes. "ambiguous": whole words, but a neighbour may belong to the
    number ("3 lakh" in "3 lakh 70"). None: not whole, or part of a longer
    number ("five years" in "twenty five years", "do lakh" in "sawa do lakh",
    "3 lakh" in "3 lakh 70 thousand").
    """
    needle, before, after = haystack[start:end], haystack[:start], haystack[end:]
    if _word_char(needle[0]) and before:
        last = before[-1]
        if _word_char(last) or (last in ".," and len(before) > 1 and before[-2].isdigit()):
            return None
    if _word_char(needle[-1]) and after:
        first = after[0]
        if _word_char(first) or (first in ".," and len(after) > 1 and after[1].isdigit()):
            return None
    pieces = list(_PIECE.finditer(needle))
    if not pieces:
        return "whole"
    following = _pieces_after(after)
    first_after = following[0] if following else None
    second_after = following[1] if len(following) > 1 else None
    joins = []
    if pieces[0].start() == 0:  # the word or number before the quote, and its head
        head_next = pieces[1].group() if len(pieces) > 1 else first_after
        joins.append(number_join(_piece_before(before), pieces[0].group(), head_next))
    if pieces[-1].end() == len(needle):  # its tail, and the words after the quote
        joins.append(number_join(pieces[-1].group(), first_after, second_after))
    if "hard" in joins:
        return None
    return "ambiguous" if "soft" in joins else "whole"


def match_in(words: str, text: str) -> Match | None:
    """How ``words`` are said in ``text`` (folded): "whole" when any occurrence stands
    as whole words and a whole number, "ambiguous" when the only ones may run on
    into a neighbouring number, None when they are not said."""
    needle, haystack = _fold(words), _fold(text)
    if not needle:
        return None
    best: Match | None = None
    start = haystack.find(needle)
    while start != -1:
        found = _whole(haystack, start, start + len(needle))
        if found == "whole":
            return found
        best = best or found
        start = haystack.find(needle, start + 1)
    return best


def said_in(words: str, text: str) -> bool:
    """``words`` said word for word in ``text`` (folded), as whole words and numbers."""
    return match_in(words, text) is not None


def _containing(words: str, cited: list[dict[str, Any]]) -> tuple[dict[str, Any], bool] | None:
    """The first cited segment that says ``words`` whole (else one that says them with an
    ambiguous neighbour), and whether the number in them is ambiguous."""
    fallback: dict[str, Any] | None = None
    for segment in cited:
        found = match_in(words, str(segment.get("text") or ""))
        if found == "whole":
            return segment, False
        if found == "ambiguous" and fallback is None:
            fallback = segment
    return (fallback, True) if fallback is not None else None


def _counted(
    value: Any,
    stated_as: str,
    *,
    maximum: int,
    said: Callable[[str], set[Decimal]] = numbers_in,
) -> int | None:
    """A count or a year only when it is a whole number said in ``stated_as``."""
    if type(value) is not int or not 1 <= value <= maximum:
        return None
    return value if Decimal(value) in said(stated_as) else None


# Plausibility bounds (round 5, R1): a typed value outside them drops the fact.
_WARRANTY_YEARS_MAX = 30
_SIZE_MAX = 1000  # kW or kVA


def _out_of_range(value: Any, maximum: int) -> bool:
    """A whole number typed by the model that no real count or warranty can be."""
    return type(value) is int and not 1 <= value <= maximum


def _clean(
    fact_type: str, raw: Any, cited: list[dict[str, Any]], speakers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(value, source) for one proposed fact or alternative, or None when it fails."""
    if not isinstance(raw, dict) or not cited:
        return None
    if fact_type in {"promise", "objection"}:
        text = _words(raw.get("text"), _LIMITS["text"])
        if text is None or mentions_price(text):
            return None
        # Round 4: every number left reads "[n]", as in the summary, so no price can pass.
        text = mask_numbers(text)
        segment = cited[0]
        if fact_type == "promise":
            speaker = speakers.get(str(segment.get("speaker_id")), "unknown")
            return {"speaker": speaker, "text": text}, segment
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["objection.kind"] else "other"
        return {"kind": kind, "text": text}, segment
    if fact_type == "next_step":
        action = raw.get("action")
        action = action if action in VOCABULARIES["next_step.action"] else "other"
        when = _words(raw.get("when_text"), _LIMITS["when_text"])
        said = _containing(when, cited) if when else None
        if when is None or said is None:
            return {"action": action, "when_text": None}, cited[0]
        # Round 5 (R2): every number reads "[n]" except strict date and time forms ("kal
        # shaam 5 baje", "Monday 10:30", "20 October", "18/10/2026"); "advance 25000 dene ke
        # baad" reads "advance [n] dene ke baad".
        return {"action": action, "when_text": mask_when(when)}, said[0]

    stated_as = _words(raw.get("stated_as"), _LIMITS["stated_as"])
    if stated_as is None:
        return None
    found = _containing(stated_as, cited)
    if found is None:
        return None
    # An ambiguous neighbour ("3 lakh" in "3 lakh 70"): the fact stays, its number is null.
    segment, ambiguous = found
    if fact_type == "mentioned_price":
        applies_to = raw.get("applies_to")
        if applies_to not in VOCABULARIES["mentioned_price.applies_to"]:
            applies_to = "other"
        return {
            "applies_to": applies_to,
            "speaker": speakers.get(str(segment.get("speaker_id")), "unknown"),
            "stated_as": stated_as,
            "amount_inr": None if ambiguous else amount_inr(stated_as),
            # Only this price's own words: GST said about another price never attaches.
            "basis": gst_basis(stated_as),
            "use": "flag_only",
        }, segment
    # Round 5 (R1, an allow rule): every number in the words must be explained by a unit, a
    # counted noun, a warranty year word or a model name, and no money, rupee, cost or GST
    # word may be said; otherwise the fact is dropped ("bill 3000 mahina", "dongle nineteen
    # ninety nine", "डोंगल पंधराशे", "watt ke 45"). "5 kW", "2 BHK", "PuREPower 5" stay.
    if carries_money(stated_as, fact_type):
        return None
    if fact_type == "system_size":
        quantity, unit = (None, None) if ambiguous else system_size(stated_as)
        if quantity is not None and quantity > (_SIZE_MAX if unit else PLAIN_PRICE_FLOOR):
            return None  # outside a sane range
        return {"stated_as": stated_as, "quantity": quantity, "unit": unit}, segment
    if fact_type == "add_on":
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["add_on.kind"] else "other"
        if _out_of_range(raw.get("qty"), PLAIN_PRICE_FLOOR):
            return None
        # A count is at most 100 and never a number next to a money or cost word.
        qty = None
        if not ambiguous:
            qty = _counted(raw.get("qty"), stated_as, maximum=PLAIN_PRICE_FLOOR, said=counts_in)
        return {"kind": kind, "qty": qty, "stated_as": stated_as}, segment
    if fact_type == "battery_type":
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["battery_type.kind"] else None
        return {"kind": kind, "stated_as": stated_as}, segment
    if fact_type == "warranty":
        if _out_of_range(raw.get("years"), _WARRANTY_YEARS_MAX):
            return None
        years = (
            None
            if ambiguous
            else _counted(raw.get("years"), stated_as, maximum=_WARRANTY_YEARS_MAX)
        )
        return {"years": years, "stated_as": stated_as}, segment
    if fact_type == "delivery_basis":
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["delivery_basis.kind"] else None
        return {"kind": kind, "stated_as": stated_as}, segment
    return {"stated_as": stated_as}, segment  # product_mention, load, site


def _identity(value: dict[str, Any]) -> str:
    return _fold(str(value.get("stated_as") or value.get("text") or value.get("action") or ""))


def unknown(fact_type: str) -> dict[str, Any]:
    return {"type": fact_type, "status": "unknown", "value": None, "source": None}


def parse_facts(
    raw: dict[str, Any], segments: list[dict[str, Any]], speakers: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    """Validated facts in contract shape, and how many proposals were dropped.

    ``segments`` are exactly the segments that were in the prompt. Every
    one-per-call type appears once: stated, conflicting or unknown.
    """
    by_id = {str(segment["id"]): segment for segment in segments}
    value = raw.get("facts")
    proposals: list[Any] = value if isinstance(value, list) else []
    dropped = 0
    singles: dict[str, list[tuple[dict[str, Any], dict[str, Any], list[Any]]]] = {}
    lists: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        if not isinstance(proposal, dict) or proposal.get("type") not in FACT_TYPES:
            dropped += 1
            continue
        fact_type = str(proposal["type"])
        if proposal.get("status") not in {"stated", "conflicting"}:
            dropped += 1
            continue
        cleaned = _clean(
            fact_type, proposal.get("value"), _cited(proposal.get("evidence"), by_id), speakers
        )
        if cleaned is None:
            dropped += 1
            continue
        value, segment = cleaned
        if fact_type in SINGLE_TYPES:
            alternatives = (
                proposal.get("alternatives") or []
                if proposal.get("status") == "conflicting"
                else []
            )
            singles.setdefault(fact_type, []).append((value, segment, list(alternatives)))
            continue
        entries = lists.setdefault(fact_type, [])
        source = _seconds(segment, speakers)
        key = (_identity(value), source["segment_id"])
        if any((_identity(item["value"]), item["source"]["segment_id"]) == key for item in entries):
            continue
        if len(entries) >= MAX_PER_LIST_TYPE:
            dropped += 1
            continue
        entries.append({"type": fact_type, "status": "stated", "value": value, "source": source})

    facts: list[dict[str, Any]] = []
    for fact_type in FACT_TYPES:
        if fact_type not in SINGLE_TYPES:
            facts.extend(sorted(lists.get(fact_type, []), key=_order))
            continue
        found = singles.get(fact_type)
        if not found:
            facts.append(unknown(fact_type))
            continue
        main_value, main_segment, proposed = found[0]
        others: list[tuple[dict[str, Any], dict[str, Any]]] = [
            (value, segment) for value, segment, _ in found[1:]
        ]
        for alternative in proposed:
            if not isinstance(alternative, dict):
                dropped += 1
                continue
            cleaned = _clean(
                fact_type,
                alternative.get("value"),
                _cited(alternative.get("evidence"), by_id),
                speakers,
            )
            if cleaned is None:
                dropped += 1
                continue
            others.append(cleaned)
        seen = {_identity(main_value)}
        alternatives = []
        for value, segment in others:
            if _identity(value) in seen or len(alternatives) >= MAX_ALTERNATIVES:
                continue
            seen.add(_identity(value))
            alternatives.append({"value": value, "source": _seconds(segment, speakers)})
        fact: dict[str, Any] = {
            "type": fact_type,
            "status": "conflicting" if alternatives else "stated",
            "value": main_value,
            "source": _seconds(main_segment, speakers),
        }
        if alternatives:
            fact["alternatives"] = alternatives
        facts.append(fact)
    return facts, dropped


def _order(fact: dict[str, Any]) -> tuple[int, str]:
    source = fact.get("source") or {}
    return int(source.get("t_start_sec") or 0), str(source.get("segment_id") or "")
