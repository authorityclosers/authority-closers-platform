"""Deterministic readers for the words a speaker said (partner quote facts v1).

The model never supplies an amount, a size or a count that we pass on. It
quotes the words said (``stated_as``) and these functions read numbers from
those words only:

- ``amount_inr``: "3.70 lakh" -> 370000, "45k" -> 45000, "3,70,000" ->
  370000, "1.2 crore" -> 12000000, "teen lakh sattar hazaar" -> 370000,
  "दो लाख साठ हजार" -> 260000, "सवा दो लाख" -> 225000, "paune teen lakh"
  -> 275000. Anything ambiguous or only partly read is ``None``: a bare small
  number ("3.70"), a range ("about 3 to 4"), an unread word before a number
  ("about 3 lakh", "dho lakh"), a money word that no number owns ("above a
  lakh"), hundreds ("paanch sau"), or a fraction word we do not read exactly
  ("saade do lakh").
- ``system_size``: "5 kW" -> (5, "kW"), "10 kva" -> (10, "kVA"),
  "5000 watt" -> (5, "kW"), "five" -> (5, None); a range or two numbers ->
  (None, None).
- ``numbers_in``: every number said, for checking a year; ``counts_in``: the
  numbers that are not next to a money, currency or cost word, for a count.
- ``mentions_price``: whether words carry a price, so no fact type other than
  ``mentioned_price`` ever passes one on.
- ``gst_basis``: "incl_gst" / "ex_gst" only when GST was said with one clear
  cue, matched on whole words.
- ``mask_amounts``: the text with every amount replaced by "[amount]" (used
  for the event summary).

English, romanised Hindi, Devanagari (Hindi and Marathi) and Devanagari
digits are read. Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Literal

Unit = Literal["kW", "kVA"]
MASK = "[amount]"

_DEVANAGARI_DIGITS = {ord(chr(0x0966 + n)): str(n) for n in range(10)}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[ऀ-ॣॱ-ॿ]+|₹|/-|[-–~+]")
# The same token classes on the original text (Devanagari digits and digit-group
# commas included), so a span can be masked in place.
_RAW_TOKEN = re.compile(r"[0-9०-९]+(?:[.,][0-9०-९]+)*|[ऀ-ॣॱ-ॿ]+|[A-Za-z]+|₹|/-|[-–~+]")

_ONES_EN: dict[str, Decimal] = {
    "one": Decimal(1),
    "two": Decimal(2),
    "three": Decimal(3),
    "four": Decimal(4),
    "five": Decimal(5),
    "six": Decimal(6),
    "seven": Decimal(7),
    "eight": Decimal(8),
    "nine": Decimal(9),
}
_TENS_EN: dict[str, Decimal] = {
    "twenty": Decimal(20),
    "thirty": Decimal(30),
    "forty": Decimal(40),
    "fifty": Decimal(50),
    "sixty": Decimal(60),
    "seventy": Decimal(70),
    "eighty": Decimal(80),
    "ninety": Decimal(90),
}
NUMBER_WORDS: dict[str, Decimal] = {
    # English ("twenty five" reads as 25; "twenty-five" is a range sign and reads nothing).
    **_ONES_EN,
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
    **_TENS_EN,
    # Romanised Hindi, unambiguous spellings only. Left out on purpose: "saath"
    # and "sath" (60, also "with"), "bara" (also "big"), "tera" (also "your"),
    # "sola", "che". An unread word before a money unit makes the amount None.
    "ek": Decimal(1),
    "do": Decimal(2),
    "teen": Decimal(3),
    "char": Decimal(4),
    "chaar": Decimal(4),
    "paanch": Decimal(5),
    "panch": Decimal(5),
    "chhe": Decimal(6),
    "chhah": Decimal(6),
    "saat": Decimal(7),
    "aath": Decimal(8),
    "nau": Decimal(9),
    "das": Decimal(10),
    "gyarah": Decimal(11),
    "barah": Decimal(12),
    "terah": Decimal(13),
    "chaudah": Decimal(14),
    "pandrah": Decimal(15),
    "solah": Decimal(16),
    "satrah": Decimal(17),
    "atharah": Decimal(18),
    "unnis": Decimal(19),
    "bees": Decimal(20),
    "pachees": Decimal(25),
    "pachchis": Decimal(25),
    "tees": Decimal(30),
    "chalees": Decimal(40),
    "chalis": Decimal(40),
    "pachas": Decimal(50),
    "pachaas": Decimal(50),
    "sattar": Decimal(70),
    "assi": Decimal(80),
    "nabbe": Decimal(90),
    "dedh": Decimal("1.5"),
    "derh": Decimal("1.5"),
    "dhai": Decimal("2.5"),
    "dhaai": Decimal("2.5"),
    # Devanagari Hindi, after nukta and chandrabindu folding
    "एक": Decimal(1),
    "दो": Decimal(2),
    "तीन": Decimal(3),
    "चार": Decimal(4),
    "पांच": Decimal(5),
    "छह": Decimal(6),
    "छः": Decimal(6),
    "सात": Decimal(7),
    "आठ": Decimal(8),
    "नौ": Decimal(9),
    "दस": Decimal(10),
    "ग्यारह": Decimal(11),
    "बारह": Decimal(12),
    "तेरह": Decimal(13),
    "चौदह": Decimal(14),
    "पंद्रह": Decimal(15),
    "पन्द्रह": Decimal(15),
    "सोलह": Decimal(16),
    "सत्रह": Decimal(17),
    "अठारह": Decimal(18),
    "उन्नीस": Decimal(19),
    "बीस": Decimal(20),
    "पच्चीस": Decimal(25),
    "तीस": Decimal(30),
    "चालीस": Decimal(40),
    "पचास": Decimal(50),
    "साठ": Decimal(60),
    "सत्तर": Decimal(70),
    "अस्सी": Decimal(80),
    "नब्बे": Decimal(90),
    "डेढ": Decimal("1.5"),
    "ढाई": Decimal("2.5"),
    # Devanagari Marathi (the shared words are above)
    "दोन": Decimal(2),
    "पाच": Decimal(5),
    "सहा": Decimal(6),
    "नऊ": Decimal(9),
    "दहा": Decimal(10),
    "अकरा": Decimal(11),
    "बारा": Decimal(12),
    "तेरा": Decimal(13),
    "चौदा": Decimal(14),
    "पंधरा": Decimal(15),
    "सोळा": Decimal(16),
    "सतरा": Decimal(17),
    "अठरा": Decimal(18),
    "एकोणीस": Decimal(19),
    "वीस": Decimal(20),
    "पंचवीस": Decimal(25),
    "चाळीस": Decimal(40),
    "पन्नास": Decimal(50),
    "ऐंशी": Decimal(80),
    "नव्वद": Decimal(90),
    "दीड": Decimal("1.5"),
    "अडीच": Decimal("2.5"),
}
# A fraction word before a whole number: (step, smallest number it is used with).
# "saade teen" 3.5 (1.5 and 2.5 are dedh and dhai), "sawa do" 2.25, "paune teen" 2.75.
FRACTION_WORDS: dict[str, tuple[Decimal, int]] = {
    "saade": (Decimal("0.5"), 3),
    "sade": (Decimal("0.5"), 3),
    "साढे": (Decimal("0.5"), 3),
    "साडे": (Decimal("0.5"), 3),
    "sawa": (Decimal("0.25"), 1),
    "sava": (Decimal("0.25"), 1),
    "सवा": (Decimal("0.25"), 1),
    "सव्वा": (Decimal("0.25"), 1),
    "paune": (Decimal("-0.25"), 2),
    "पौने": (Decimal("-0.25"), 2),
    "पावणे": (Decimal("-0.25"), 2),
}
# Hundreds are never read as an amount ("paanch sau" is None), but they mark a price.
HUNDRED_WORDS = frozenset({"hundred", "hundreds", "sau", "सौ", "शे", "शंभर"})
_COMPOUND_HUNDREDS = frozenset({"दोनशे", "तीनशे", "चारशे", "पाचशे", "सहाशे", "सातशे", "आठशे", "नऊशे"})
MONEY_UNITS: dict[str, int] = {
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
    "karod": 10_000_000,
    "karor": 10_000_000,
    "करोड": 10_000_000,
    "कोटी": 10_000_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "k": 1_000,
    "hazar": 1_000,
    "hazaar": 1_000,
    "hajar": 1_000,
    "हजार": 1_000,
}
# Money words that mark a price anywhere; "k", "l" and "lk" only right after a number.
_SHORT_UNITS = frozenset({"k", "l", "lk"})
_MONEY_WORDS = frozenset(MONEY_UNITS) - _SHORT_UNITS
_CURRENCY_WORDS = frozenset({"₹", "rs", "inr", "रु", "/-"})
# Rupee spellings: rupees, rupee, rupaye, rupiya, rupaiya, rupya, ruppees; रुपये, रुपया, रूपये ...
_CURRENCY_PREFIX = re.compile(r"^(?:ru+p+[aeiy][a-z]*|रुपय|रूपय|रुपए|रूपए|रुपै|रूपै)")
COST_WORDS = frozenset(
    {
        "charge",
        "charges",
        "cost",
        "costs",
        "costing",
        "price",
        "prices",
        "priced",
        "pricing",
        "rate",
        "rates",
        "budget",
        "kimat",
        "keemat",
        "kimmat",
        "कीमत",
        "किमत",
        "दाम",
        "किंमत",
        "बजट",
    }
)
_RANGE = {"to", "or", "se", "ya", "से", "ते", "या", "किंवा", "-", "–", "~"}
_JOINERS = _RANGE | {"and", "aur", "और", "ani", "आणि", "+"}
# One short word allowed between a cost word and its number ("charges of 50", "50 ka charge").
_CONNECTORS = frozenset(
    {"of", "is", "was", "for", "ka", "ki", "ke", "hai", "का", "की", "के", "है", "चा", "ची", "चे"}
)
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
# Units that make a number something other than money (power, energy, size, length, years).
_OTHER_UNITS = set(_SIZE_UNITS) | {
    "kwh",
    "kwp",
    "wp",
    "mah",
    "ah",
    "v",
    "volt",
    "volts",
    "sq",
    "sqft",
    "sqm",
    "square",
    "ft",
    "feet",
    "foot",
    "m",
    "mm",
    "cm",
    "km",
    "meter",
    "meters",
    "metre",
    "metres",
    "mtr",
    "inch",
    "inches",
    "kg",
    "kgs",
    "litre",
    "litres",
    "liter",
    "liters",
    "ltr",
    "hp",
    "rpm",
    "cell",
    "cells",
    "unit",
    "units",
    "ton",
    "tons",
    "year",
    "years",
    "saal",
    "साल",
    "वर्ष",
    "वर्षे",
}
# A number above this with no unit, in a field that is not a price, is taken as a price
# ("packing 500"); add-on counts are capped at the same number.
PLAIN_PRICE_FLOOR = 100
_GST = ("gst", "जीएसटी")
_INCLUDED = (
    "incl",
    "including",
    "inclusive",
    "included",
    "with gst",
    "gst ke saath",
    "gst ke sath",
    "gst sahit",
    "सहित",
    "समेत",
    "धरून",
)
_EXCLUDED = (
    "excl",
    "excluding",
    "exclusive",
    "excluded",
    "plus gst",
    "+ gst",
    "+gst",
    "without gst",
    "extra",
    "alag",
    "अलग",
    "अतिरिक्त",
    "वेगळा",
    "वेगळे",
)
_WORD_CLASS = "0-9a-zऀ-ॿ"
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


def is_currency(token: str) -> bool:
    """A normalised token that names rupees (any common spelling) or is a rupee sign."""
    return token in _CURRENCY_WORDS or bool(_CURRENCY_PREFIX.match(token))


def _is_digits(token: str) -> bool:
    return bool(token) and token[0].isdigit()


def _plain_number(tokens: list[str], index: int) -> tuple[Decimal, int] | None:
    token = tokens[index]
    if _is_digits(token):
        try:
            return Decimal(token), 1
        except InvalidOperation:
            return None
    if token in _TENS_EN and index + 1 < len(tokens) and tokens[index + 1] in _ONES_EN:
        return _TENS_EN[token] + _ONES_EN[tokens[index + 1]], 2
    value = NUMBER_WORDS.get(token)
    return (value, 1) if value is not None else None


def _number(tokens: list[str], index: int) -> tuple[Decimal, int] | None:
    """The number starting at ``index`` and how many tokens it used."""
    token = tokens[index]
    if token in FRACTION_WORDS:
        step, smallest = FRACTION_WORDS[token]
        following = _plain_number(tokens, index + 1) if index + 1 < len(tokens) else None
        if following is None:
            return None
        value, used = following
        if value != value.to_integral_value() or value < smallest:
            return None
        return value + step, used + 1
    return _plain_number(tokens, index)


def _quantities(tokens: list[str]) -> tuple[list[tuple[Decimal, str | None]], bool]:
    """(value, following unit token) for every number, and whether a range word appears."""
    found: list[tuple[Decimal, str | None]] = []
    ranged = any(token in _RANGE for token in tokens)
    index = 0
    while index < len(tokens):
        parsed = _number(tokens, index)
        if parsed is None:
            # A fraction word we do not read ("saade do") hides the number after it.
            index += 2 if tokens[index] in FRACTION_WORDS else 1
            continue
        value, used = parsed
        index += used
        unit = tokens[index] if index < len(tokens) else None
        if unit == "kilo" and index + 1 < len(tokens) and tokens[index + 1].startswith("watt"):
            unit, index = "kw", index + 1
        found.append((value, unit))
    return found, ranged


def numbers_in(text: str) -> set[Decimal]:
    """Every number said in ``text`` (digits, number words, "saade teen", "twenty five")."""
    return {value for value, _ in _quantities(_tokens(text))[0]}


def _priced(token: str | None) -> bool:
    return token is not None and (
        is_currency(token) or token in MONEY_UNITS or token in COST_WORDS or token in HUNDRED_WORDS
    )


def counts_in(text: str) -> set[Decimal]:
    """Numbers said in ``text`` that do not sit next to a money, currency or cost word
    ("packing charge 2" and "2 hazaar" give nothing)."""
    tokens = _tokens(text)
    found: set[Decimal] = set()
    index = 0
    while index < len(tokens):
        parsed = _number(tokens, index)
        if parsed is None:
            index += 2 if tokens[index] in FRACTION_WORDS else 1
            continue
        value, used = parsed
        before = tokens[index - 1] if index > 0 else None
        after = tokens[index + used] if index + used < len(tokens) else None
        if not (_priced(before) or _priced(after)):
            found.add(value)
        index += used
    return found


def is_numeric_word(token: str | None) -> bool:
    """Digits, a number word, a fraction word, or a money or hundred word."""
    if not token:
        return False
    value = normalise(token)
    return (
        bool(re.fullmatch(r"\d+(?:\.\d+)?", value))
        or value in NUMBER_WORDS
        or value in FRACTION_WORDS
        or value in MONEY_UNITS
        or value in HUNDRED_WORDS
        or value in _COMPOUND_HUNDREDS
    )


def amount_inr(stated_as: str) -> int | None:
    """Rupees from the exact words said, or None when any part is ambiguous or unread.

    Every number must own its money unit (or be one whole number of 1,000 or
    more), every money word must be owned by a number, no unread word may sit
    directly before a number, parts fall from crore to lakh to thousand, and
    only the last part may have a fraction. Hundreds and ranges are never read.
    """
    said = _tokens(stated_as)
    tokens = [token for token in said if not is_currency(token)]
    rupees_said = len(tokens) < len(said)
    if not tokens or any(token in _RANGE or token in HUNDRED_WORDS for token in tokens):
        return None
    groups: list[tuple[Decimal, str | None, bool]] = []  # value, next token, owns a money unit
    after_word = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        parsed = _number(tokens, index)
        if parsed is None:
            if token in FRACTION_WORDS or token in MONEY_UNITS or token in _COMPOUND_HUNDREDS:
                return None  # an unread fraction word, or a money word no number owns
            after_word = token[0].isalpha()  # a word ("about", "dho"), not a sign
            index += 1
            continue
        if after_word:
            return None  # an unread word directly before a number ("about 3 lakh")
        value, used = parsed
        index += used
        following = tokens[index] if index < len(tokens) else None
        owns = following in MONEY_UNITS
        if owns:
            index += 1
        groups.append((value, following, owns))
    if not groups:
        return None
    if len(groups) == 1:
        value, following, owns = groups[0]
        if owns and following is not None:
            total = value * MONEY_UNITS[following]
        elif (
            value == value.to_integral_value()
            and value >= 1000
            and following not in _OTHER_UNITS
            and (rupees_said or not _year(value))  # a bare "2000" may be a year
        ):
            total = value
        else:
            return None
    else:
        # "3 lakh 70 thousand": each part owns a smaller money unit than the part before,
        # is smaller than that unit, and only the last part may have a fraction.
        total = Decimal(0)
        previous: int | None = None
        for number, (value, following, owns) in enumerate(groups):
            if not owns or following is None:
                return None
            scale = MONEY_UNITS[following]
            part = value * scale
            if previous is not None and (scale >= previous or part >= previous):
                return None
            if number < len(groups) - 1 and value != value.to_integral_value():
                return None
            total += part
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


def _year(value: Decimal) -> bool:
    return value == value.to_integral_value() and 1900 <= value <= 2100


def mentions_price(text: str, *, plain_numbers: bool = True) -> bool:
    """True when words carry a price.

    - a currency word or sign (any rupee spelling) or a money word (lakh,
      crore, thousand, hazaar, लाख, करोड, कोटी, हजार ...) anywhere;
    - a cost word (price, charge, rate, kimat, कीमत, दाम, किंमत ...) with any
      number that is not a power, size or length figure;
    - a number followed by a money unit or a hundred word ("45k", "paanch sau");
    - with ``plain_numbers``: a number above 100 that is not a year or a unit
      figure ("packing 500"), or a Marathi hundred ("पाचशे").
    """
    tokens = _tokens(text)
    if any(is_currency(token) or token in _MONEY_WORDS for token in tokens):
        return True
    quantities = _quantities(tokens)[0]
    if any(token in COST_WORDS for token in tokens) and any(
        unit not in _OTHER_UNITS for _, unit in quantities
    ):
        return True
    if plain_numbers and any(token in _COMPOUND_HUNDREDS for token in tokens):
        return True
    for value, unit in quantities:
        if unit in MONEY_UNITS or unit in HUNDRED_WORDS:
            return True
        if (
            plain_numbers
            and value > PLAIN_PRICE_FLOOR
            and unit not in _OTHER_UNITS
            and not _year(value)
        ):
            return True
    return False


def _cue(text: str, cue: str) -> bool:
    """``cue`` in normalised ``text`` as whole words (no letter or digit on either side)."""
    word = f"[{_WORD_CLASS}]"
    before = f"(?<!{word})" if re.match(word, cue[0]) else ""
    after = f"(?!{word})" if re.match(word, cue[-1]) else ""
    return re.search(before + re.escape(cue) + after, text) is not None


def gst_basis(text: str) -> Literal["incl_gst", "ex_gst"] | None:
    """GST basis only when the words name GST with one clear cue (whole words only).

    The caller passes a price's own ``stated_as``, so a cue said about another
    price in the same segment never attaches to this one.
    """
    value = normalise(text)
    if not any(_cue(value, word) for word in _GST):
        return None
    included = any(_cue(value, cue) for cue in _INCLUDED)
    excluded = any(_cue(value, cue) for cue in _EXCLUDED)
    if included == excluded:
        return None
    return "incl_gst" if included else "ex_gst"


# --- masking amounts in free text ---------------------------------------------------------


def _kinds(norms: list[str], gaps: list[str]) -> list[str]:
    """num, unit, cur, join, article or other per token; ``gaps[i]`` precedes token i."""
    kinds: list[str] = []
    for index, token in enumerate(norms):
        following = norms[index + 1] if index + 1 < len(norms) else None
        previous = kinds[index - 1] if index else None
        spaced = gaps[index].strip() == ""
        if is_currency(token):
            kind = "cur"
        elif token in _MONEY_WORDS:
            kind = "unit"
        elif token in _SHORT_UNITS:
            tight = index > 0 and spaced and len(gaps[index]) <= 1
            kind = "unit" if tight and _is_digits(norms[index - 1]) else "other"
        elif token in HUNDRED_WORDS:
            kind = "unit" if previous == "num" and spaced else "other"
        elif (
            _is_digits(token)
            or token in NUMBER_WORDS
            or token in FRACTION_WORDS
            or token in _COMPOUND_HUNDREDS
        ):
            # A number that owns a power, size, length or time unit is not money ("5 kW").
            kind = "other" if following in _OTHER_UNITS else "num"
        elif token in _JOINERS:
            kind = "join"
        elif token in {"a", "an"}:
            kind = "article"
        else:
            kind = "other"
        kinds.append(kind)
    return kinds


def _digits_value(token: str) -> Decimal | None:
    if not _is_digits(token):
        return None
    try:
        return Decimal(token)
    except InvalidOperation:
        return None


def mask_amounts(text: str) -> str:
    """``text`` with every amount replaced by "[amount]" (idempotent).

    Masked: a money word with the numbers that own it ("teen lakh sattar
    hazaar", "दो लाख साठ हजार", "45k"; "above a lakh" -> "above [amount]"); a
    currency word or sign with its number ("₹3.7L", "Rs. 3,70,000", "500
    rupaiya"); a number above 100 that is not a year or a unit figure; a number
    next to a cost word ("packing charge 50"). Power, size, length and time
    figures ("5 kW", "1500 sq ft", "5 years") and years stay.
    """
    found = list(_RAW_TOKEN.finditer(text))
    if not found:
        return text
    count = len(found)
    norms = [normalise(match.group()) for match in found]
    gaps = [""] + [text[found[index - 1].end() : found[index].start()] for index in range(1, count)]
    kinds = _kinds(norms, gaps)
    parts_of_amount = {"num", "unit", "cur", "join", "article"}
    spans: list[tuple[int, int]] = []

    def joined(left: int, right: int) -> bool:
        gap = gaps[right].strip()
        return gap == "" or (kinds[left] == "cur" and gap == ".")

    index = 0
    while index < count:
        if kinds[index] not in parts_of_amount:
            index += 1
            continue
        end = index
        while end + 1 < count and kinds[end + 1] in parts_of_amount and joined(end, end + 1):
            end += 1
        run = list(range(index, end + 1))
        # Joiners only join; an article counts only right before a money word.
        while run and (
            kinds[run[0]] == "join"
            or (kinds[run[0]] == "article" and (len(run) < 2 or kinds[run[1]] != "unit"))
        ):
            run.pop(0)
        while run and kinds[run[-1]] in {"join", "article"}:
            run.pop()
        present = {kinds[item] for item in run}
        if "unit" in present or {"cur", "num"} <= present:
            spans.append((found[run[0]].start(), found[run[-1]].end()))
        index = end + 1

    for index, kind in enumerate(kinds):
        if kind != "num":
            continue
        value = _digits_value(norms[index])
        big = norms[index] in _COMPOUND_HUNDREDS or (
            value is not None and value > PLAIN_PRICE_FLOOR and not _year(value)
        )
        near_cost = False
        for other in (index - 2, index - 1, index + 1, index + 2):
            if not 0 <= other < count or norms[other] not in COST_WORDS:
                continue
            between = range(min(index, other) + 1, max(index, other))
            if all(norms[step] in _CONNECTORS for step in between):
                near_cost = True
        if big or near_cost:
            spans.append((found[index].start(), found[index].end()))

    if not spans:
        return text
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        pieces.append(text[cursor:start])
        pieces.append(MASK)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)
