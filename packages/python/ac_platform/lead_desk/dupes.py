"""Duplicate leads: which two leads are the same person, scored with no AI (owner, 25 Oct
2026: "a very very strong pattern recognition and perfect engine that detects duplicate
leads based on many many factors and variables"; design: docs/product/lead-desk/
duplicates.md).

Each pair of leads that share a blocking key (the last ten digits of a phone, an email with
its typos folded, a name key, a company or a work domain) is scored on evidence, and every
point has a reason in words:
  - Certain: the same phone, the same email, or the same source record. These are the
    intake's repeats already; a pair found later is merged after review like any other.
  - Probable (score >= PROBABLE): the review queue.
  - Possible (score >= POSSIBLE): a quiet hint on the lead.
Two leads with different phones and different emails are two people until a person says
otherwise: such a pair is never above Possible, whatever else matches.

Pure: lead facts in, pairs out. No database, no clock, no randomness.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import combinations
from typing import Final, Literal
from uuid import UUID

Band = Literal["certain", "probable", "possible"]
PROBABLE: Final = 60
POSSIBLE: Final = 35
# A blocking key shared by more leads than this says little ("rahul", a big company): skipped.
BLOCK_LIMIT: Final = 60
RANK: Final[dict[Band, int]] = {"certain": 3, "probable": 2, "possible": 1}

EMAIL_TYPOS: Final[dict[str, str]] = {
    "gamil.com": "gmail.com",
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gnail.com": "gmail.com",
    "gmil.com": "gmail.com",
    "gmaill.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gmail.con": "gmail.com",
    "gmail.cm": "gmail.com",
    "googlemail.com": "gmail.com",
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yahoo.co": "yahoo.com",
    "hotmial.com": "hotmail.com",
    "outlok.com": "outlook.com",
    "rediffmail.co": "rediffmail.com",
}
FREE_MAIL: Final = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "yahoo.co.in",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "rediffmail.com",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "aol.com",
        "ymail.com",
    }
)
HONORIFICS: Final = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "shri", "shree", "sri", "smt", "kumari", "km", "prof", "er"}
)
COMPANY_WORDS: Final = frozenset(
    {
        "pvt",
        "private",
        "ltd",
        "limited",
        "llp",
        "inc",
        "co",
        "company",
        "corp",
        "corporation",
        "the",
        "and",
        "india",
        "solutions",
        "services",
        "enterprises",
        "group",
    }
)
# Romanised Indian names are written many ways; each pair folds to one spelling.
_FOLDS: Final[tuple[tuple[str, str], ...]] = (
    ("aa", "a"),
    ("ee", "i"),
    ("ii", "i"),
    ("oo", "u"),
    ("uu", "u"),
    ("ph", "f"),
    ("kh", "k"),
    ("gh", "g"),
    ("th", "t"),
    ("dh", "d"),
    ("bh", "b"),
    ("sh", "s"),
    ("ch", "c"),
    ("w", "v"),
    ("z", "j"),
    ("q", "k"),
)


@dataclass(frozen=True, slots=True)
class Card:
    """What the engine reads of a lead."""

    lead_id: UUID
    name: str | None = None
    # The organisation the lead is in: find() never compares two organisations' leads.
    tenant_id: UUID | None = None
    phones: tuple[str, ...] = ()
    emails: tuple[str, ...] = ()
    company: str | None = None
    city: str | None = None
    source_ref: str | None = None
    form: str | None = None
    received_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Pair:
    first: UUID
    second: UUID
    score: int
    # None: not alike enough to say anything.
    band: Band | None
    reasons: tuple[str, ...]
    # What says they may be two people ("different phones"): shown beside the reasons.
    against: tuple[str, ...] = field(default=())


# ----- normalising -------------------------------------------------------------------------


def last10(phone: str) -> str | None:
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else None


def fold_email(email: str) -> str | None:
    """One spelling for an email: lower case, a pasted "www." gone, known domain typos
    fixed, and for Gmail the dots and a +tag that Gmail itself ignores."""
    text = email.strip().lower()
    if text.count("@") != 1:
        return None
    local, domain = text.split("@")
    local = local.removeprefix("www.")
    domain = EMAIL_TYPOS.get(domain, domain)
    if not local or "." not in domain:
        return None
    if domain == "gmail.com":
        local = local.split("+", 1)[0].replace(".", "")
    return f"{local}@{domain}"


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def fold_token(token: str) -> str:
    """A romanised name word as one spelling: "Mohammad", "Muhammed" and "Mohamad" meet."""
    word = token
    for old, new in _FOLDS:
        word = word.replace(old, new)
    word = re.sub(r"(.)\1+", r"\1", word)
    # A final vowel sound written y, i or ee ("Sanjay" and "Sanjai") is one sound.
    return re.sub(r"y$", "i", word)


def name_tokens(name: str | None) -> tuple[str, ...]:
    if not name:
        return ()
    words = re.findall(r"[a-z]+", _ascii(name).lower())
    return tuple(fold_token(word) for word in words if word not in HONORIFICS and len(word) > 1)


def company_key(company: str | None) -> str | None:
    if not company:
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", _ascii(company).lower()) if w not in COMPANY_WORDS]
    return " ".join(words) or None


def work_domain(emails: Iterable[str]) -> str | None:
    for email in emails:
        folded = fold_email(email)
        if folded is not None:
            domain = folded.split("@")[1]
            if domain not in FREE_MAIL:
                return domain
    return None


def city_key(city: str | None) -> str | None:
    if not city:
        return None
    text = re.sub(r"[\s,\-]+(maharashtra|mh|india)$", "", city.strip().lower())
    text = re.sub(r"[^a-z ]", "", text).strip()
    return {"pume": "pune", "pube": "pune", "poona": "pune", "bombay": "mumbai"}.get(
        text, text
    ) or None


# ----- similarity --------------------------------------------------------------------------


def jaro_winkler(first: str, second: str) -> float:
    """Jaro-Winkler similarity, 0 to 1; the same whichever order the two come in."""
    if first > second:
        first, second = second, first
    if first == second:
        return 1.0 if first else 0.0
    if not first or not second:
        return 0.0
    reach = max(len(first), len(second)) // 2 - 1
    first_hits = [False] * len(first)
    second_hits = [False] * len(second)
    matches = 0
    for i, char in enumerate(first):
        low, high = max(0, i - reach), min(len(second), i + reach + 1)
        for j in range(low, high):
            if not second_hits[j] and second[j] == char:
                first_hits[i] = second_hits[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    left = [c for c, hit in zip(first, first_hits, strict=True) if hit]
    right = [c for c, hit in zip(second, second_hits, strict=True) if hit]
    transpositions = sum(a != b for a, b in zip(left, right, strict=True)) / 2
    jaro = (matches / len(first) + matches / len(second) + (matches - transpositions) / matches) / 3
    prefix = 0
    for a, b in zip(first[:4], second[:4], strict=False):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def name_similarity(first: str | None, second: str | None) -> float:
    """How alike two names are, after folding: the sorted words compared whole, or, when one
    name is a single word, that word against the other's first word (a little less sure)."""
    a, b = name_tokens(first), name_tokens(second)
    if not a or not b:
        return 0.0
    whole = jaro_winkler(" ".join(sorted(a)), " ".join(sorted(b)))
    if len(a) == 1 or len(b) == 1:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        partial = max(jaro_winkler(shorter[0], word) for word in longer) * 0.9
        return max(whole, partial)
    return whole


