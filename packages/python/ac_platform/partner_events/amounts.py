"""Deterministic readers for the words a speaker said (partner quote facts v1).

The model never supplies an amount, a size or a count that we pass on. It
quotes the words said (``stated_as``) and these functions read numbers from
those words only:

- ``amount_inr``: "3.70 lakh" -> 370000, "45k" -> 45000, "3,70,000" ->
  370000, "1.2 crore" -> 12000000, "teen lakh" / "तीन लाख" -> 300000,
  "3 lakh 70 thousand" -> 370000. Anything ambiguous is ``None``: a bare
  small number ("3.70"), a range ("about 3 to 4"), two unrelated numbers.
- ``system_size``: "5 kW" -> (5, "kW"), "10 kva" -> (10, "kVA"),
  "5000 watt" -> (5, "kW"), "five" -> (5, None); a range or two numbers ->
  (None, None).
- ``numbers_in``: every number said, for checking a count or a year.
- ``mentions_price``: whether words carry a price, so no fact type other than
  ``mentioned_price`` ever passes one on.
- ``gst_basis``: "incl_gst" / "ex_gst" only when GST was said with a clear cue.

English, romanised Hindi, Devanagari (Hindi and Marathi) and Devanagari
digits are read. Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal

Unit = Literal["kW", "kVA"]

_DEVANAGARI_DIGITS = {ord(chr(0x0966 + n)): str(n) for n in range(10)}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[ऀ-ॣॱ-ॿ]+|₹|/-|[-–~+]")

_WORDS: dict[str, Decimal] = {
    # English
    "one": Decimal(1),
    "two": Decimal(2),
    "three": Decimal(3),
    "four": Decimal(4),
    "five": Decimal(5),
    "six": Decimal(6),
    "seven": Decimal(7),
    "eight": Decimal(8),
    "nine": Decimal(9),
    "ten": Decimal(10),
    "eleven": Decimal(11),
    "twelve": Decimal(12),
    "thirteen": Decimal(13),
    "fourteen": Decimal(14),
    "fifteen": Decimal(15),
    "sixteen": Decimal(16),
    "seventeen": Decimal(17),
    "eighteen": Decimal(18),
    "nineteen": Decimal(19),
    "twenty": Decimal(20),
    "thirty": Decimal(30),
    "forty": Decimal(40),
    "fifty": Decimal(50),
    "sixty": Decimal(60),
    "seventy": Decimal(70),
    "eighty": Decimal(80),
    "ninety": Decimal(90),
    # Romanised Hindi
    "ek": Decimal(1),
    "teen": Decimal(3),
    "char": Decimal(4),
    "chaar": Decimal(4),
    "paanch": Decimal(5),
    "panch": Decimal(5),
    "chhe": Decimal(6),
    "saat": Decimal(7),
    "aath": Decimal(8),
    "nau": Decimal(9),
    "das": Decimal(10),
    "bees": Decimal(20),
    "pachees": Decimal(25),
    "tees": Decimal(30),
    "pachas": Decimal(50),
    "dedh": Decimal("1.5"),
    "derh": Decimal("1.5"),
    "dhai": Decimal("2.5"),
    "dhaai": Decimal("2.5"),
    # Devanagari (Hindi and Marathi), after nukta and chandrabindu folding
    "एक": Decimal(1),
    "दो": Decimal(2),
    "दोन": Decimal(2),
    "तीन": Decimal(3),
    "चार": Decimal(4),
    "पांच": Decimal(5),
    "पाच": Decimal(5),
    "छह": Decimal(6),
    "सहा": Decimal(6),
    "सात": Decimal(7),
    "आठ": Decimal(8),
    "नौ": Decimal(9),
    "नऊ": Decimal(9),
    "दस": Decimal(10),
    "दहा": Decimal(10),
    "बीस": Decimal(20),
    "पच्चीस": Decimal(25),
    "तीस": Decimal(30),
    "पचास": Decimal(50),
    "डेढ": Decimal("1.5"),
    "दीड": Decimal("1.5"),
    "ढाई": Decimal("2.5"),
    "अडीच": Decimal("2.5"),
}
# "saade teen" is three and a half.
_HALF_MORE = {"saade", "sade", "साढे", "साडे"}
_MONEY_UNITS: dict[str, int] = {
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "lk": 100_000,
    "l": 100_000,
    "लाख": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
    "करोड": 10_000_000,
    "कोटी": 10_000_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "k": 1_000,
    "hazar": 1_000,
    "hazaar": 1_000,
    "हजार": 1_000,
}
_CURRENCY = {"₹", "rs", "inr", "rupees", "rupee", "rupaye", "rupay", "रुपये", "रुपए", "रु", "/-"}
_RANGE = {"to", "or", "se", "ya", "से", "ते", "या", "किंवा", "-", "–", "~"}
_SIZE_UNITS: dict[str, tuple[Unit, int]] = {
    "kw": ("kW", 1),
    "kilowatt": ("kW", 1),
    "kilowatts": ("kW", 1),
    "किलोवाट": ("kW", 1),
    "kva": ("kVA", 1),
    "w": ("kW", 1000),
    "watt": ("kW", 1000),
    "watts": ("kW", 1000),
    "वाट": ("kW", 1000),
    "va": ("kVA", 1000),
}
# Units that make a number something other than money (power, energy, area, years).
_OTHER_UNITS = set(_SIZE_UNITS) | {
    "kwh",
    "mah",
    "ah",
    "v",
    "volt",
    "volts",
    "sq",
    "sqft",
    "ft",
    "feet",
    "unit",
    "units",
    "ton",
    "tons",
}
_GST = ("gst", "जीएसटी")
_INCLUDED = ("incl", "inclusive", "with gst", "gst included", "gst ke saath", "सहित", "समेत")
_EXCLUDED = ("excl", "exclusive", "plus gst", "+ gst", "+gst", "without gst", "extra", "अलग")
_MAX_INR = 10_000_000_000


def normalise(text: str) -> str:
    """NFKC, case-folded, Devanagari digits as ASCII, nukta and chandrabindu folded,
    digit-group commas removed and whitespace collapsed."""
    value = unicodedata.normalize("NFKC", text).casefold().translate(_DEVANAGARI_DIGITS)
    value = value.replace("़", "").replace("ँ", "ं")
    value = re.sub(r"(?<=\d),(?=\d)", "", value)
    value = re.sub(r"(?<=[a-z])\.(?=[a-z])", "", value)  # k.w. -> kw.
    return " ".join(value.split())


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalise(text))


def _number(tokens: list[str], index: int) -> tuple[Decimal, int] | None:
    """The number starting at ``index`` and how many tokens it used."""
    token = tokens[index]
    if token in _HALF_MORE and index + 1 < len(tokens):
        following = _number(tokens, index + 1)
        if following is not None and following[0] == following[0].to_integral_value():
            return following[0] + Decimal("0.5"), following[1] + 1
        return None
    if token[0].isdigit():
        try:
            return Decimal(token), 1
        except InvalidOperation:
            return None
    if token in _WORDS:
        return _WORDS[token], 1
    return None


def _quantities(tokens: list[str]) -> tuple[list[tuple[Decimal, str | None]], bool]:
    """(value, following unit token) for every number, and whether a range word appears."""
    found: list[tuple[Decimal, str | None]] = []
    ranged = any(token in _RANGE for token in tokens)
    index = 0
    while index < len(tokens):
        parsed = _number(tokens, index)
        if parsed is None:
            index += 1
            continue
        value, used = parsed
        index += used
        unit = tokens[index] if index < len(tokens) else None
        if unit == "kilo" and index + 1 < len(tokens) and tokens[index + 1].startswith("watt"):
            unit, index = "kw", index + 1
        found.append((value, unit))
    return found, ranged


def numbers_in(text: str) -> set[Decimal]:
    """Every number said in ``text`` (digits, number words, "saade teen")."""
    return {value for value, _ in _quantities(_tokens(text))[0]}


def amount_inr(stated_as: str) -> int | None:
    """Rupees from the exact words said, or None when the words are ambiguous."""
    tokens = [token for token in _tokens(stated_as) if token not in _CURRENCY]
    quantities, ranged = _quantities(tokens)
    if not quantities or ranged:
        return None
    if len(quantities) == 1:
        value, unit = quantities[0]
        if unit in _MONEY_UNITS:
            total = value * _MONEY_UNITS[unit]
        elif value == value.to_integral_value() and value >= 1000 and unit not in _OTHER_UNITS:
            total = value
        else:
            return None
    else:
        # "3 lakh 70 thousand": every part has a money unit, each smaller than the last.
        total = Decimal(0)
        previous: int | None = None
        for value, unit in quantities:
            scale = _MONEY_UNITS.get(unit or "")
            if scale is None or (previous is not None and scale >= previous):
                return None
            total += value * scale
            previous = scale
    if total != total.to_integral_value() or not 0 < total <= _MAX_INR:
        return None
    return int(total)


def system_size(stated_as: str) -> tuple[int | float | None, Unit | None]:
    """(quantity, unit) from the words said; (None, None) when ambiguous."""
    quantities, ranged = _quantities(_tokens(stated_as))
    if len(quantities) != 1 or ranged:
        return None, None
    value, unit_token = quantities[0]
    unit: Unit | None = None
    if unit_token in _SIZE_UNITS:
        unit, divisor = _SIZE_UNITS[unit_token]
        value = value / divisor
    if value <= 0 or value > 100_000:
        return None, None
    rounded = value.quantize(Decimal("0.01"))
    if rounded != value:
        return None, None
    quantity: int | float = int(value) if value == value.to_integral_value() else float(rounded)
    return quantity, unit


def mentions_price(text: str, *, plain_numbers: bool = True) -> bool:
    """True when words carry a price: a currency word, a money unit after a number,
    or (with ``plain_numbers``) a bare number of 1,000 or more that is not a year
    or a power, energy or area figure."""
    tokens = _tokens(text)
    if any(token in _CURRENCY for token in tokens):
        return True
    for value, unit in _quantities(tokens)[0]:
        if unit in _MONEY_UNITS:
            return True
        if (
            plain_numbers
            and value >= 1000
            and unit not in _OTHER_UNITS
            and not (value == value.to_integral_value() and 1900 <= value <= 2100)
        ):
            return True
    return False


def gst_basis(text: str) -> Literal["incl_gst", "ex_gst"] | None:
    """GST basis only when the words said name GST with one clear cue."""
    value = normalise(text)
    if not any(word in value for word in _GST):
        return None
    included = any(cue in value for cue in _INCLUDED)
    excluded = any(cue in value for cue in _EXCLUDED)
    if included == excluded:
        return None
    return "incl_gst" if included else "ex_gst"
