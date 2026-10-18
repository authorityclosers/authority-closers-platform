"""Quote facts for a partner's quotation draft (profile ``wiselife-quote-v1``).

One provider call reads one saved transcript and lists what was said about
the system, add-ons, prices, promises, next steps and objections. The model
is never trusted:

- it cites transcript segment ids only; unknown ids are dropped, and times
  and speakers are copied from the saved transcript;
- ``stated_as`` (and ``next_step.when_text``) must appear in a cited segment
  as whole words (case-insensitive, whitespace-normalised; no letter, digit
  or decimal point on either side, and no number word running on: "five
  years" is not in "twenty five years", "3.70 lakh" is not in "13.70 lakh"),
  else the fact is dropped (a one-per-call type then reads ``unknown``);
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
from typing import Any

from ac_platform.partner_events.amounts import (
    PLAIN_PRICE_FLOOR,
    amount_inr,
    counts_in,
    gst_basis,
    is_numeric_word,
    mentions_price,
    numbers_in,
    system_size,
)

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
    """Case-insensitive, whitespace-normalised comparison form."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _words(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
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


def _piece_after(text: str) -> str | None:
    """The word or number that ``text`` starts with, after only spaces or hyphens."""
    found = _PIECE.search(text)
    if found is None:
        return None
    gap = text[: found.start()]
    return found.group() if gap and _JOINING.fullmatch(gap) else None


def _whole(haystack: str, start: int, end: int) -> bool:
    """Whether ``haystack[start:end]`` stands as whole words and as a whole number."""
    needle, before, after = haystack[start:end], haystack[:start], haystack[end:]
    if _word_char(needle[0]) and before:
        last = before[-1]
        if _word_char(last) or (last in ".," and len(before) > 1 and before[-2].isdigit()):
            return False
    if _word_char(needle[-1]) and after:
        first = after[0]
        if _word_char(first) or (first in ".," and len(after) > 1 and after[1].isdigit()):
            return False
    # A number said in more words than were quoted: "five years" in "twenty five years",
    # "do lakh" in "sawa do lakh", "3 lakh" in "3 lakh 70 thousand".
    head = _PIECE.match(needle)
    tail = list(_PIECE.finditer(needle))
    if head and is_numeric_word(head.group()) and is_numeric_word(_piece_before(before)):
        return False
    return not (
        tail
        and tail[-1].end() == len(needle)
        and is_numeric_word(tail[-1].group())
        and is_numeric_word(_piece_after(after))
    )


def said_in(words: str, text: str) -> bool:
    """``words`` said word for word in ``text`` (folded), as whole words and numbers."""
    needle, haystack = _fold(words), _fold(text)
    if not needle:
        return False
    start = haystack.find(needle)
    while start != -1:
        if _whole(haystack, start, start + len(needle)):
            return True
        start = haystack.find(needle, start + 1)
    return False


def _containing(words: str, cited: list[dict[str, Any]]) -> dict[str, Any] | None:
    for segment in cited:
        if said_in(words, str(segment.get("text") or "")):
            return segment
    return None


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
        if when is None or said is None or mentions_price(when):
            return {"action": action, "when_text": None}, cited[0]
        return {"action": action, "when_text": when}, said

    stated_as = _words(raw.get("stated_as"), _LIMITS["stated_as"])
    if stated_as is None:
        return None
    found = _containing(stated_as, cited)
    if found is None:
        return None
    segment = found
    if fact_type == "mentioned_price":
        applies_to = raw.get("applies_to")
        if applies_to not in VOCABULARIES["mentioned_price.applies_to"]:
            applies_to = "other"
        return {
            "applies_to": applies_to,
            "speaker": speakers.get(str(segment.get("speaker_id")), "unknown"),
            "stated_as": stated_as,
            "amount_inr": amount_inr(stated_as),
            # Only this price's own words: GST said about another price never attaches.
            "basis": gst_basis(stated_as),
            "use": "flag_only",
        }, segment
    # Product names keep their own digits ("PuREPower 5"); a currency or money unit never.
    if mentions_price(stated_as, plain_numbers=fact_type != "product_mention"):
        return None
    if fact_type == "system_size":
        quantity, unit = system_size(stated_as)
        return {"stated_as": stated_as, "quantity": quantity, "unit": unit}, segment
    if fact_type == "add_on":
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["add_on.kind"] else "other"
        # A count is at most 100 and never a number next to a money or cost word.
        qty = _counted(raw.get("qty"), stated_as, maximum=PLAIN_PRICE_FLOOR, said=counts_in)
        return {"kind": kind, "qty": qty, "stated_as": stated_as}, segment
    if fact_type == "battery_type":
        kind = raw.get("kind")
        kind = kind if kind in VOCABULARIES["battery_type.kind"] else None
        return {"kind": kind, "stated_as": stated_as}, segment
    if fact_type == "warranty":
        years = _counted(raw.get("years"), stated_as, maximum=50)
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