# ----- scoring -----------------------------------------------------------------------------


def _phones10(card: Card) -> set[str]:
    return {key for phone in card.phones if (key := last10(phone)) is not None}


def _emails(card: Card) -> set[str]:
    return {key for email in card.emails if (key := fold_email(email)) is not None}


def score(a: Card, b: Card) -> Pair:
    """The evidence that two leads are one person, in points and words."""
    reasons: list[str] = []
    against: list[str] = []
    points = 0
    certain = False
    if a.source_ref and a.source_ref == b.source_ref:
        certain = True
        reasons.append("the same source record")
    exact_phone = set(a.phones) & set(b.phones)
    a10, b10 = _phones10(a), _phones10(b)
    if exact_phone:
        certain = True
        reasons.append("same phone number")
    elif a10 & b10:
        points += 80
        reasons.append("same last 10 digits of the phone")
    elif a10 and b10:
        points -= 40
        against.append("different phones")
    raw_a = {e.strip().lower() for e in a.emails if e.strip()}
    raw_b = {e.strip().lower() for e in b.emails if e.strip()}
    folded_a, folded_b = _emails(a), _emails(b)
    if raw_a & raw_b:
        certain = True
        reasons.append("same email")
    elif folded_a & folded_b:
        points += 70
        reasons.append("same email apart from a typo")
    elif folded_a and folded_b:
        points -= 15
        against.append("different emails")
    alike = name_similarity(a.name, b.name)
    if alike >= 0.99:
        points += 35
        reasons.append("same name")
    elif alike >= 0.92:
        points += 30
        reasons.append(f"names {round(alike * 100)}% alike")
    elif alike >= 0.85:
        points += 20
        reasons.append(f"names {round(alike * 100)}% alike")
    elif alike >= 0.75:
        points += 8
        reasons.append(f"names {round(alike * 100)}% alike")
    elif name_tokens(a.name) and name_tokens(b.name) and alike < 0.5:
        points -= 30
        against.append("different names")
    company_a, company_b = company_key(a.company), company_key(b.company)
    if company_a and company_a == company_b:
        points += 15
        reasons.append("same company")
    domain_a, domain_b = work_domain(a.emails), work_domain(b.emails)
    if domain_a and domain_a == domain_b and not (folded_a & folded_b):
        points += 15
        reasons.append(f"same work email domain ({domain_a})")
    city_a, city_b = city_key(a.city), city_key(b.city)
    if city_a and city_a == city_b:
        points += 5
        reasons.append("same city")
    if a.form and a.form == b.form:
        points += 5
        reasons.append("same form or campaign")
    if a.received_at and b.received_at:
        gap = abs(a.received_at - b.received_at)
        if gap <= timedelta(minutes=10):
            points += 10
            reasons.append("came in within 10 minutes")
        elif gap <= timedelta(hours=24):
            points += 5
            reasons.append("came in the same day")
    first, second = sorted((a.lead_id, b.lead_id))
    band: Band | None
    if certain:
        band = "certain"
    elif points >= PROBABLE:
        band = "probable"
    elif points >= POSSIBLE:
        band = "possible"
    else:
        band = None
    two_people = bool(a10 and b10 and not a10 & b10) and bool(
        folded_a and folded_b and not folded_a & folded_b
    )
    if two_people and band in ("certain", "probable"):
        # Different phones and different emails: never more than a hint.
        band = "possible"
    return Pair(
        first=first,
        second=second,
        score=points + (100 if certain else 0),
        band=band,
        reasons=tuple(reasons),
        against=tuple(against),
    )


