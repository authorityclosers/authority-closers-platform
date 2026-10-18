"""Deterministic readers for the words a speaker said (partner quote facts v1).

The model never supplies an amount, a size or a count that we pass on. It
quotes the words said (``stated_as``) and these functions read numbers from
those words only:

- ``amount_inr``: "3.70 lakh" -> 370000, "45k" -> 45000, "3,70,000" ->
  370000, "1.2 crore" -> 12000000, "teen lakh sattar hazaar" -> 370000,
  "दो लाख साठ हजार" -> 260000, "सवा दो लाख" -> 225000, "paune teen lakh"
  -> 275000, "पाच लाखांचे" -> 500000. Anything ambiguous or only partly read
  is ``None``: a bare small number ("3.70"), a range ("about 3 to 4"), an
  unread word before a number ("about 3 lakh", "dho lakh"), a money word that
  no number owns ("above a lakh"), hundreds ("paanch sau"), a fraction word
  we do not read exactly ("saade do lakh"), a per-unit price ("₹60,000 per
  kW", "₹45/W", "60000 each") or a cap ("4 lakh max", "3.5 lakh tak", "तीन
  लाखांत").
- ``system_size``: "5 kW" -> (5, "kW"), "10 kva" -> (10, "kVA"),
  "5000 watt" -> (5, "kW"), "five" -> (5, None); a range or two numbers ->
  (None, None).
- ``numbers_in``: every number said, for checking a year; ``counts_in``: the
  numbers that are not next to a money, currency or cost word, for a count.
- ``number_join``: whether two words said in a row read as one number, for
  the evidence check ("twenty five", "sawa do", "3 lakh 70 thousand").
- ``mentions_price``: whether words carry a price, so no fact type other than
  ``mentioned_price`` ever passes one on.
- ``gst_basis``: "incl_gst" / "ex_gst" only when GST was said with one clear
  cue, matched on whole words.
- ``mask_amounts``: the text with every amount replaced by "[amount]" (used
  for the event summary).

English, romanised Hindi, Devanagari (Hindi and Marathi, with their case
endings: लाखांत, हजारांचा, कोटींचा) and Devanagari digits are read. Nothing here
calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Literal

Unit = Literal["kW", "kVA"]
Join = Literal["hard", "soft"]
MASK = "[amount]"

_DEVANAGARI_DIGITS = {ord(chr(0x0966 + n)): str(n) for n in range(10)}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[ऀ-ॣॱ-ॿ]+|₹|/-|/|[-–~+]")
# The same token classes on the original text (Devanagari digits, digit-group commas and
# the old rupee sign included), so a span can be masked in place.
_RAW_TOKEN = re.compile(r"[0-9०-९]+(?:[.,][0-9०-९]+)*|[ऀ-ॣॱ-ॿ]+|[A-Za-z]+|₹|₨|/-|[-–~+]")
# Numbers written with digit-group commas ("1,999", "3,70,000"): never a year.
_GROUPED = re.compile(r"(?<![0-9.,])[0-9]{1,3}(?:,[0-9]{2,3})+(?![0-9])")

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
# English ("twenty five" reads as 25; "twenty-five" is a range sign and reads nothing).
_EN_NUMBER_WORDS: dict[str, Decimal] = {
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
}
# Romanised Hindi, unambiguous spellings only. Left out on purpose: "saath" and "sath"
# (60, also "with"), "bara" (also "big"), "tera" (also "your"), "sola", "che". An unread
# word before a money unit makes the amount None.
_HI_NUMBER_WORDS: dict[str, Decimal] = {
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
}
_DEVA_NUMBER_WORDS: dict[str, Decimal] = {
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
NUMBER_WORDS: dict[str, Decimal] = {
    **_EN_NUMBER_WORDS,
    **_HI_NUMBER_WORDS,
    **_DEVA_NUMBER_WORDS,
}
# Number words that are far more often ordinary words: English "do" and Hindi "do" (give),
# "one" (the one, one of). They join a neighbour only when they directly form an amount.
_EVERYDAY_WORDS = frozenset({"do", "one"})
# "do" before these is the English verb, never "two" ("do you want 1 dongle").
_AFTER_DO_VERB = frozenset(
    {"you", "u", "we", "i", "they", "it", "not", "the", "a", "an", "this", "that", "your"}
)
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
# Words that make part of a spoken number with "and"/"point" ("one and a half lakh",
# "three point seven lakh"); masked with the amount they belong to, never alone.
_PART_WORDS = frozenset({"half", "quarter", "point"})
MONEY_UNITS: dict[str, int] = {
    "lakh": 100_000,
    "lakhs": 100_000,
    "lakhon": 100_000,
    "laakh": 100_000,
    "laakhs": 100_000,
    "laakhon": 100_000,
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
    "karodon": 10_000_000,
    "karoron": 10_000_000,
    "करोड": 10_000_000,
    "कोटी": 10_000_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "k": 1_000,
    "hazar": 1_000,
    "hazaar": 1_000,
    "hajar": 1_000,
    "hajaar": 1_000,
    "hazaron": 1_000,
    "hazaaron": 1_000,
    "hajaron": 1_000,
    "hajaaron": 1_000,
    "हजार": 1_000,
}
# Devanagari money words with a case ending or plural (लाखांत, लाखांपर्यंत, हजारांचा, लाखों,
# करोडचा, कोटींचा). A closed list of endings, so names and places (हजारीबाग) never match.
_DEVA_MONEY_STEMS = {"लाख": 100_000, "हजार": 1_000, "करोड": 10_000_000, "कोटी": 10_000_000}
_DEVA_MONEY = re.compile(
    r"(लाख|हजार|करोड|कोटी)(ों|ो|ां|ा|ं)?"
    r"(चा|ची|चे|च्या|त|तच|ना|ला|पर्यंत|मध्ये|वर|नी|ने|हून|पेक्षा|शी|साठी|च|ही|भर)?"
)
# Endings that make the amount a cap or a guess ("तीन लाखांत" within three lakh,
# "लाखांपर्यंत" up to, "लाखभर" about a lakh): the amount is not read.
_CAP_ENDINGS = frozenset({"त", "तच", "पर्यंत", "भर"})
# Money words that mark a price anywhere; "k", "l" and "lk" only right after a number.
_SHORT_UNITS = frozenset({"k", "l", "lk"})
# Rupee words: a closed list, so names (Rupesh, Rupali, Rupinder) are never rupees.
_CURRENCY_WORDS = frozenset(
    {
        "₹",
        "rs",
        "inr",
        "रु",
        "रू",
        "/-",
        "rupee",
        "rupees",
        "ruppee",
        "ruppees",
        "rupay",
        "rupaye",
        "rupaiye",
        "rupaya",
        "rupaiya",
        "rupaiyaa",
        "rupaiyya",
        "rupiya",
        "rupiyaa",
        "rupiye",
        "rupya",
        "rupye",
        "rupayon",
        "rupiyon",
        "rupaiyon",
        "rupia",
        "rupies",
    }
)
# Devanagari rupee words: रुपये, रुपया, रुपए, रूपये, रुपयों, रुपै ...
_CURRENCY_PREFIX = re.compile(r"^(?:रुपय|रूपय|रुपए|रूपए|रुपै|रूपै)")
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
        "बजेट",
    }
)
_RANGE = {"to", "or", "se", "ya", "से", "ते", "या", "किंवा", "-", "–", "~"}
_JOINERS = _RANGE | {"and", "aur", "और", "ani", "आणि", "+"}
# One short word allowed between a cost word and its number ("charges of 50", "50 ka charge").
_CONNECTORS = frozenset(
    {"of", "is", "was", "for", "ka", "ki", "ke", "hai", "का", "की", "के", "है", "चा", "ची", "चे"}
)
# Words after a number that keep it a price after "of"/"for" ("charges of 50 only").
_PRICE_TAIL = frozenset({"only", "extra", "plus", "final", "fixed", "total", "hi", "ही"})
# Words after a number that make it a per-unit price ("45 per watt", "₹45/W", "₹45 प्रति वाट").
_PER_WORDS = frozenset({"per", "प्रति", "/"})
# Words that make an amount a per-unit price, a cap or a guess: the amount is not read.
_NOT_A_TOTAL = _PER_WORDS | {
    "each",
    "har",
    "हर",
    "प्रत्येक",
    "max",
    "maximum",
    "upto",
    "tak",
    "तक",
    "पर्यंत",
    "min",
    "minimum",
    "least",
    "atleast",
    "approx",
    "approximately",
    "around",
    "about",
    "lagbhag",
    "लगभग",
    "karib",
    "kareeb",
    "करीब",
    "almost",
    "nearly",
    "under",
    "below",
    "above",
    "over",
    "within",
    "less",
    "more",
}
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
# Units a price is quoted per ("₹45/W", "60,000 per kW", "8 per unit", "₹55/Wp").
_PER_UNITS = set(_SIZE_UNITS) | {
    "kwh",
    "kwp",
    "wp",
    "ah",
    "unit",
    "units",
    "sq",
    "sqft",
    "sqm",
    "square",
    "ft",
    "feet",
    "foot",
    "m",
    "meter",
    "meters",
    "metre",
    "metres",
    "mtr",
    "kg",
    "kgs",
    "ton",
    "tons",
    "cell",
    "cells",
}
# Time words: "in 2 days", "by 6 pm", "3 baje" are never amounts.
_TIME_UNITS = frozenset(
    {
        "second",
        "seconds",
        "sec",
        "secs",
        "minute",
        "minutes",
        "min",
        "mins",
        "hour",
        "hours",
        "hr",
        "hrs",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "am",
        "pm",
        "din",
        "dino",
        "dinon",
        "hafta",
        "hafte",
        "mahina",
        "mahine",
        "ghanta",
        "ghante",
        "baje",
        "minat",
        "दिन",
        "दिनों",
        "हफ्ता",
        "हफ्ते",
        "महीना",
        "महीने",
        "घंटा",
        "घंटे",
        "बजे",
        "मिनट",
        "दिवस",
        "दिवसांत",
        "दिवसात",
        "आठवडा",
        "आठवड्यात",
        "महिना",
        "महिने",
        "महिन्यात",
        "तास",
        "तासात",
        "वाजता",
        "वाजे",
        "मिनिटे",
        "मिनिटांत",
    }
)
# Units that make a number something other than money (power, energy, size, length,
# years, time).
_OTHER_UNITS = (
    _PER_UNITS
    | _TIME_UNITS
    | {
        "mah",
        "v",
        "volt",
        "volts",
        "mm",
        "cm",
        "km",
        "inch",
        "inches",
        "litre",
        "litres",
        "liter",
        "liters",
        "ltr",
        "hp",
        "rpm",
        "kilo",
        "kilos",
        "year",
        "years",
        "saal",
        "साल",
        "वर्ष",
        "वर्षे",
    }
)
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


def _grouped(text: str) -> set[Decimal]:
    """Numbers written with digit-group commas in ``text``; such a number is never a year."""
    value = unicodedata.normalize("NFKC", text).translate(_DEVANAGARI_DIGITS)
    return {Decimal(found.group().replace(",", "")) for found in _GROUPED.finditer(value)}


def is_currency(token: str) -> bool:
    """A normalised token that names rupees (a known spelling) or is a rupee sign."""
    return token in _CURRENCY_WORDS or bool(_CURRENCY_PREFIX.match(token))


def money_scale(token: str | None) -> int | None:
    """Rupees one money word stands for ("lakh" 100000, "हजारांचा" 1000), else None."""
    if token is None:
        return None
    scale = MONEY_UNITS.get(token)
    if scale is not None:
        return scale
    found = _DEVA_MONEY.fullmatch(token)
    return _DEVA_MONEY_STEMS[found.group(1)] if found else None


def _money_word(token: str) -> bool:
    """A money word that marks a price anywhere (not "k", "l" or "lk" on their own)."""
    return token not in _SHORT_UNITS and money_scale(token) is not None


def _capped(token: str) -> bool:
    """A Devanagari money word whose ending makes it a cap or a guess ("लाखांत")."""
    found = _DEVA_MONEY.fullmatch(token)
    return found is not None and found.group(3) in _CAP_ENDINGS


def _joined_fraction(token: str) -> bool:
    """A fraction word written together with its number ("साडेतीन", "सव्वादोन", "पावणेतीन")."""
    return any(
        token.startswith(word) and token[len(word) :] in NUMBER_WORDS for word in FRACTION_WORDS
    )


def _is_digits(token: str) -> bool:
    return bool(token) and token[0].isdigit()


def _numberish(token: str) -> bool:
    """Digits, a number word, a fraction word (alone or joined) or a Marathi hundred."""
    return (
        _is_digits(token)
        or token in NUMBER_WORDS
        or token in FRACTION_WORDS
        or token in _COMPOUND_HUNDREDS
        or _joined_fraction(token)
    )


def _plain_number(tokens: list[str], index: int) -> tuple[Decimal, int] | None:
    word = tokens[index]
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    if _is_digits(word):
        try:
            return Decimal(word), 1
        except InvalidOperation:
            return None
    if word in _TENS_EN and following in _ONES_EN:
        return _TENS_EN[word] + _ONES_EN[following], 2
    if word == "do" and following in _AFTER_DO_VERB:
        return None  # "do you want 1 dongle": the English verb
    value = NUMBER_WORDS.get(word)
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


def _spans(tokens: list[str]) -> Iterator[tuple[int, Decimal, int, str | None]]:
    """(start, value, end, following unit token) for every number; ``end`` is past it."""
    index = 0
    while index < len(tokens):
        parsed = _number(tokens, index)
        if parsed is None:
            # A fraction word we do not read ("saade do") hides the number after it.
            index += 2 if tokens[index] in FRACTION_WORDS else 1
            continue
        value, used = parsed
        start, index = index, index + used
        end = index
        unit = tokens[index] if index < len(tokens) else None
        if unit == "kilo" and index + 1 < len(tokens) and tokens[index + 1].startswith("watt"):
            unit, index = "kw", index + 1
        yield start, value, end, unit


def _quantities(tokens: list[str]) -> tuple[list[tuple[Decimal, str | None]], bool]:
    """(value, following unit token) for every number, and whether a range word appears."""
    ranged = any(token in _RANGE for token in tokens)
    return [(value, unit) for _, value, _, unit in _spans(tokens)], ranged


def numbers_in(text: str) -> set[Decimal]:
    """Every number said in ``text`` (digits, number words, "saade teen", "twenty five")."""
    return {value for value, _ in _quantities(_tokens(text))[0]}


def _priced(token: str | None) -> bool:
    return token is not None and (
        is_currency(token)
        or money_scale(token) is not None
        or token in COST_WORDS
        or token in HUNDRED_WORDS
    )


def counts_in(text: str) -> set[Decimal]:
    """Numbers said in ``text`` that do not sit next to a money, currency or cost word
    ("packing charge 2" and "2 hazaar" give nothing)."""
    tokens = _tokens(text)
    found: set[Decimal] = set()
    for start, value, end, _ in _spans(tokens):
        before = tokens[start - 1] if start > 0 else None
        after = tokens[end] if end < len(tokens) else None
        if not (_priced(before) or _priced(after)):
            found.add(value)
    return found


def _language(token: str) -> str | None:
    if token in _EN_NUMBER_WORDS:
        return "en"
    if token in _HI_NUMBER_WORDS:
        return "hi"
    return "deva" if token in _DEVA_NUMBER_WORDS else None


def number_join(left: str | None, right: str | None, right_next: str | None = None) -> Join | None:
    """Whether ``left right``, said in a row, read as one number.

    "hard": they are one number and neither half stands alone: digits next to
    digits ("3-5 kW"), a tens and a ones word ("twenty five"), a fraction word
    and its number ("sawa do"), "point" and a number, a number and its money or
    hundred word ("do lakh", "paanch sau"), or a money word and a number that
    owns a smaller money word ("3 lakh" | "70 thousand"). "soft": they may be
    one number or a range: a money word and a bare number ("3 lakh" | "70"),
    or two number words of the same language ("do teen lakh", "four five
    years"). None: a reader would not join them; "do" and "one" next to digits
    ("we can do 5 kW", "one 5 kW inverter"), or after a money word ("teen lakh
    do"), are ordinary words, and so is a number before a unit that is not
    money ("3 lakh" | "5 kW").
    """
    if not left or not right:
        return None
    left, right = normalise(left), normalise(right)
    following = normalise(right_next) if right_next else None
    left_number, right_number = _numberish(left), _numberish(right)
    if _is_digits(left) and _is_digits(right):
        return "hard"
    if left in _TENS_EN and right in _ONES_EN:
        return "hard"
    if left in FRACTION_WORDS and right_number:
        return "hard"
    if (left == "point" and right_number) or (left_number and right == "point"):
        return "hard"
    if left_number and (
        money_scale(right) is not None or right in HUNDRED_WORDS or right in _COMPOUND_HUNDREDS
    ):
        return "hard"
    scale = money_scale(left)
    if scale is not None and right_number:
        next_scale = money_scale(following)
        if next_scale is not None:
            return "hard" if next_scale < scale else None
        if following in _OTHER_UNITS or right in _EVERYDAY_WORDS:
            return None
        return "soft"
    if left_number and right_number:
        language = _language(left)
        if language is not None and language == _language(right):
            return "soft"
    return None


def amount_inr(stated_as: str) -> int | None:
    """Rupees from the exact words said, or None when any part is ambiguous or unread.

    Every number must own its money unit (or be one whole number of 1,000 or
    more), every money word must be owned by a number, no unread word may sit
    directly before a number, parts fall from crore to lakh to thousand, and
    only the last part may have a fraction. Hundreds, ranges, per-unit prices
    ("per kW", "/W", "each", "har") and caps or guesses ("max", "tak", "upto",
    "approx", "लाखांत") are never read.
    """
    said = _tokens(stated_as)
    tokens = [token for token in said if not is_currency(token)]
    rupees_said = len(tokens) < len(said)
    if not tokens or any(
        token in _RANGE or token in HUNDRED_WORDS or token in _NOT_A_TOTAL or _capped(token)
        for token in tokens
    ):
        return None
    grouped = _grouped(stated_as)
    groups: list[tuple[Decimal, str | None, int | None]] = []  # value, next token, its scale
    after_word = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        parsed = _number(tokens, index)
        if parsed is None:
            if (
                token in FRACTION_WORDS
                or money_scale(token) is not None
                or token in _COMPOUND_HUNDREDS
            ):
                return None  # an unread fraction word, or a money word no number owns
            after_word = token[0].isalpha()  # a word ("about", "dho"), not a sign
            index += 1
            continue
        if after_word:
            return None  # an unread word directly before a number ("about 3 lakh")
        value, used = parsed
        index += used
        following = tokens[index] if index < len(tokens) else None
        scale = money_scale(following)
        if scale is not None:
            index += 1
        groups.append((value, following, scale))
    if not groups:
        return None
    if len(groups) == 1:
        value, following, scale = groups[0]
        if scale is not None:
            total = value * scale
        elif (
            value == value.to_integral_value()
            and value >= 1000
            and following not in _OTHER_UNITS
            # A bare "2000" may be a year; "Rs 2000" and "2,000" are not.
            and (rupees_said or value in grouped or not _year(value))
        ):
            total = value
        else:
            return None
    else:
        # "3 lakh 70 thousand": each part owns a smaller money unit than the part before,
        # is smaller than that unit, and only the last part may have a fraction.
        total = Decimal(0)
        previous: int | None = None
        for number, (value, _, scale) in enumerate(groups):
            if scale is None:
                return None
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


def _near_cost(tokens: list[str], start: int, end: int) -> bool:
    """A cost word within two words of the number ``tokens[start:end]``, with only a
    connector between ("charges of 50", "50 ka charge"; not "price ... in 2 days").

    After "of" or "for", a number followed by the thing it counts is a count
    ("price for 2 ACs", "cost of 3 panels"), unless a price word follows it
    ("charges of 50 only").
    """
    after = tokens[end] if end < len(tokens) else None
    counted = after is not None and after[0].isalpha() and after not in _PRICE_TAIL
    for other in (start - 2, start - 1, end, end + 1):
        if not 0 <= other < len(tokens) or tokens[other] not in COST_WORDS:
            continue
        between = range(other + 1, start) if other < start else range(end, other)
        if not all(tokens[step] in _CONNECTORS for step in between):
            continue
        if other < start and counted and any(tokens[step] in {"of", "for"} for step in between):
            continue
        return True
    return False


def _per_unit(tokens: list[str], end: int) -> bool:
    """The number ending before ``end`` is quoted per unit ("45 per watt", "45/W")."""
    return end + 1 < len(tokens) and tokens[end] in _PER_WORDS and tokens[end + 1] in _PER_UNITS


def mentions_price(text: str, *, plain_numbers: bool = True) -> bool:
    """True when words carry a price.

    - a currency word or sign (a known rupee spelling) or a money word (lakh,
      crore, thousand, hazaar, लाख, करोड, कोटी, हजार, and their case forms
      such as लाखांत or हजारांचा) anywhere;
    - a number followed by a money unit or a hundred word ("45k", "paanch sau");
    - a number quoted per unit ("45 per watt", "45/W");
    - a cost word (price, charge, rate, budget, kimat, कीमत, दाम, किंमत, बजेट ...)
      within two words of a number that is not a power, size, length or time
      figure ("rate 40", "charges of 50"; not "price in 2 days");
    - with ``plain_numbers``: a number above 100 that is not a year or a unit
      figure ("packing 500", "1,999"), or a Marathi hundred ("पाचशे").
    """
    tokens = _tokens(text)
    if any(is_currency(token) or _money_word(token) for token in tokens):
        return True
    if plain_numbers and any(token in _COMPOUND_HUNDREDS for token in tokens):
        return True
    grouped = _grouped(text)
    for start, value, end, unit in _spans(tokens):
        if money_scale(unit) is not None or unit in HUNDRED_WORDS or _per_unit(tokens, end):
            return True
        if unit in _OTHER_UNITS:
            continue
        if _near_cost(tokens, start, end):
            return True
        if plain_numbers and value > PLAIN_PRICE_FLOOR and (value in grouped or not _year(value)):
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


def _currency_gap(gap: str) -> bool:
    """Only spaces, "." or ":" between a rupee sign or word and its number ("Rs.45", "Rs: 50")."""
    mark = gap.strip()
    return len(mark) <= 2 and set(mark) <= {".", ":"}


def _kinds(norms: list[str], gaps: list[str]) -> tuple[list[str], set[int]]:
    """num, unit, cur, part, join, article or other per token, and the numbers quoted
    per unit; ``gaps[i]`` precedes token i."""
    kinds: list[str] = []
    per_unit: set[int] = set()
    for index, token in enumerate(norms):
        following = norms[index + 1] if index + 1 < len(norms) else None
        previous = kinds[index - 1] if index else None
        spaced = gaps[index].strip() == ""
        if is_currency(token):
            kind = "cur"
        elif _money_word(token):
            kind = "unit"
        elif token in _SHORT_UNITS:
            tight = index > 0 and spaced and len(gaps[index]) <= 1
            kind = "unit" if tight and _is_digits(norms[index - 1]) else "other"
        elif token in HUNDRED_WORDS:
            kind = "unit" if previous == "num" and spaced else "other"
        elif _numberish(token):
            # "45/W", "45 per watt", "45 प्रति वाट": a per-unit price.
            slashed = following in _PER_UNITS and "/" in gaps[index + 1]
            per = (
                following in _PER_WORDS
                and index + 2 < len(norms)
                and norms[index + 2] in _PER_UNITS
            )
            if slashed or per:
                per_unit.add(index)
            # A rupee sign or word right before a number makes it money even before a
            # unit ("₹45/W", "Rs.45 W"); otherwise a number that owns a power, size,
            # length or time unit is not money ("5 kW", "2 days").
            priced = previous == "cur" and _currency_gap(gaps[index])
            mark = priced or index in per_unit or following not in _OTHER_UNITS
            kind = "num" if mark else "other"
        elif token in _PART_WORDS:
            kind = "part"
        elif token in _JOINERS:
            kind = "join"
        elif token in {"a", "an"}:
            kind = "article"
        else:
            kind = "other"
        kinds.append(kind)
    return kinds, per_unit


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
    hazaar", "दो लाख साठ हजार", "साडेतीन लाखांपर्यंत", "45k", "one and a half
    lakh"; "above a lakh" -> "above [amount]"); a currency word or sign with
    its number, even before a unit ("₹3.7L", "Rs. 3,70,000", "500 rupiya",
    "₹45/W" -> "[amount]/W"); a number quoted per unit ("45 per watt"); a
    number above 100 that is not a year or a unit figure ("1,999" is never a
    year); a decimal that is not a unit figure ("quoted 3.70"); a number next
    to a cost word ("packing charge 50", "बजेट 3"). Power, size, length and
    time figures ("5 kW", "1500 sq ft", "5 years", "2 days", "6 pm") and years
    stay.
    """
    found = list(_RAW_TOKEN.finditer(text))
    if not found:
        return text
    count = len(found)
    norms = [normalise(match.group()) for match in found]
    gaps = [""] + [text[found[index - 1].end() : found[index].start()] for index in range(1, count)]
    kinds, per_unit = _kinds(norms, gaps)
    parts_of_amount = {"num", "unit", "cur", "part", "join", "article"}
    spans: list[tuple[int, int]] = []

    def joined(left: int, right: int) -> bool:
        return gaps[right].strip() == "" or (kinds[left] == "cur" and _currency_gap(gaps[right]))

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
        comma = "," in found[index].group()
        big = norms[index] in _COMPOUND_HUNDREDS or (
            value is not None and value > PLAIN_PRICE_FLOOR and (comma or not _year(value))
        )
        decimal = value is not None and "." in norms[index]
        if big or decimal or index in per_unit or _near_cost(norms, index, index + 1):
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
