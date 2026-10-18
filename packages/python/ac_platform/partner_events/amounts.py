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
  ``mentioned_price`` ever passes one on; ``carries_money``: the stricter rule for
  the stated words of every other fact (round 4: any rupee, money or cost word, or
  a number above 100 that is not a unit figure, years included).
- ``gst_basis``: "incl_gst" / "ex_gst" only when GST was said with one clear
  cue, matched on whole words.

English, romanised Hindi and Marathi, Devanagari (Hindi and Marathi, with
their case endings: लाखांत, हजारांचा, कोटींचा) and Devanagari digits are read;
number words come from the closed 0-99 lists in ``number_words``. The event
summary does not use this reader: it masks every number (``summary_mask``).
Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from decimal import Decimal, InvalidOperation
from typing import Literal

from ac_platform.partner_events import number_words

Unit = Literal["kW", "kVA"]
Join = Literal["hard", "soft"]

_DEVANAGARI_DIGITS = {ord(chr(0x0966 + n)): str(n) for n in range(10)}
# A nasal half-letter before a stop is written either way (पन्द्रह / पंद्रह, किम्मत / किंमत).
_HALF_NASAL = re.compile(r"[ङञणनम]्(?=[क-म])")
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+|[ऀ-ॣॱ-ॿ]+|₹|/-|/|[-–~+]")
# Numbers written with digit-group commas ("1,999", "3,70,000"): never a year.
_GROUPED = re.compile(r"(?<![0-9.,])[0-9]{1,3}(?:,[0-9]{2,3})+(?![0-9])")


def clean_text(text: str) -> str:
    """Model text made safe to read and to send (round 4, check 4 robustness): lone
    surrogates, NUL and other control characters (tabs and line breaks stay) and format
    characters (zero-width spaces and joiners, soft hyphens, direction marks, BOM) are
    removed, then NFKC folds look-alike forms ("⁴⁵" -> "45", "④" -> "4", "４" -> "4")."""
    return strip_unsafe(unicodedata.normalize("NFKC", strip_unsafe(text)))


_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def strip_unsafe(text: str) -> str:
    """``text`` without lone surrogates, control characters (tabs and line breaks stay) or
    format characters; nothing else changes, so names and addresses keep their form."""
    return "".join(
        char
        for char in text
        if char in "\t\n\r" or unicodedata.category(char) not in _UNSAFE_CATEGORIES
    )


def normalise(text: str) -> str:
    """NFKC, case-folded, Devanagari digits as ASCII, nukta and chandrabindu folded, ऱ as
    र, zero-width joiners dropped, a nasal half-letter before a stop as anusvara,
    digit-group commas removed and whitespace collapsed."""
    value = unicodedata.normalize("NFKC", text).casefold().translate(_DEVANAGARI_DIGITS)
    value = value.replace("़", "").replace("ँ", "ं").replace("ऱ", "र")
    value = value.replace("\u200c", "").replace("\u200d", "")
    value = _HALF_NASAL.sub("ं", value)
    value = re.sub(r"(?<=\d),(?=\d)", "", value)
    value = re.sub(r"(?<=[a-z])\.(?=[a-z])", "", value)  # k.w. -> kw.
    return " ".join(value.split())


def folded(words: Iterable[str]) -> frozenset[str]:
    """``words`` as ``normalise`` writes them, so a lookup matches every spelling."""
    return frozenset(normalise(word) for word in words)


def _folded_values(*tables: dict[str, Decimal]) -> dict[str, Decimal]:
    """One table of folded spellings; a spelling with two values is a list error."""
    found: dict[str, Decimal] = {}
    for table in tables:
        for word, value in table.items():
            if found.setdefault(normalise(word), value) != value:
                raise ValueError(f"number word {word!r} has two values")
    return found