def keys(card: Card) -> set[str]:
    """The blocking keys a lead is compared under."""
    found = {f"p:{key}" for key in _phones10(card)}
    found |= {f"e:{key}" for key in _emails(card)}
    tokens = name_tokens(card.name)
    if len(tokens) >= 2:
        found.add(f"n:{tokens[0]}:{tokens[-1][:3]}")
    elif tokens:
        found.add(f"n1:{tokens[0]}")
    company = company_key(card.company)
    if company:
        found.add(f"c:{company}")
    domain = work_domain(card.emails)
    if domain:
        found.add(f"d:{domain}")
    if card.source_ref:
        found.add(f"r:{card.source_ref}")
    return found


def find(cards: Sequence[Card], *, minimum: Band = "possible") -> list[Pair]:
    """The pairs in these leads at or above a band, the likeliest first. The leads are one
    organisation's: leads of two are refused, never compared."""
    if len({card.tenant_id for card in cards if card.tenant_id is not None}) > 1:
        raise ValueError("Duplicates are found within one organisation at a time.")
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, card in enumerate(cards):
        for key in keys(card):
            blocks[key].append(index)
    seen: set[tuple[int, int]] = set()
    pairs: list[Pair] = []
    wanted = RANK[minimum]
    for members in blocks.values():
        if len(members) < 2 or len(members) > BLOCK_LIMIT:
            continue
        for i, j in combinations(members, 2):
            if (i, j) in seen:
                continue
            seen.add((i, j))
            pair = score(cards[i], cards[j])
            if pair.band is not None and RANK[pair.band] >= wanted:
                pairs.append(pair)
    pairs.sort(key=lambda pair: (-pair.score, str(pair.first), str(pair.second)))
    return pairs
