"""What a lead carries for routing (docs/product/lead-desk/routing-and-patterns.md, section 1):
its form answers as facets, and a value read from one answer as a number band. Pure: no
database and no clock.

- An answer is a facet when it is a choice, not free text: at most 80 characters, and not a
  phone number, an email, one of the lead's own fields, a time or a source's own id.
- A value band reads money as people write it in India: "₹60,000 – ₹1,00,000", "₹1,00,000+",
  "Under ₹15,000", "15k-30k", "1.5 lakh", "2L+", "1 crore", "50,000 to 1 lakh". "+" or "above"
  has no high; "under" or "up to" has no low; one amount is a band of one.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final, NamedTuple

from ac_platform.lead_desk.capture import ALIASES, FIELDS, REFERENCE_KEYS, flatten, key

MAX_ANSWER: Final = 80
MAX_FACETS: Final = 30
# A lead's own fields and a source's bookkeeping are never answers.
_NOT_ANSWERS: Final = frozenset(
    {*FIELDS, *(alias for names in ALIASES.values() for alias in names), *REFERENCE_KEYS}
)
_TIME = re.compile(r"(?:^|_)(?:created|submitted|received|updated)?_?(?:time|date|at|timestamp)$")
_PHONE = re.compile(r"\A\+?[\d\s()-]{7,}\Z")
_EMAIL = re.compile(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\Z")

_UNITS: Final[dict[str, int]] = {
    "k": 1_000,
    "thousand": 1_000,
    "l": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "cr": 10_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
}
_AMOUNT = re.compile(
    r"(\d+(?:,\d+)*(?:\.\d+)?)\s*(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")?\b"
)
_ABOVE = re.compile(r"\+|\b(?:above|over|more than|greater than|at least|minimum|min)\b")
_BELOW = re.compile(r"\b(?:under|below|less than|up ?to|within|maximum|max)\b|<")


class Band(NamedTuple):
    """A value as a range in rupees: ``low`` or ``high`` is None when open on that side."""

    low: int | None
    high: int | None

    @property
    def mid(self) -> int | None:
        if self.low is not None and self.high is not None:
            return (self.low + self.high) // 2
        return self.low if self.low is not None else self.high


class Facet(NamedTuple):
    key: str
    label: str
    value: str


def value_band(text: object) -> Band | None:
    """The money in an answer as a band, or None when it names no amount."""
    if text is None or isinstance(text, (dict, list, bool)):
        return None
    lowered = str(text).lower()
    words = re.sub(r"₹|\brs\.?|\binr\b", " ", lowered)
    words = re.sub(r"[–—−]|\bto\b", "-", words)
    # "15, 000" (a number split at its comma by an export) reads as 15000.
    words = re.sub(r"(\d),\s+(?=\d{3}\b)", r"\1,", words)
    found = [(float(digits.replace(",", "")), unit) for digits, unit in _AMOUNT.findall(words)][:2]
    if not found:
        return None
    if len(found) == 2:
        (first, first_unit), (second, second_unit) = found
        # "15-30k", "1-1.5 lakh": the first borrows the second's unit.
        if not first_unit and second_unit and first <= second:
            first_unit = second_unit
        amounts = sorted(
            round(number * _UNITS.get(unit, 1))
            for number, unit in ((first, first_unit), (second, second_unit))
        )
        return Band(amounts[0], amounts[1])
    number, unit = found[0]
    amount = round(number * _UNITS.get(unit, 1))
    if _BELOW.search(lowered):
        return Band(None, amount)
    if _ABOVE.search(lowered):
        return Band(amount, None)
    return Band(amount, amount)


def rupees(amount: int) -> str:
    """₹1,00,000: Indian grouping, as owners write it."""
    digits = str(abs(amount))
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ("-" if amount < 0 else "") + "₹" + ",".join([*groups, tail])


def band_words(band: Band) -> str:
    if band.low is not None and band.high is not None:
        if band.low == band.high:
            return rupees(band.low)
        return f"{rupees(band.low)} – {rupees(band.high)}"
    if band.low is not None:
        return f"{rupees(band.low)}+"
    return f"under {rupees(band.high or 0)}"


def facets(payload: Mapping[str, Any]) -> tuple[Facet, ...]:
    """A lead's form answers that are choices, by question: one spelling of each question
    (``capture.key``), its words as asked, and the answer as given."""
    found: dict[str, Facet] = {}
    for name, raw in flatten(payload).items():
        if raw is None or isinstance(raw, (dict, list)) or str(name).startswith("_"):
            continue
        slug = key(name)[:80]
        if not slug or slug in _NOT_ANSWERS or _TIME.search(slug) or slug in found:
            continue
        value = " ".join(str(raw).split())
        if not value or len(value) > MAX_ANSWER or _PHONE.match(value) or _EMAIL.match(value):
            continue
        label = " ".join(str(name).replace("_", " ").split())
        found[slug] = Facet(slug, label[:1].upper() + label[1:120], value)
        if len(found) >= MAX_FACETS:
            break
    return tuple(found.values())