def _strong(table: dict[str, int]) -> dict[str, Decimal]:
    """The 0-99 words the reader reads: never zero, never an everyday word."""
    return {
        word: Decimal(value)
        for word, value in table.items()
        if value > 0 and word not in number_words.SOFT_WORDS
    }


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
# Round 3: the complete closed lists for 1-99 (pachpan, chhattis, पैंतालीस, पस्तीस ...).
# Everyday words ("saath", "bara", "tera" as romanised words) stay out.
_HI_NUMBER_WORDS = _folded_values(
    _HI_NUMBER_WORDS, _strong(number_words.HI_ROMAN), _strong(number_words.MR_ROMAN)
)
_DEVA_NUMBER_WORDS = _folded_values(
    _DEVA_NUMBER_WORDS, _strong(number_words.HI_DEVA), _strong(number_words.MR_DEVA)
)
NUMBER_WORDS: dict[str, Decimal] = _folded_values(
    _EN_NUMBER_WORDS, _HI_NUMBER_WORDS, _DEVA_NUMBER_WORDS
)
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
        "buck",  # round 4 (check 4, minor): "45 bucks a watt"
        "bucks",
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
        # Round 3 (check 3, item 2): rate, rate/every, price, cost, charge, fee.
        "रेट",
        "दर",
        "भाव",
        "खर्च",
        "खर्चा",
        "चार्ज",
        "शुल्क",
        "kharch",
        "kharcha",
        "bhav",
        "bhaav",
        "shulk",
        # Round 4 (check 4, B1 and the coordinator's decision): discount, EMI, quoted, fee.
        "discount",
        "discounts",
        "discounted",
        "rebate",
        "emi",
        "emis",
        "quoted",
        "fee",
        "fees",
        "amount",
        "installment",
        "installments",
        "instalment",
        "instalments",
        "kist",
        "kisht",
        "डिस्काउंट",
        "डिस्काऊंट",
        "सूट",
        "ईएमआई",
        "हप्ता",
        "हप्ते",
        "किस्त",
        "रक्कम",
        "रकम",
    }
)
# Things that are paid for (round 4): a number right after one is a price unless the thing
# it counts follows ("Transport 2000 extra", "packing 50"; not "delivery 3 panels",
# "installation 2 days"). Not cost words on their own: "transport included" is a delivery
# basis, not a price.
CHARGE_NOUNS = folded(
    {
        "transport",
        "transportation",
        "installation",
        "install",
        "installing",
        "packing",
        "packaging",
        "delivery",
        "labour",
        "labor",
        "freight",
        "fitting",
        "cartage",
        "shipping",
        "wiring",
        "bhada",
        "bhaada",
        "kiraya",
        "ट्रांसपोर्ट",
        "ट्रान्सपोर्ट",
        "इंस्टॉलेशन",
        "इन्स्टॉलेशन",
        "इंस्टालेशन",
        "पैकिंग",
        "पॅकिंग",
        "डिलीवरी",
        "डिलिव्हरी",
        "वाहतूक",
        "भाड़ा",
        "किराया",
        "मजुरी",
        "मजदूरी",
    }
)
_RANGE = {"to", "or", "se", "ya", "से", "ते", "या", "किंवा", "-", "–", "~"}
# Short words allowed between a cost word, a rupee word or a per-unit phrase and its number
# ("charges of 50", "50 ka charge", "price per watt is 45"), and hedges ("rate approx 45",
# "दर साधारण ४५"; check 3, item 5).
_CONNECTORS = frozenset(
    {
        "of",
        "is",
        "was",
        "are",
        "were",
        "be",
        "for",
        "at",
        "ka",
        "ki",
        "ke",
        "hai",
        "का",
        "की",
        "के",
        "है",
        "हैं",
        "था",
        "थी",
        "चा",
        "ची",
        "चे",
        "आहे",
        "होता",
        "होती",
        "होते",
        "approx",
        "approximately",
        "around",
        "about",
        "roughly",
        "nearly",
        "almost",
        "lagbhag",
        "karib",
        "kareeb",
        "लगभग",
        "करीब",
        "साधारण",
        "साधारणतः",
        "जवळपास",
        "अंदाजे",
        # Round 4 (check 4, B3 and M4): "rate is only 45", "दर फक्त ४५", "45 wala rate",
        # "rate - 45", "price ~45".
        "only",
        "just",
        "sirf",
        "bas",
        "keval",
        "फक्त",
        "सिर्फ",
        "बस",
        "केवल",
        "मात्र",
        "wala",
        "wale",
        "wali",
        "vala",
        "vale",
        "vali",
        "वाला",
        "वाले",
        "वाली",
        "-",
        "–",
        "~",
    }
)
# After these, a number followed by the thing it counts is a count ("price for 2 ACs").
_COUNTED_AFTER = frozenset({"of", "for", "at"})
# Words after a number that keep it a price after "of"/"for" ("charges of 50 only").
_PRICE_TAIL = frozenset({"only", "extra", "plus", "final", "fixed", "total", "hi", "ही"})
# Words after a number that make it a per-unit price ("45 per watt", "₹45/W", "₹45 प्रति वाट",
# "45 prati watt"); "a" too, right before a unit ("45 a watt").
_PER_WORDS = frozenset({"per", "प्रति", "prati", "/"})
_PER_ARTICLES = frozenset({"a", "an"})
# Round 4 (check 4, B2 and minor): words between a number and its per-unit phrase that
# leave it a per-unit price ("45 plus GST per watt", "45 + GST per watt", "45 ex-GST/W",
# "45 for each watt", "45 per peak watt").
_PER_SKIP = folded(
    {
        "+",
        "plus",
        "gst",
        "जीएसटी",
        "incl",
        "including",
        "inclusive",
        "excl",
        "excluding",
        "exclusive",
        "ex",
        "-",
        "with",
        "without",
        "अधिक",
        "सहित",
        "rs",
        "rupees",
        "rupaye",
        "रुपये",
        "for",
    }
)
_EVERY = folded({"each", "every", "har", "हर", "प्रत्येक", "pratyek", "एका", "ek", "एक"})
_PEAK = frozenset({"peak"})
# Things a price is quoted per that are not units of measure ("45 per panel"); never units
# that make a number something other than money ("150 panels" stays a count).
_PER_ONLY = frozenset({"panel", "panels", "piece", "pieces", "pc", "pcs", "nos", "plate", "plates"})
# Hindi and Marathi "per watt" with a case ending ("वॅटला ४५", "एका वॅटचे ४५", "वॉटमागे").
_DEVA_UNIT_STEM = "(?:वॅट|वाट|वॉट|युनिट|यूनिट)"
_DEVA_PER_ENDING = "(?:ला|चे|चा|ची|ना|मागे|साठी|ाला|ाचे|ाचा|ाची|ामागे)"
# Before a number, kilowatt forms too ("किलोवॅटला 60 हजार"); after one, only "per" endings
# and never a size ("45 वॅटला"; "5 किलोवॅटला" is "for 5 kW", "100 वॅटचे दिवे" are lamps).
_DEVA_PER_UNIT = re.compile(f"(?:किलो)?{_DEVA_UNIT_STEM}{_DEVA_PER_ENDING}")
_DEVA_PER_WATT = re.compile(f"{_DEVA_UNIT_STEM}(?:ला|मागे|ाला|ामागे)")
# Everyday romanised number words the reader leaves out, read as a number in the price
# check before a per-unit phrase or right after a cost word ("saath per watt is too much",
# "rate saath hai").
_SOFT_PRICE_WORDS = frozenset({"saath", "sath", "das", "dus", "bara", "tera", "sola"})
# A bare 1900-2100 is a year only with a year cue next to it ("installed in 2019", "on
# 18/10/2026", "सन 2020"); otherwise it is a plain number ("Transport 2000 extra").
_YEAR_BEFORE = folded(
    {
        "in",
        "since",
        "year",
        "years",
        "saal",
        "sal",
        "san",
        "from",
        "till",
        "until",
        "by",
        "before",
        "after",
        "circa",
        "fy",
        "सन",
        "साल",
        "साली",
        "वर्ष",
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
        "जनवरी",
        "जानेवारी",
        "फरवरी",
        "फेब्रुवारी",
        "मार्च",
        "अप्रैल",
        "एप्रिल",
        "मई",
        "मे",
        "जून",
        "जुलाई",
        "जुलै",
        "अगस्त",
        "ऑगस्ट",
        "सितंबर",
        "सप्टेंबर",
        "अक्टूबर",
        "ऑक्टोबर",
        "नवंबर",
        "नोव्हेंबर",
        "दिसंबर",
        "डिसेंबर",
    }
)
_YEAR_AFTER = folded({"साली", "साल", "सालात", "saali"})
_DATE_SIGNS = frozenset({"/", "-", "–"})
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
    "kwp": ("kW", 1),  # round 4 (check 4, minor): kWp is the usual solar size unit
    "kilowatt": ("kW", 1),
    "kilowatts": ("kW", 1),
    "किलोवाट": ("kW", 1),
    "किलोवॉट": ("kW", 1),  # Hindi spelling (check 3, item 1)
    "किलोवॅट": ("kW", 1),  # Marathi spelling
    "kva": ("kVA", 1),
    "w": ("kW", 1000),
    "watt": ("kW", 1000),
    "watts": ("kW", 1000),
    "वाट": ("kW", 1000),
    "वॉट": ("kW", 1000),
    "वॅट": ("kW", 1000),
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
    "यूनिट",  # round 4: "हर यूनिट 9", "प्रति युनिट 8"
    "युनिट",
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
# Hindi and Marathi time words with a case ending ("2 महिन्यांनी", "3 दिवसांत", "वाजेपर्यंत",
# "सालों"): a closed list of stems and endings.
_DEVA_TIME = re.compile(
    r"(?:दिवस|दिन|महिन|महीन|वर्ष|साल|आठवड|हफ्त|तास|घंट|मिनिट|मिनट|सेकंद|वाज|बज)"
    r"(?:ा|ां|े|ें|ों|्या|्यां|ी|ो)?"
    r"(?:चा|ची|चे|च्या|त|ने|नी|ला|ना|ता|पर्यंत|मध्ये|भर|ही|च|नंतर|पूर्वी|पासून)?"
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


def is_time_word(token: str | None) -> bool:
    """A time word or a Hindi/Marathi time word with its ending ("days", "बजे", "महिन्यांनी")."""
    return token is not None and (token in _TIME_UNITS or bool(_DEVA_TIME.fullmatch(token)))


def is_unit_word(token: str | None) -> bool:
    """A unit that makes the number before it something other than money (power, size,
    length, years, time: "kW", "sq", "saal", "days", "महिन्यांनी")."""
    return token is not None and (token in _OTHER_UNITS or bool(_DEVA_TIME.fullmatch(token)))


_other_unit = is_unit_word


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
        if _other_unit(following) or right in _EVERYDAY_WORDS:
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
            and not _other_unit(following)
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


def _year_cue(tokens: list[str], start: int, end: int) -> bool:
    """A year cue next to the number ``tokens[start:end]``: "in 2019", "सन 2020", "Oct
    2026", "18/10/2026", "2019 साली"."""
    before = tokens[start - 1] if start > 0 else None
    after = tokens[end] if end < len(tokens) else None
    if before in _YEAR_BEFORE or after in _YEAR_AFTER:
        return True
    return before in _DATE_SIGNS and start >= 2 and _is_digits(tokens[start - 2])


def _per_phrase_ends_at(tokens: list[str], index: int) -> bool:
    """``tokens[index]`` closes a per-unit phrase ("per watt", "प्रति वॅट", "/W", "har watt",
    "हर वॉट", "वॅटला", "एका वॅटचे")."""
    token = tokens[index]
    if _DEVA_PER_UNIT.fullmatch(token):
        return True
    if index < 1 or token not in _PER_UNITS | _PER_ONLY:
        return False
    previous = tokens[index - 1]
    if previous in _PEAK and index >= 2:
        previous = tokens[index - 2]
    return previous in _PER_WORDS or previous in _EVERY


def _near_cost(tokens: list[str], start: int, end: int) -> bool:
    """The number ``tokens[start:end]`` reads as money from the words around it.

    Before it, with at most two connecting words between: a cost word ("rate
    approx 45", "दर ४५", "price is around 45"), a rupee word or sign ("Rs:
    45"), or a per-unit phrase ("price per watt is 45", "per watt 45", "₹/W
    45"). After it, within two words with only a connector between: a cost
    word ("50 ka charge"). Not "price ... in 2 days" (no connector chain).

    After "of", "for" or "at", a number followed by the thing it counts is a
    count ("price for 2 ACs", "cost of 3 panels"), unless a price word follows
    it ("charges of 50 only").
    """
    after = tokens[end] if end < len(tokens) else None
    counted = after is not None and after[0].isalpha() and after not in _PRICE_TAIL
    for other in range(start - 1, max(start - 4, -1), -1):
        between = range(other + 1, start)
        if not all(tokens[step] in _CONNECTORS for step in between):
            break
        token = tokens[other]
        if token in COST_WORDS:
            if counted and any(tokens[step] in _COUNTED_AFTER for step in between):
                continue
            return True
        if token in CHARGE_NOUNS and not counted:  # "Transport 2000 extra", "packing 50"
            return True
        if is_currency(token) or _per_phrase_ends_at(tokens, other):
            return True
    for other in (end, end + 1):
        if other >= len(tokens) or tokens[other] not in COST_WORDS:
            continue
        if all(tokens[step] in _CONNECTORS for step in range(end, other)):
            return True
    return False


def _per_unit(tokens: list[str], end: int) -> bool:
    """The number ending before ``end`` is quoted per unit ("45 per watt", "45/W",
    "45 प्रति वॅट", "45 a watt", "45 plus GST per watt", "45 for each watt", "45 per peak
    watt", "45 per panel", "45 वॅटला")."""
    index = end
    while index < len(tokens) and tokens[index] in _PER_SKIP:
        index += 1
    if index < len(tokens) and _DEVA_PER_WATT.fullmatch(tokens[index]):
        return True
    if index + 1 >= len(tokens):
        return False
    per = tokens[index]
    if not (per in _PER_WORDS or per in _PER_ARTICLES or per in _EVERY):
        return False
    unit = index + 1
    if tokens[unit] in _PEAK and unit + 1 < len(tokens):
        unit += 1
    return tokens[unit] in _PER_UNITS or tokens[unit] in _PER_ONLY


def _soft_price(tokens: list[str]) -> bool:
    """An everyday number word quoted per unit or right after a cost word ("saath per
    watt", "saath rupaye", "rate saath hai")."""
    for index, token in enumerate(tokens):
        if token not in _SOFT_PRICE_WORDS:
            continue
        if _per_unit(tokens, index + 1):
            return True
        if index > 0 and tokens[index - 1] in COST_WORDS:
            return True
    return False


def carries_money(text: str) -> bool:
    """True when the words of a fact that is not a price must be dropped (round 4, the
    coordinator's decision): a rupee word or sign, a money word, a cost word anywhere
    ("packing charge", "EMI option"), any price ``mentions_price`` finds, or a number above
    100 that is not a unit figure, years included ("dongle 1999", "Transport 2000 extra",
    "150 panels"; "1500 sq ft" and "150Ah" stay)."""
    tokens = _tokens(text)
    if any(token in COST_WORDS or token in HUNDRED_WORDS for token in tokens):
        return True
    return mentions_price(text, plain_numbers=True, years=False)


def mentions_price(text: str, *, plain_numbers: bool = True, years: bool = True) -> bool:
    """True when words carry a price.

    - a currency word or sign (a known rupee spelling) or a money word (lakh,
      crore, thousand, hazaar, लाख, करोड, कोटी, हजार, and their case forms
      such as लाखांत or हजारांचा) anywhere;
    - a number followed by a money unit or a hundred word ("45k", "paanch sau");
    - a number quoted per unit ("45 per watt", "45/W", "45 प्रति वॅट");
    - a cost word (price, charge, rate, budget, kimat, कीमत, दाम, किंमत, बजेट,
      रेट, दर, भाव, खर्च, चार्ज, शुल्क ...), a rupee word or a per-unit phrase
      just before a number that is not a power, size, length or time figure,
      or a cost word just after it ("rate approx 45", "price per watt is 45",
      "charges of 50"; not "price in 2 days");
    - with ``plain_numbers``: a number above 100 that is not a year or a unit
      figure ("packing 500", "1,999"), or a Marathi hundred ("पाचशे"). A bare
      1900-2100 is a year only with a year cue next to it ("installed in 2019",
      "18/10/2026", "सन 2020"; not "Transport 2000 extra" or "EMI 2000"), and
      never with ``years=False``;
    - an everyday number word quoted per unit or right after a cost word ("saath
      per watt", "rate saath hai").
    """
    tokens = _tokens(text)
    if any(is_currency(token) or _money_word(token) for token in tokens):
        return True
    if plain_numbers and any(token in _COMPOUND_HUNDREDS for token in tokens):
        return True
    if _soft_price(tokens):
        return True
    grouped = _grouped(text)
    for start, value, end, unit in _spans(tokens):
        if money_scale(unit) is not None or unit in HUNDRED_WORDS or _per_unit(tokens, end):
            return True
        if _other_unit(unit):
            continue
        if _near_cost(tokens, start, end):
            return True
        if not plain_numbers or value <= PLAIN_PRICE_FLOOR:
            continue
        year = years and value not in grouped and _year(value) and _year_cue(tokens, start, end)
        if not year:
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
