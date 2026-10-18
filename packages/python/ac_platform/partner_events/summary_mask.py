"""Every number in the event summary reads "[n]" (round 3 decision, 18 Oct 2026).

The summary is free text written by the report model, so no amount reader can
be trusted to find every price in it. Instead every number goes:

- every digit run, with its separators and whatever is written onto it
  ("₹45/W", "3,70,000", "3.70", "२३", "10:30", "18/10/2026", "5kW", "45/-",
  "Rs.45"), in any script's digits;
- every number word, from the closed lists in ``number_words``: 0-99,
  hundreds, thousands, lakh, crore and fractions in English, romanised Hindi
  and Marathi, and Devanagari Hindi and Marathi, with Marathi case endings
  ("पाचला", "तीनच", "दोनशे", "साडेतीनशे"), Hindi plurals ("तीनों", "हजारों") and
  money words with their endings ("लाखांपर्यंत", "कोटींचा");
- number words, money words and rupee words said together read as one "[n]"
  ("teen lakh sattar hazaar rupaye", "one and a half lakh", "twenty-five",
  "दो लाख साठ हजार", "Rs 45").

Dates and times go too ("[n] Oct", "[n] pm"); ``next_step.when_text`` keeps
the words as said. Units, names and other words stay ("[n] kW", "Kothrud").

Whole words only, with Devanagari-aware boundaries: "often", "someone",
"Lakhan", "हजारीबाग", "सातारा", "बारामती", "एकदम" and "साठी" stay. Number words
that are also everyday words (``number_words.SOFT_WORDS``) are masked only
where they read as a number: "do", "दो", "saath", "आधी" next to another number
word, a money word or a rupee word ("do lakh", "सवा दो लाख"), and "one" on its
own unless it is a pronoun ("no one", "the one", "this one"). "do" is the verb
after can, will, we ... or before you, the, it ... ("we can do [n] kW").

Round 4 (check 4): an everyday word next to a rupee word or sign ("saath
rupay", "₹ saath"), right after a cost word ("rate saath hai") or before a
range word and a number word ("do se teen lakh", "do-do hazaar") is a number;
any word directly before a rupee or money word is read as a number unless it is
an ordinary word from a closed list ("pantalis rupaye"; "in rupees", "spent
lakhs" stay); "Sau." / "सौ." before a name stays. The same mask runs on promise
and objection text, and on ``next_step.when_text`` when money is said near its
number. Callers pass model text through ``amounts.clean_text`` first.

Round 5 (check 5 and the coordinator's decision): more spellings (चौपन्न, एकसष्ठ,
satalis, ikkavan, nintey; laks, hazzar, lakhat, hajarachi; Marathi hundreds in one word with
any ending, "अडीचशेला", "didshe"); a word shaped like a number word right after a cost word
(hedges allowed: "rate lagbhag saath") or right before a per-unit phrase, and an everyday
word before a per-unit phrase or before "wala" and a cost word, is a number; "ek baar"
(once) stays. The same reading serves two more rules:

- ``mask_when``: ``next_step.when_text`` shows every number as "[n]" except strict date and
  time forms (hh:mm, dd/mm[/yyyy], a day or hour of 31 or less next to a clock or date word).
- ``fact_carries_money``: the stated words of a fact that is not a price keep only numbers
  explained by a unit, a counted noun, a warranty year word or a model name.

Round 6 (check 6 and the coordinator's decision D1-D5):

- D1: in a product mention a number is a model number only when written onto letters in one
  token ("PuREPower5", "MC4", "Solis 5G") or joined by a hyphen ("PuREPower-5"); a
  free-standing number ("Tata 42", "PuREPower 5") or any number word ("Adani forty") drops
  the fact. Units still explain ("Waaree 545 Wp").
- D2: watts are a size only from 100 up ("45 watt padega", "47 watt" drop); a rate verb
  (padega, lagenge, detat, पडेल, लगेगा ...) with any number drops a fact that is not a price.
- D3: ``mask_when`` keeps only hh:mm, h or h.mm before a clock word, a day before a month or
  tarikh, the year of "<day> <month> <year>" and dd/mm[/yyyy]; everything else is "[n]".
- D4: spoken Marathi endings (चं, नं, ना ...) on number, hundred and money words.

Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ac_platform.partner_events import number_words as words
from ac_platform.partner_events.amounts import (
    CHARGE_NOUNS,
    COST_WORDS,
    FRACTION_WORDS,
    HUNDRED_WORDS,
    MONEY_UNITS,
    NUMBER_WORDS,
    clean_text,
    folded,
    hundreds_word,
    is_currency,
    is_time_word,
    is_unit_word,
    money_scale,
    money_word_said,
    normalise,
    read_number,
    soft_price,
    tokens_of,
)

MASK = "[n]"

_DIGIT = "[\\d¼-¾⅐-⅞]"  # any script's digits, and ½ ¼ ¾ ⅓ ...
_DEVA = "ऀ-ॣॱ-ॿ\u200c\u200d"  # letters and signs, not digits or danda
_LATIN = "A-Za-zÀ-ÖØ-öø-ɏ"
_TOKEN = re.compile(
    # A digit run with its separators and what is written onto it: a rupee sign or word
    # before ("₹45", "Rs.45"), a unit or sign after ("45/W", "5kW", "45/-", "18%", "3rd").
    rf"(?P<num>(?:[₹₨$]|(?<![{_LATIN}])(?i:rs|inr)[.:]?)?"
    rf"{_DIGIT}(?:[.,:/\-–]?{_DIGIT})*"
    rf"(?:/-|/?[{_LATIN}{_DEVA}%]+(?:/[{_LATIN}]+)?)?)"
    rf"|(?P<deva>[{_DEVA}]+)"
    rf"|(?P<latin>[{_LATIN}]+(?:['’][{_LATIN}]+)*)"
    r"|(?P<sign>[₹₨$]|/-)"
)
# Between two parts of one number: spaces (zero-width ones too) or one hyphen ("twenty-five").
_TIGHT = re.compile(r"[\s\u200b\u200c\u200d\ufeff]*|[-–]")
# Between a rupee word and its number: also "." or ":" ("Rs. 45", "Rs: 50", "रु. ५००").
_CURRENCY_GAP = re.compile(r"[\s\u200b\ufeff]*[.:]?[\s\u200b\ufeff]*")
_SENTENCE_END = re.compile(r"[।॥.!?]")


def _all(*groups: Iterable[str]) -> frozenset[str]:
    found: set[str] = set()
    for group in groups:
        found |= folded(group)
    return frozenset(found)


_SOFT = folded(words.SOFT_WORDS)
_ALL_0_99_WORDS = (
    set(words.EN_ONES)
    | set(words.EN_TENS)
    | set(words.HI_ROMAN)
    | set(words.MR_ROMAN)
    | set(words.HI_DEVA)
    | set(words.MR_DEVA)
)
_TENS = folded(words.EN_TENS)
_AFTER_TENS = folded(words.EN_ORDINALS_AFTER_TENS)
_SHORT = folded(words.SHORT_UNITS)
_FRACTIONS = _all(words.FRACTION_PREFIXES, words.FRACTION_VALUES, FRACTION_WORDS)
# Words that are a number wherever they stand (whole words only).
_NUMBER = (
    (
        _all(
            words.EN_ONES,
            words.EN_TENS,
            words.EN_DECADES,
            words.EN_ORDINALS,
            words.HI_ROMAN,
            words.MR_ROMAN,
            words.HI_DEVA,
            words.MR_DEVA,
            words.BIG_WORDS,
            NUMBER_WORDS,
            HUNDRED_WORDS,
            MONEY_UNITS,
        )
        | _FRACTIONS
    )
    - _SOFT
    - _SHORT
)
# Words an article belongs to ("a lakh", "a half", "a hundred", "an hundred", "a dozen").
_TAKES_ARTICLE = (
    _all(words.BIG_WORDS, HUNDRED_WORDS, MONEY_UNITS, words.FRACTION_VALUES) - _SHORT - _SOFT
)
# Two number words written as one ("fortyfive", "teenlakh", "dolakh", "पाचहजार", "दोलाख"):
# a 0-99 or fraction word, then a money or hundred word; or a tens word, then a ones word.
_HEADS = _all(_ALL_0_99_WORDS) | _FRACTIONS
_MONEY_TAILS = _all(words.BIG_WORDS, HUNDRED_WORDS, MONEY_UNITS) - _SHORT
_ONES = folded(word for word, value in words.EN_ONES.items() if 1 <= value <= 9)
_LONGEST_COMPOUND = 2 * max(len(word) for word in _HEADS | _MONEY_TAILS)
_POINT = frozenset({"point", "dot"})
_JOINERS = folded({"and", "aur", "और", "आणि", "ani"}) | _POINT
_ARTICLES = frozenset({"a", "an"})

# Devanagari stems that take Marathi case endings ("पाचला", "तीनच", "दोनशे"); Hindi-only
# words take the plural only ("तीनों", "दसों").
_MR_STEMS = folded(words.MR_DEVA) - _SOFT
_HI_STEMS = folded(words.HI_DEVA) - _SOFT - _MR_STEMS
_MR_SUFFIXES = (
    "चा",
    "ची",
    "चे",
    "च्या",
    "त",
    "ला",
    "पर्यंत",
    "मध्ये",
    "वर",
    "नी",
    "ने",
    "हून",
    "पेक्षा",
    "शी",
    "साठी",
    "च",
    "ही",
    "भर",
    "शे",
    "नंतर",
    "पासून",
    # Round 6 (D4): spoken Marathi endings ("पाचचं", "दहानं", "पन्नासना"; "ाचं", "ांचं" with
    # the vowels below).
    "चं",
    "नं",
    "ना",
)
# "ा" and "ां" only before a case ending, so "साठा" (stock) and "चारा" (fodder) stay.
_MR_ENDINGS = tuple(
    sorted({vowel + suffix for vowel in ("", "ा", "ां") for suffix in _MR_SUFFIXES}, key=len)[::-1]
)
_DEVA_FRACTION_PREFIXES = frozenset(word for word in _FRACTIONS if word[0] >= "ऀ")
# After a fraction written onto it, every 0-99 word is a number ("साडेदो", "सवानव").
_DEVA_0_99 = folded(words.HI_DEVA) | folded(words.MR_DEVA)
_HUNDRED_SUFFIX = "शे"
_PLURAL = "ों"
_EXTRA_DEVA = folded({"दोनों"})

# "one" as a pronoun: "no one", "the one", "this one", "a new one".
_BEFORE_PRONOUN_ONE = frozenset(
    {
        "no",
        "the",
        "this",
        "that",
        "which",
        "each",
        "every",
        "any",
        "some",
        "other",
        "same",
        "new",
        "old",
        "big",
        "small",
        "bigger",
        "smaller",
        "cheaper",
        "better",
        "right",
        "wrong",
        "last",
        "next",
        "first",
        "little",
        "good",
        "bad",
        "best",
    }
)
# "do" as the English verb: after a modal or pronoun, or before a pronoun or article.
_BEFORE_VERB_DO = frozenset(
    {
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "must",
        "may",
        "might",
        "to",
        "we",
        "i",
        "you",
        "they",
        "he",
        "she",
        "it",
        "lets",
        "let's",
        "please",
        "pls",
        "kindly",
        "i'll",
        "we'll",
        "you'll",
        "they'll",
        "he'll",
        "she'll",
        "i'd",
        "we'd",
        "you'd",
        "they'd",
        "don't",
        "didn't",
        "doesn't",
        "not",
        "also",
    }
)
_AFTER_VERB_DO = frozenset(
    {
        "you",
        "u",
        "we",
        "i",
        "they",
        "it",
        "not",
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "your",
        "so",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "our",
        "their",
        "his",
        "its",
        "something",
        "anything",
        "nothing",
        "everything",
        "what",
        "whatever",
        "well",
        "better",
        "more",
        "less",
        "all",
        "any",
        "some",
    }
)
# Hindi "दो" as the verb "give": after a verb stem ("भेज दो", "बता दो", "कर दो").
_BEFORE_VERB_DEVA_DO = folded(
    {
        "कर",
        "दे",
        "ले",
        "भेज",
        "बता",
        "रख",
        "बोल",
        "समझा",
        "समझ",
        "दिखा",
        "दिखला",
        "लगा",
        "बना",
        "सुना",
        "चला",
        "छोड़",
        "डाल",
        "भिजवा",
        "करवा",
        "लगवा",
        "बनवा",
        "दिलवा",
        "लिख",
        "दिला",
        "मंगा",
        "मंगवा",
        "बुला",
        "उठा",
        "बदल",
        "जोड़",
        "निकाल",
        "सुधार",
        "पढ़",
        "लौटा",
        "बतला",
        "पहुंचा",
        "भर",
        "खोल",
        "रोक",
        "चुका",
        "जमा",
        "मुझे",
        "हमें",
        "उन्हें",
        "उसे",
    }
)


_COST = folded(COST_WORDS)
# Between a cost word and an everyday number word ("rate sirf saath").
_ONLY = folded({"only", "just", "sirf", "bas", "is", "hai", "फक्त", "सिर्फ", "बस", "है", "आहे"})
# Range words: "do se teen lakh", "saath ya sattar hazaar", "दो या तीन लाख".
_RANGE_WORDS = folded({"se", "ya", "or", "to", "से", "या", "ते", "किंवा", "va", "व"})
# The honorific "Sau." / "सौ." before a name (Marathi "Mrs").
_HONORIFICS = folded({"sau", "सौ"})
_HONORIFIC_GAP = re.compile(r"\.[\s​﻿]*")
# Ordinary words that may stand directly before a rupee or money word; any other word
# there is read as a number we have no spelling for ("pantalis rupaye", round 4 fallback).
# fmt: off
_ORDINARY_BEFORE_MONEY = (
    folded(
        {
            # English
            "n", "a", "an", "the", "of", "in", "on", "at", "by", "for", "from", "to", "into",
            "with", "without", "and", "or", "but", "than", "then", "per", "only", "just",
            "about", "around", "approx", "approximately", "nearly", "almost", "roughly",
            "over", "under", "above", "below", "upto", "up", "within", "more", "less", "extra",
            "additional", "total", "few", "many", "several", "some", "any", "all", "lots",
            "lot", "much", "is", "was", "are", "were", "be", "been", "being", "will", "would",
            "can", "could", "should", "must", "may", "might", "pay", "paid", "pays", "paying",
            "spend", "spent", "spends", "spending", "save", "saved", "saves", "saving",
            "savings", "earn", "earned", "earns", "worth", "charged", "offered", "offer",
            "asked", "said", "says", "told", "gave", "give", "gives", "given", "get", "got",
            "gets", "take", "took", "takes", "taken", "need", "needs", "needed", "want",
            "wants", "wanted", "invest", "invested", "investment", "lose", "lost", "waste",
            "wasted", "his", "her", "their", "our", "my", "your", "its", "these", "those",
            "this", "that", "what", "which", "how", "no", "not", "never", "also", "even",
            "still", "too", "so", "very", "each", "every", "plus", "minus", "indian",
            # romanised Hindi and Marathi
            "ka", "ki", "ke", "ko", "se", "me", "mein", "main", "par", "pe", "tak", "hi", "bhi",
            "aur", "ya", "sirf", "bas", "kuch", "kitne", "kitna", "kitni", "kai", "lagbhag",
            "karib", "kareeb", "hai", "hain", "tha", "thi", "ho", "de", "dena", "denge",
            "diya", "liya", "lagega", "lagenge", "milega", "kam", "zyada", "jyada", "jada",
            "upar", "niche", "andar", "bahut", "sab", "saare", "wala", "wale", "vala", "apne",
            "mere", "hamare", "unke", "kul", "alag", "ani", "kiti", "fakt", "aahe", "ahe",
            # Devanagari Hindi
            "का", "की", "के", "को", "से", "में", "पर", "पे", "तक", "ही", "भी", "और", "या",
            "सिर्फ", "बस", "कुछ", "कितने", "कितना", "कितनी", "कई", "लगभग", "करीब", "है",
            "हैं", "था", "थी", "थे", "हो", "दे", "देंगे", "दिया", "दिए", "लिया", "लिए", "लगेगा",
            "लगेंगे", "मिलेगा", "कम", "ज़्यादा", "ज्यादा", "ऊपर", "नीचे", "अंदर", "बहुत", "सब",
            "वाला", "वाले", "कुल", "अलग", "अतिरिक्त",
            # Devanagari Marathi
            "चा", "ची", "चे", "च्या", "ला", "ने", "नी", "त", "मध्ये", "वर", "पर्यंत", "फक्त",
            "काही", "किती", "कित्येक", "अनेक", "साधारण", "जवळपास", "अंदाजे", "आहे", "आहेत",
            "होता", "होती", "होते", "द्या", "देऊ", "देईल", "दिले", "घेतले", "लागेल", "लागतील",
            "मिळेल", "जास्त", "कमी", "खाली", "एकूण", "वेगळे", "अधिक", "आणि", "किंवा", "सुद्धा",
            "पण", "तर", "हे", "ते", "तो", "त्या", "शिवाय", "सह", "म्हणजे",
            # Verbs of saying, giving and needing, and the customer
            "म्हणाला", "म्हणाले", "म्हणाली", "सांगितले", "सांगितला", "बोलला", "बोलले",
            "बोलली", "बोला", "बोले", "बोली", "कहा", "कहे", "कही", "बताया", "बताए", "बताई",
            "चाहिए", "हवे", "हवेत", "पाहिजे", "पाहिजेत", "लागले", "लगे", "दिलेत",
            "ग्राहक", "ग्राहकाने", "ग्राहकाचे", "ग्राहकाला", "ग्राहकने", "customer", "client",
            "bola", "bole", "boli", "kaha", "bataya", "chahiye", "pahije", "have", "has", "had",
            "quote", "quotes", "budget",
        }
    )
    | _COST
    | CHARGE_NOUNS
)
# fmt: on


def _deva_number(token: str) -> bool:
    """A Devanagari number word, with a Marathi case ending, a Hindi plural, a joined
    fraction ("साडेतीन", "सव्वादोन", "पावणेतीनशे") or a money word's ending."""
    if token in _NUMBER or token in _EXTRA_DEVA or money_scale(token) is not None:
        return True
    if _stem_with_ending(token) or hundreds_word(token):  # "पंधराशे", "अडीचशेला" (round 5)
        return True
    for prefix in _DEVA_FRACTION_PREFIXES:
        rest = token[len(prefix) :]
        if not token.startswith(prefix) or not rest:
            continue
        if rest == _HUNDRED_SUFFIX or rest in _NUMBER or rest in _DEVA_0_99:
            return True
        if _stem_with_ending(rest) or money_scale(rest) is not None:
            return True
    return False


def _compound(token: str) -> bool:
    """Two number words written as one word ("fortyfive", "teenlakh", "पाचहजार")."""
    if len(token) > _LONGEST_COMPOUND:
        return False
    for cut in range(2, len(token) - 1):
        head, tail = token[:cut], token[cut:]
        if head in _HEADS and (tail in _MONEY_TAILS or money_scale(tail) is not None):
            return True
        if head in _TENS and tail in _ONES:
            return True
    return False


def _stem_with_ending(token: str) -> bool:
    if token in _MR_STEMS or token in _HI_STEMS:
        return True
    if token.endswith(_PLURAL) and token[: -len(_PLURAL)] in (_MR_STEMS | _HI_STEMS):
        return True
    return any(
        token.endswith(ending) and token[: -len(ending)] in _MR_STEMS for ending in _MR_ENDINGS
    )


def _kind(group: str | None, norm: str) -> str:
    """num, number, after_tens, short, one, do, deva_do, soft, cur, join, article or other."""
    if group == "num":
        return "num"
    if group == "sign" or is_currency(norm):
        return "cur"
    if group == "latin" and norm.endswith("'s") and _kind(group, norm[:-2]) == "number":
        return "number"  # "lakh's", "forty's"
    if group == "latin" and norm.endswith("ish") and norm[:-3] in _NUMBER:
        return "number"  # "fortyish" (round 6, check 6 M7)
    if norm in _SOFT:
        if norm == "one":
            return "one"
        if norm == "do":
            return "do"
        return "deva_do" if norm == "दो" else "soft"
    if group == "deva":
        return "number" if _deva_number(norm) or _compound(norm) else "other"
    if norm in _NUMBER or _compound(norm) or hundreds_word(norm):
        return "number"
    if money_scale(norm) is not None and norm not in _SHORT:  # "lakhat", "hajarachi"
        return "number"
    if norm in _AFTER_TENS:
        return "after_tens"
    if norm in _SHORT:
        return "short"
    if norm in _JOINERS:
        return "join"
    if norm in _ARTICLES:
        return "article"
    return "other"


# --- Round 5 (check 5 and the coordinator's decision) ------------------------------------------

# Hedges allowed between a cost word and the number after it ("rate lagbhag saath").
_HEDGES = folded(
    {
        "lagbhag",
        "around",
        "approx",
        "approximately",
        "about",
        "karib",
        "kareeb",
        "nearly",
        "almost",
        "roughly",
        "लगभग",
        "करीब",
        "जवळपास",
        "अंदाजे",
        "साधारण",
    }
)
_AFTER_COST_GAP = _ONLY | _HEDGES
# Round 6 (D2): rate verbs. With any number they drop a fact that is not a price ("45 watt
# padega", "Tatawale pannas detat"); "hisaab" (rate basis, check 6 M2) too.
_RATE_VERBS = folded(
    {
        "padega",
        "padta",
        "lagega",
        "lagenge",
        "lagta",
        "milega",
        "milta",
        "chalega",
        "detat",
        "deta",
        "denge",
        "पडेल",
        "पडतात",
        "पडतील",
        "लागेल",
        "लागतील",
        "मिळेल",
        "देतात",
        "देऊ",
        "लगेगा",
        "लगेंगे",
        "मिलेगा",
        "पड़ेगा",
        "hisaab",
        "hisab",
        "हिसाब",
    }
)
# Round 6 (check 6, M1 structurally): a word shaped like a number word right before a rate
# verb or a verb of quoting, directly or after one connector, is a number we have no spelling
# for ("Tata ne bayaalees bola", "टाटावाले बेचाळिस देतात", "pachavanna tak chalega").
_QUOTE_VERBS = _RATE_VERBS | folded(
    {
        "bola",
        "bole",
        "boli",
        "bataya",
        "kaha",
        "बोला",
        "बोले",
        "बोली",
        "बताया",
        "कहा",
        "बोलला",
        "बोलले",
        "सांगितले",
        "सांगितला",
        "म्हणाले",
        "म्हणाला",
        "चलेगा",
        "चालेल",
    }
)
_QUOTE_GAP = folded({"tak", "तक", "me", "mein", "में", "pe", "पे", "पर्यंत", "ला", "मध्ये"})
# "ek baar" / "एक बार" is "once", not a number.
_ONCE = folded({"ek", "एक"})
_TIMES = folded({"baar", "bar", "बार", "dafa", "दफा", "वेळा", "वेळ"})
# A per-unit phrase: one of these, then a unit ("per watt", "a watt", "har unit", "प्रति वॅट").
_PER_START = folded(
    {"per", "prati", "प्रति", "a", "an", "har", "हर", "each", "every", "एका", "pratyek", "प्रत्येक"}
)
_PER_UNIT_NAMES = folded(
    {
        "watt",
        "watts",
        "w",
        "wp",
        "kw",
        "kwp",
        "kwh",
        "unit",
        "units",
        "panel",
        "panels",
        "वॅट",
        "वाट",
        "वॉट",
        "युनिट",
        "यूनिट",
        "किलोवॅट",
        "किलोवाट",
        "किलोवॉट",
    }
)
# "वॅटला", "वॉटचे", "युनिटमागे": a per-unit phrase in one word.
_DEVA_PER_FORM = re.compile(
    r"(?:किलो)?(?:वॅट|वाट|वॉट|युनिट|यूनिट)(?:ला|चे|चा|ची|ना|मागे|साठी|ाला|ाचे|ाचा|ाची|ामागे)"
)
_WALA = folded({"wala", "wale", "wali", "vala", "vale", "vali", "वाला", "वाले", "वाली"})
# The shape of a number word we have no spelling for ("satalis", "एक्क्याण्णव"): read as a
# number only right after a cost word or right before a per-unit phrase (round 5 fallback).
# Matched on normalised words, where a nasal half-letter reads as anusvara (न्न as ंन).
_NUMBER_SHAPED = re.compile(
    r"[a-z]{2,}(?:alis|alees|anve|anbe|nnav|asi|aasi|sath|saath|sasht|sashta|shath|attar"
    r"|avan|awan|anna|ees|tis|tees|inshi|nshi|aas|chas|ann|pun|uvan)"
    r"|[ऀ-ॿ]{2,}(?:ीस|ईस|इस|िस|न्न|ंन|वन|पन|सष्ट|सष्ठ|सठ|त्तर|ऐंशी|यंशी|ासी|ण्णव|ंणव|णव|नवे|नबे"
    r"|ंबे|चास|छठ|ाश)"  # round 6 (check 6, M1): unanchaas, pachpun, उनन्चास, छाछठ, पन्नाश
)


@dataclass(frozen=True)
class _Scan:
    """The mask's reading of a text: its tokens, their kinds and which ones are numbers."""

    text: str
    found: list[re.Match[str]]
    norms: list[str]
    kinds: list[str]
    gaps: list[str]
    masked: list[bool]

    @property
    def count(self) -> int:
        return len(self.found)

    def tight(self, index: int) -> bool:
        """Token ``index`` follows token ``index - 1`` as part of one number."""
        return 0 < index < self.count and _TIGHT.fullmatch(self.gaps[index]) is not None

    def norm_at(self, index: int) -> str | None:
        return self.norms[index] if 0 <= index < self.count else None


def _scan(text: str) -> _Scan:
    found = list(_TOKEN.finditer(text))
    norms = [normalise(match.group()).replace("’", "'") for match in found]
    kinds = [_kind(match.lastgroup, norm) for match, norm in zip(found, norms, strict=True)]
    gaps = [""] + [
        text[found[index - 1].end() : found[index].start()] for index in range(1, len(found))
    ]
    scan = _Scan(text, found, norms, kinds, gaps, [kind in {"num", "number"} for kind in kinds])
    if found:
        _read(scan)
    return scan


def _read(scan: _Scan) -> None:
    """Decide which everyday words, articles, joiners and rupee words belong to a number."""
    count, norms, kinds, gaps, masked = scan.count, scan.norms, scan.kinds, scan.gaps, scan.masked
    tight, norm_at = scan.tight, scan.norm_at

    def kind_before(index: int) -> str | None:
        return kinds[index - 1] if tight(index) else None

    def kind_after(index: int) -> str | None:
        return kinds[index + 1] if tight(index + 1) else None

    def word_beside(index: int, test: Callable[[int], bool]) -> bool:
        return (tight(index) and test(index - 1)) or (tight(index + 1) and test(index + 1))

    def word_number(index: int) -> bool:
        """Token ``index`` is a number word already masked (not digits)."""
        return 0 <= index < count and masked[index] and kinds[index] != "num"

    def after_cost(index: int) -> bool:
        """Token ``index`` follows a cost word, directly or after "only" or a hedge ("rate
        saath", "rate sirf saath", "rate lagbhag saath"; round 5 adds the hedges)."""
        step = index
        for _ in range(3):
            if not tight(step):
                return False
            previous = norm_at(step - 1)
            if previous in _COST:
                return True
            if previous not in _AFTER_COST_GAP:
                return False
            step -= 1
        return False

    def before_per(index: int) -> bool:
        """A per-unit phrase follows token ``index`` ("saath per watt", "das per unit",
        "X प्रति वॅट", "X वॅटला"; round 5)."""
        following = index + 1
        if not tight(following):
            return False
        if _DEVA_PER_FORM.fullmatch(norms[following]):
            return True
        return (
            norms[following] in _PER_START
            and tight(following + 1)
            and norm_at(following + 1) in _PER_UNIT_NAMES
        )

    def before_wala_cost(index: int) -> bool:
        """ "wala" and a cost word follow token ``index`` ("saath wala rate"; round 5)."""
        return (
            tight(index + 1)
            and norms[index + 1] in _WALA
            and tight(index + 2)
            and norm_at(index + 2) in _COST
        )

    def before_quote_verb(index: int) -> bool:
        """A rate verb or a verb of quoting follows token ``index``, directly or after one
        connector ("bayaalees bola", "pachavanna tak chalega"; round 6)."""
        following = index + 1
        if tight(following) and norms[following] in _QUOTE_GAP:
            following += 1
        return tight(following) and norms[following] in _QUOTE_VERBS

    def honorific(index: int) -> bool:
        """The honorific "Sau." or "सौ." before a name, with no number, rupee or cost word
        before it."""
        if index + 1 >= count or kinds[index + 1] != "other":
            return False
        if _HONORIFIC_GAP.fullmatch(gaps[index + 1]) is None:
            return False
        if money_scale(norms[index + 1]) is not None or norms[index + 1] in _COST:
            return False
        return not (
            tight(index)
            and (
                kinds[index - 1] in {"num", "number", "soft", "do", "deva_do", "one", "cur"}
                or norms[index - 1] in _COST
            )
        )

    for index, kind in enumerate(kinds):
        if kind == "after_tens":  # "twenty first"
            masked[index] = tight(index) and norms[index - 1] in _TENS
        elif kind == "short":  # "45 k", "2.5 L", "forty k", "teen lack"
            masked[index] = kind_before(index) in {"num", "number"} and len(gaps[index]) <= 1
        elif kind == "one":
            pronoun = norm_at(index - 1) in _BEFORE_PRONOUN_ONE and kind_after(index) not in {
                "num",
                "number",
                "cur",
                "short",
                "join",
                "article",
            }
            masked[index] = not (pronoun or norm_at(index + 1) == "another")
        elif kind == "do":
            verb = norm_at(index - 1) in _BEFORE_VERB_DO or norm_at(index + 1) in _AFTER_VERB_DO
            right = kind_after(index) in {"number", "cur"} or (
                tight(index + 1) and is_unit_word(norms[index + 1])  # "do din", "do saal"
            )
            left = tight(index) and (
                norms[index - 1] in _FRACTIONS
                or (kinds[index - 1] == "number" and money_scale(norms[index - 1]) is None)
            )
            masked[index] = not verb and (right or left)
        elif kind == "deva_do":
            verb = norm_at(index - 1) in _BEFORE_VERB_DEVA_DO
            last = index + 1 >= count or _SENTENCE_END.search(gaps[index + 1]) is not None
            masked[index] = not (verb or last)
        elif kind == "number" and norms[index] in _HONORIFICS:
            masked[index] = not honorific(index)  # "Sau. Sunita", "सौ. सुनीता"
        elif kind == "number" and norms[index] in _ONCE:
            masked[index] = not (tight(index + 1) and norm_at(index + 1) in _TIMES)  # "ek baar"

    # Everyday number words next to a number word, a money word or a rupee word ("saath
    # hazaar", "दो अरब", "saath rupay", "₹ saath"; check 4, B4), right after a cost word
    # ("rate saath hai", "rate lagbhag saath"), right before a per-unit phrase ("saath per
    # watt", "das per unit") or before "wala" and a cost word ("saath wala rate"; check 5, M3).
    def number_or_rupee(other: int) -> bool:
        return (masked[other] and kinds[other] != "num") or kinds[other] == "cur"

    for index, kind in enumerate(kinds):
        if kind == "soft":
            masked[index] = (
                word_beside(index, number_or_rupee)
                or after_cost(index)
                or before_per(index)
                or before_wala_cost(index)
            )
    # Ranges: an everyday word or "do" before a range word and a number word ("do se teen
    # lakh", "saath se sattar hazaar", "do-do hazaar"; check 4, M2). Right to left, so a
    # chain of ranges is read whole.
    for index in range(count - 1, -1, -1):
        if kinds[index] not in {"soft", "do"} or masked[index]:
            continue
        if kinds[index] == "do" and norm_at(index - 1) in _BEFORE_VERB_DO:
            continue
        hyphen = tight(index + 1) and gaps[index + 1] in {"-", "–"} and word_number(index + 1)
        ranged = (
            norm_at(index + 1) in _RANGE_WORDS
            and tight(index + 1)
            and tight(index + 2)
            and word_number(index + 2)
        )
        masked[index] = hyphen or ranged
    # "a lakh", "a half", "a hundred"; not "a half-hearted reply" ("a [n]-hearted").
    for index, kind in enumerate(kinds):
        if kind == "article" and tight(index + 1) and masked[index + 1]:
            compound = index + 2 < count and gaps[index + 2] in {"-", "–"}
            masked[index] = norms[index + 1] in _TAKES_ARTICLE and not (
                compound and not masked[index + 2]
            )
    # A word we have no spelling for is read as a number (check 4, M1 fallback; check 5, M2):
    # - with the shape of a number word, right after a cost word or right before a per-unit
    #   phrase ("दर एक्क्याण्णव", "satalis per watt");
    # - any word directly before a rupee word or a money word ("pantalis rupaye",
    #   "chalis-ek hazaar"), unless it is an ordinary word ("in rupees", "spent lakhs", "the
    #   lakh"). A rupee word that already goes with the number after it ("quoted Rs 45")
    #   does not count.
    for index, kind in enumerate(kinds):
        if kind != "other" or norms[index] in _ORDINARY_BEFORE_MONEY:
            continue
        if _NUMBER_SHAPED.fullmatch(norms[index]) and (
            after_cost(index)
            or before_per(index)
            or before_wala_cost(index)
            or before_quote_verb(index)
        ):
            masked[index] = True
            continue
        if not tight(index + 1):
            continue
        following = index + 1
        if kinds[following] == "cur":
            owned = tight(following + 1) and masked[following + 1]
            masked[index] = not owned
        elif masked[following] and (
            norms[following] in _MONEY_TAILS
            or (money_scale(norms[following]) is not None and norms[following] not in _SHORT)
        ):
            masked[index] = True
    # A rupee word or sign with its number ("Rs 45", "45 rupees", "rupees forty five").
    for index, kind in enumerate(kinds):
        if kind == "cur":
            before = index > 0 and masked[index - 1] and _joins_currency(gaps[index])
            after = index + 1 < count and masked[index + 1] and _joins_currency(gaps[index + 1])
            masked[index] = before or after
    # "and" or "point" inside one number ("one and a half", "one hundred and twenty", "three
    # point seven"); "and" before digits or a rupee word starts another number ("₹45/W and
    # 3.7 lakh", "INR45 and inr 45").
    for index, kind in enumerate(kinds):
        if kind == "join":
            inside = tight(index) and tight(index + 1) and masked[index - 1] and masked[index + 1]
            masked[index] = inside and (
                norms[index] in _POINT or kinds[index + 1] not in {"num", "cur"}
            )


def _runs(scan: _Scan) -> list[tuple[int, int]]:
    """Token ranges [start, end) that read as one "[n]"."""
    runs: list[list[int]] = []
    for index in range(scan.count):
        if not scan.masked[index]:
            continue
        previous = scan.kinds[index - 1] if index else None
        currency = "cur" in {scan.kinds[index], previous}
        joined = scan.tight(index) or (currency and index > 0 and _joins_currency(scan.gaps[index]))
        if runs and index > 0 and scan.masked[index - 1] and joined:
            runs[-1][1] = index + 1
        else:
            runs.append([index, index + 1])
    return [(start, end) for start, end in runs]


def _render(scan: _Scan, runs: list[tuple[int, int]]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in runs:
        pieces.append(scan.text[cursor : scan.found[start].start()])
        pieces.append(MASK)
        cursor = scan.found[end - 1].end()
    pieces.append(scan.text[cursor:])
    return "".join(pieces)


def mask_numbers(text: str) -> str:
    """``text`` with every number replaced by "[n]" (idempotent)."""
    scan = _scan(text)
    if not scan.count:
        return text
    return _render(scan, _runs(scan))


def _joins_currency(gap: str) -> bool:
    return _CURRENCY_GAP.fullmatch(gap) is not None


# --- Reading one number (round 5) ---------------------------------------------------------------

# A digit token's parts: a rupee sign or word before, the digits, what is written onto them.
_NUM_PARTS = re.compile(
    rf"(?P<cur>[₹₨$]|(?i:rs|inr)[.:]?)?(?P<body>{_DIGIT}(?:[.,:/\-–]?{_DIGIT})*)(?P<suffix>.*)",
    re.DOTALL,
)
_PLAIN_DECIMAL = re.compile(r"\d+(?:\.\d+)?")


def _word_values() -> dict[str, Decimal]:
    found: dict[str, Decimal] = {}
    for table in (
        words.EN_ONES,
        words.EN_TENS,
        words.HI_ROMAN,
        words.MR_ROMAN,
        words.HI_DEVA,
        words.MR_DEVA,
    ):
        for word, value in table.items():
            found.setdefault(normalise(word), Decimal(value))
    for word, fraction in words.FRACTION_VALUES.items():
        found.setdefault(normalise(word), fraction)
    for word, number in NUMBER_WORDS.items():
        found.setdefault(word, number)
    return found


# Every 0-99 and fraction word with its value, everyday words included ("do" 2, "saath" 60).
_WORD_VALUES = _word_values()


def _decimal(body: str) -> Decimal | None:
    """Digits in any script, with digit-group commas or one decimal point; else None."""
    plain = body.replace(",", "")
    if _PLAIN_DECIMAL.fullmatch(plain) is None:
        return None
    try:
        return Decimal(
            "".join(char if char == "." else str(unicodedata.decimal(char)) for char in plain)
        )
    except (InvalidOperation, ValueError):
        return None


def _parts(scan: _Scan, index: int) -> re.Match[str] | None:
    return _NUM_PARTS.fullmatch(scan.found[index].group()) if scan.kinds[index] == "num" else None


def _suffix(scan: _Scan, index: int) -> str:
    """What is written onto a digit token ("kw" in "5kW", "/w" in "45/W"), normalised."""
    parts = _parts(scan, index)
    return normalise(parts.group("suffix")) if parts is not None else ""


def _value(scan: _Scan, start: int, end: int) -> Decimal | None:
    """The value of the number in tokens [start, end), or None when it is not one clear
    number ("45 000" and "4 5 0 0 0" read 45000, "nineteen ninety nine" 1999, "do" 2)."""
    kinds = scan.kinds[start:end]
    if all(kind == "num" for kind in kinds):
        bodies: list[str] = []
        for index in range(start, end):
            parts = _parts(scan, index)
            if parts is None or parts.group("cur"):
                return None
            bodies.append(parts.group("body"))
        if len(bodies) == 1:
            return _decimal(bodies[0])
        if not all(body.isdecimal() for body in bodies):
            return None
        return _decimal("".join(bodies))  # spaced digit groups are one number
    if "num" in kinds:
        return None
    said = scan.norms[start:end]
    if len(said) == 1:
        return _WORD_VALUES.get(said[0])
    return read_number(said)


def _number_groups(scan: _Scan) -> list[tuple[int, int]]:
    """Token ranges that read as one number, for the fact rule: tight neighbours, but a digit
    run with a unit written onto it ends its number ("48V 100Ah" is two)."""
    groups: list[list[int]] = []
    for index in range(scan.count):
        if not scan.masked[index] or scan.kinds[index] == "cur":
            continue
        if (
            groups
            and groups[-1][1] == index
            and scan.tight(index)
            and not _suffix(scan, index - 1)
            # Digits and number words are separate numbers ("55000 ek kW": not one "ek kW").
            and (scan.kinds[index] == "num") == (scan.kinds[index - 1] == "num")
        ):
            groups[-1][1] = index + 1
        else:
            groups.append([index, index + 1])
    return [(start, end) for start, end in groups]


# --- next_step.when_text (round 5, R2) ----------------------------------------------------------

_MONTHS = folded(
    {
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
# Round 6 (the coordinator's decision D3): a number in when_text stays only in these forms.
# - hh:mm with a colon (hours to 23);
# - h or h.mm (h to 12, mm to 59) directly before a clock word, or with am/pm written on;
# - a day of 31 or less directly before a month name or tarikh / तारीख / तारखेला (or directly
#   after a month name that has no day before it: "October 20");
# - a 4-digit year (2025-2035) directly after "<day> <month>";
# - dd/mm or dd/mm/yyyy.
# Every other number, decimal or number word reads "[n]" ("kal 5 baje [n] final", "[n] din").
_CLOCK_WORDS = folded({"baje", "बजे", "वाजता", "am", "pm", "o'clock", "oclock"})
_DEVA_CLOCK = re.compile(r"वाज[ऀ-ॿ]*")  # "वाजता", "वाजेपर्यंत"
_DAY_WORDS = folded({"tarikh", "tareekh", "tarik", "तारीख", "तारिख", "तारखेला"})
_DEVA_DAY = re.compile(r"ता(?:री|रि|र)ख[ऀ-ॿ]*")  # "तारखेपर्यंत"
# Hindi and Marathi months with a case ending ("ऑक्टोबरला", "नोव्हेंबरपर्यंत"); not the short
# मे / मई, which would match ordinary words.
_DEVA_MONTH = re.compile(
    "(?:"
    + "|".join(
        sorted(
            (re.escape(month) for month in _MONTHS if month[0] >= "ऀ" and len(month) > 2),
            key=len,
            reverse=True,
        )
    )
    + ")(?:ला|ात|मध्ये|पर्यंत|च्या|ची|चा|चे|में|को|तक|से)"
)
_HH_MM = re.compile(r"(\d{1,2}):(\d{2})")
_CLOCK_TIME = re.compile(r"(\d{1,2})(?:\.(\d{2}))?")
_DD_MM = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(?:\d{4}|\d{2}))?")
_DAY = re.compile(r"\d{1,2}")
_DAY_RANGE = re.compile(r"\d{1,2}(?:[-–]\d{1,2})+")
_YEAR = re.compile(r"\d{4}")
_ORDINAL_SUFFIXES = frozenset({"st", "nd", "rd", "th"})
_AM_PM = frozenset({"am", "pm"})
_LAST_DAY = 31
_LAST_HOUR = 23
_LAST_CLOCK_HOUR = 12
_LAST_MINUTE = 59
_FIRST_YEAR, _LAST_YEAR = 2025, 2035


def _clock_word(norm: str | None) -> bool:
    return norm is not None and (norm in _CLOCK_WORDS or _DEVA_CLOCK.fullmatch(norm) is not None)


def _month(norm: str | None) -> bool:
    return norm is not None and (norm in _MONTHS or _DEVA_MONTH.fullmatch(norm) is not None)


def _day_word(norm: str | None) -> bool:
    return norm is not None and (
        _month(norm) or norm in _DAY_WORDS or _DEVA_DAY.fullmatch(norm) is not None
    )


def _when_kept(scan: _Scan, start: int, end: int, kept: set[int], claimed: set[int]) -> bool:
    """Tokens [start, end) are one of the strict date and time forms of D3. ``kept`` holds
    the numbers kept so far, ``claimed`` the month words a day before them already uses."""
    if end - start != 1 or scan.kinds[start] != "num":
        return False  # number words, rupee words and runs of several numbers read "[n]"
    parts = _parts(scan, start)
    if parts is None or parts.group("cur"):
        return False
    body, suffix = parts.group("body"), normalise(parts.group("suffix"))
    before = scan.norms[end] if scan.tight(end) else None
    after_month = scan.tight(start) and _month(scan.norm_at(start - 1))
    clock = _HH_MM.fullmatch(body)
    if clock is not None and suffix in {"", *_AM_PM}:
        return int(clock.group(1)) <= _LAST_HOUR and int(clock.group(2)) <= _LAST_MINUTE
    date = _DD_MM.fullmatch(body)
    if date is not None and not suffix:
        return 1 <= int(date.group(1)) <= _LAST_DAY and 1 <= int(date.group(2)) <= 12
    time = _CLOCK_TIME.fullmatch(body)
    if time is not None and (suffix in _AM_PM or (not suffix and _clock_word(before))):
        minutes = time.group(2)
        return int(time.group(1)) <= _LAST_CLOCK_HOUR and (
            minutes is None or int(minutes) <= _LAST_MINUTE
        )
    if suffix and suffix not in _ORDINAL_SUFFIXES:
        return False
    if _DAY.fullmatch(body) is not None or _DAY_RANGE.fullmatch(body) is not None:
        days = [int(day) for day in re.split("[-–]", body)]
        if not all(1 <= day <= _LAST_DAY for day in days):
            return False
        if _day_word(before):
            if _month(before):
                claimed.add(end)
            return True
        if after_month and (start - 1) not in claimed:
            claimed.add(start - 1)
            return True
        return False
    if suffix or _YEAR.fullmatch(body) is None or not after_month:
        return False
    month = start - 1
    return (
        _FIRST_YEAR <= int(body) <= _LAST_YEAR
        and month in claimed
        and scan.tight(month)
        and (month - 1) in kept
    )


def mask_when(text: str) -> str:
    """``next_step.when_text`` with every number as "[n]" except strict date and time forms
    (round 6, D3): "kal shaam 5 baje", "Monday 10:30", "20 October", "18/10/2026" and "३
    तारखेला" stay; "advance 25000 dene ke baad" reads "advance [n] dene ke baad" and "kal 5
    baje 2.35 final" reads "kal 5 baje [n] final"."""
    scan = _scan(text)
    if not scan.count:
        return text
    kept: set[int] = set()
    claimed: set[int] = set()
    hidden: list[tuple[int, int]] = []
    for start, end in _runs(scan):
        if _when_kept(scan, start, end, kept, claimed):
            kept.update(range(start, end))
        else:
            hidden.append((start, end))
    return _render(scan, hidden)


# --- Other facts: the allow rule (round 5, R1) --------------------------------------------------

# Words that drop a fact that is not a price wherever they stand (R1), on top of rupee,
# money, cost and hundred words.
_FACT_DENY = folded(
    {
        "bill",
        "bills",
        "बिल",
        "amc",
        "maintenance",
        "देखभाल",
        "rent",
        "kiraya",
        "किराया",
        "भाडे",
        "भाडा",
        "भाड़ा",
        "bhada",
        "bhaada",
        "bhade",
        "subscription",
        "सबस्क्रिप्शन",
        "advance",
        "एडवांस",
        "ॲडव्हान्स",
        "अॅडव्हान्स",
        "token",
        "टोकन",
        "booking",
        "बुकिंग",
        "deposit",
        "डिपॉझिट",
        "डिपॉजिट",
        "subsidy",
        "सबसिडी",
        "सब्सिडी",
        "अनुदान",
        "पैसे",
        "पैसा",
        "paise",
        "paisa",
        "आगाऊ",
        "gst",
        "जीएसटी",
        "incl",
        "excl",
        "inclusive",
        "exclusive",
    }
)
# Units that explain the number before them: size, power, capacity, length, area (R1).
_UNITS = folded(
    {
        "kw",
        "kwp",
        "w",
        "wp",
        "watt",
        "watts",
        "kilowatt",
        "kilowatts",
        "va",
        "kva",
        "kwh",
        "ah",
        "mah",
        "v",
        "volt",
        "volts",
        "ton",
        "tons",
        "tonne",
        "tonnes",
        "टन",
        "hp",
        "bhk",
        "बीएचके",
        "sq",
        "sqft",
        "sqm",
        "sqmt",
        "square",
        "ft",
        "feet",
        "foot",
        "फूट",
        "फुट",
        "फीट",
        "m",
        "meter",
        "meters",
        "metre",
        "metres",
        "mtr",
        "mtrs",
        "मीटर",
        "mm",
        "cm",
        "km",
        "inch",
        "inches",
        "इंच",
        "acre",
        "acres",
        "एकर",
        "guntha",
        "gunthe",
        "गुंठा",
        "गुंठे",
    }
)
# Watt and kilowatt in Hindi and Marathi, with the endings that leave them a size
# ("पाच किलोवॅटची", "100 वॅटचे दिवे"; "45 वॅटला" is a per-watt price and is not here).
_DEVA_UNIT = re.compile(r"किलो(?:वॅट|वाट|वॉट)(?:चा|ची|चे|च्या|ला|ना)?|(?:वॅट|वाट|वॉट)(?:चा|ची|चे|च्या)?")
# Litres, in a load only ("250 L fridge", "geyser 15 L"; R4: elsewhere "L" is lakh).
_LITRES = folded({"l", "ltr", "ltrs", "litre", "litres", "liter", "liters", "लिटर", "लीटर"})
# Things counted (up to 100) in solar quotes and household loads.
_COUNTABLE = folded(
    {
        "panel",
        "panels",
        "plate",
        "plates",
        "module",
        "modules",
        "dongle",
        "dongles",
        "ac",
        "acs",
        "fridge",
        "fridges",
        "refrigerator",
        "refrigerators",
        "battery",
        "batteries",
        "inverter",
        "inverters",
        "fan",
        "fans",
        "pankha",
        "pankhe",
        "tubelight",
        "tubelights",
        "tube",
        "tubes",
        "light",
        "lights",
        "bulb",
        "bulbs",
        "led",
        "leds",
        "geyser",
        "geysers",
        "motor",
        "motors",
        "pump",
        "pumps",
        "tv",
        "tvs",
        "cooler",
        "coolers",
        "connector",
        "connectors",
        "pit",
        "pits",
        "cable",
        "cables",
        "wire",
        "wires",
        "structure",
        "structures",
        "stand",
        "stands",
        "room",
        "rooms",
        "floor",
        "floors",
        "storey",
        "storeys",
        "flat",
        "flats",
        "house",
        "houses",
        "shop",
        "shops",
        "machine",
        "machines",
        "computer",
        "computers",
        "laptop",
        "laptops",
        "oven",
        "ovens",
        "microwave",
        "microwaves",
        "heater",
        "heaters",
        "iron",
        "mixer",
        "string",
        "strings",
        "kit",
        "kits",
        "acdb",
        "dcdb",
        "arrestor",
        "arrestors",
        "arrester",
        "arresters",
        "earthing",
        "earthings",
        "camera",
        "cameras",
        "cctv",
        "tank",
        "tanks",
        "chimney",
        "purifier",
        "phase",  # "3 phase" connection in a load
        "फेज",
        "पॅनेल",
        "पॅनल",
        "पैनल",
        "प्लेट",
        "प्लेट्स",
        "डोंगल",
        "एसी",
        "फ्रिज",
        "फ्रीज",
        "बॅटरी",
        "बैटरी",
        "इन्व्हर्टर",
        "इनवर्टर",
        "इन्वर्टर",
        "पंखे",
        "पंखा",
        "पंख्या",
        "ट्यूबलाईट",
        "ट्यूबलाइट",
        "ट्युबलाईट",
        "लाईट",
        "लाइट",
        "बल्ब",
        "गिझर",
        "गीझर",
        "गीजर",
        "मोटर",
        "पंप",
        "टीव्ही",
        "टीवी",
        "कूलर",
        "खोल्या",
        "खोली",
        "कमरे",
        "कमरा",
        "मजले",
        "मजला",
        "दिवे",
        "दिवा",
        "केबल",
        "कनेक्टर",
        "अर्थिंग",
        "स्ट्रक्चर",
        "फ्लॅट",
        "बंगले",
    }
)
# Words that may stand between a count and the thing counted ("4 earthing pits", "2 extra
# panels", "2 MC4 connectors" with the code).
_MODIFIERS = folded(
    {
        "extra",
        "more",
        "additional",
        "new",
        "solar",
        "mono",
        "perc",
        "monoperc",
        "poly",
        "bifacial",
        "topcon",
        "dc",
        "ac",
        "earthing",
        "lightning",
        "ceiling",
        "exhaust",
        "split",
        "window",
        "inverter",
        "lithium",
        "tubular",
        "led",
        "small",
        "big",
        "wifi",
        "smart",
        "अतिरिक्त",
        "जादा",
        "नवीन",
        "सोलर",
        "मोठे",
        "छोटे",
        "आणखी",
        "अजून",
    }
)
_YEAR_WORDS = folded(
    {
        "saal",
        "sal",
        "saala",
        "saalon",
        "salon",
        "year",
        "years",
        "yrs",
        "yr",
        "varsh",
        "varsha",
        "varshe",
    }
)
_DEVA_YEAR = re.compile(r"(?:वर्ष|साल)[ऀ-ॿ]*")
_WARRANTY_WORDS = folded(
    {
        "warranty",
        "warrantee",
        "guarantee",
        "guaranty",
        "garanti",
        "वॉरंटी",
        "वारंटी",
        "वॉरन्टी",
        "वॉरेंटी",
        "गॅरंटी",
        "गारंटी",
        "हमी",
    }
)
# Address labels a small number belongs to in a site ("Plot 45", "Sector 21", "Phase 2").
# Not "flat": "flat 1500" is also a flat rate.
_SITE_LABELS = folded(
    {
        "plot",
        "sector",
        "phase",
        "survey",
        "sr",
        "gat",
        "ward",
        "wing",
        "block",
        "building",
        "bldg",
        "house",
        "no",
        "number",
        "lane",
        "gali",
        "galli",
        "road",
        "street",
        "floor",
        "room",
        "shop",
        "tower",
        "प्लॉट",
        "सेक्टर",
        "फेज",
        "गट",
        "सर्वे",
        "वॉर्ड",
        "विंग",
        "इमारत",
        "बिल्डिंग",
        "क्रमांक",
        "नंबर",
        "नं",
        "गल्ली",
        "गली",
        "रोड",
    }
)
_LABEL_GAP = re.compile(r"[\s.:#\-]*")
_GROUND_PLUS = re.compile(r"(?<![A-Za-z])[Gg]\s*\+\s*$")
_GROUND_PLUS_MAX = 10  # "G+2" floors, in a site or load only (round 6, check 6 theoretical)
# Round 6 (check 6, M5): "into" and "*" are Hinglish for "times", not the sides of an area.
_DIMENSION_WORDS = folded({"by", "x"})
_DIMENSION_SIGN = re.compile(r"\s*[x×]\s*")
# Round 6 (D2): watts are a size only from 100 up (panels and systems): "45 watt padega" and
# "47 watt" are per-watt prices. Kilowatts are not watts here.
_WATTS = folded({"w", "wp", "watt", "watts"})
_DEVA_WATT = re.compile(r"(?:वॅट|वाट|वॉट)(?:चा|ची|चे|च्या)?")
_WATT_SIZE_MIN = 100
# Round 6 (check 6, M4): "L" is litres only for a whole number of 10 or more ("250 L fridge").
_LITRE_L_MIN = 10
# Round 6 (D1): a model number glued to letters as the suffix ("Solis 5G"): a capital first.
_MODEL_SUFFIX = re.compile(r"[A-Z][A-Za-z]{0,3}")
# Words after a small number that make it a quoted price, not a model or a label ("Tata wale
# 42", "Adani 43 wala", "chalis me milta"; check 5, M7).
_PRICE_TAIL = folded(
    {
        "wale",
        "wala",
        "wali",
        "vale",
        "vala",
        "vali",
        "ne",
        "me",
        "mein",
        "main",
        "में",
        "मध्ये",
        "ला",
        "मे",
        "ka",
        "ki",
        "ke",
        "का",
        "की",
        "के",
        "se",
        "से",
        "pe",
        "par",
        "पे",
        "पर",
        "tak",
        "तक",
        "only",
        "sirf",
        "bas",
        "fakt",
        "फक्त",
        "सिर्फ",
        "final",
        "fix",
        "fixed",
        "lagenge",
        "lagega",
        "padega",
        "padenge",
        "chalega",
        "milega",
        "milta",
        "milti",
        "denge",
        "dega",
        "de",
        "देंगे",
        "देगा",
        "पडतील",
        "पडेल",
        "लागेल",
        "लागतील",
        "चालेल",
        "मिळेल",
        "चलेगा",
        "लगेगा",
        "लगेंगे",
        "पडेगा",
        "देऊ",
    }
)
# Per-unit words: a quote when said without their own number (BL6: "watt ke 45").
_BARE_PER_UNIT = folded(
    {"watt", "watts", "w", "wp", "unit", "units", "वॅट", "वाट", "वॉट", "युनिट", "यूनिट"}
)
_DEVA_PER_WORD = re.compile(r"(?:वॅट|वाट|वॉट|युनिट|यूनिट)[ऀ-ॿ]*")
_NOT_A_NAME = (
    _ORDINARY_BEFORE_MONEY
    | _COUNTABLE
    | _MODIFIERS
    | _FACT_DENY
    | _PRICE_TAIL
    | _PER_START
    | _PER_UNIT_NAMES
    | _UNITS
    | _SITE_LABELS
    | _DIMENSION_WORDS
)
_COUNT_MAX = 100
_WARRANTY_YEARS_MAX = 30
_DIMENSION_MAX = 1000


def _unit(norm: str | None, litres: frozenset[str]) -> bool:
    if norm is None:
        return False
    return norm in _UNITS or _DEVA_UNIT.fullmatch(norm) is not None or norm in litres


def _price_tail_ends(scan: _Scan, index: int) -> bool:
    """The stated words end with a price tail right after a unit ("55 kW ka", "60 kW pe",
    "पचपन किलोवाट का"; round 6, check 6 M2)."""
    return index == scan.count - 1 and scan.tight(index) and scan.norms[index] in _PRICE_TAIL


def _unit_explains(norm: str, value: Decimal | None) -> bool:
    """A unit explains its number, but watts only from 100 up (D2) and "L" only for a whole
    10 or more (check 6, M4)."""
    if norm in _WATTS or _DEVA_WATT.fullmatch(norm) is not None:
        return value is not None and value >= _WATT_SIZE_MIN
    if norm in _SHORT:  # "l"
        return value is not None and value == value.to_integral_value() and value >= _LITRE_L_MIN
    return True


def _year_word(norm: str | None) -> bool:
    return norm is not None and (norm in _YEAR_WORDS or _DEVA_YEAR.fullmatch(norm) is not None)


def _code(scan: _Scan, index: int) -> bool:
    """A Latin or Devanagari word with digits written onto it ("MC4", "PuREPower5", "एमसी4";
    round 6 adds Devanagari, check 6 EV6b)."""
    return (
        scan.found[index].lastgroup in {"latin", "deva"}
        and scan.kinds[index] == "other"
        and index + 1 < scan.count
        and scan.kinds[index + 1] == "num"
        and scan.gaps[index + 1] == ""
    )


def _name(scan: _Scan, index: int) -> bool:
    """A Latin word written with a capital that is not an ordinary, cost, count or unit word
    ("PuREPower", "Pro", "MC"): the name a small model number belongs to."""
    if index < 0 or scan.kinds[index] != "other":
        return False
    group = scan.found[index].lastgroup
    norm = scan.norms[index]
    if group not in {"latin", "deva"} or norm in _NOT_A_NAME:
        return False
    if is_time_word(norm) or _year_word(norm) or norm in _RATE_VERBS:
        return False
    # Devanagari has no capitals: only a code written onto its digits ("एमसी4"; round 6).
    return group == "deva" or any(char.isupper() for char in scan.found[index].group())


def _counted_after(scan: _Scan, end: int) -> bool:
    """A countable noun follows the number ending before ``end``, with at most two modifiers
    or codes between ("2 panels", "4 earthing pits", "2 MC4 connectors", "तीन पंखे")."""
    index, skipped = end, 0
    while index < scan.count and scan.tight(index) and skipped <= 2:
        norm = scan.norms[index]
        if norm in _COUNTABLE:
            return True
        if _code(scan, index):
            index, skipped = index + 2, skipped + 1
        elif norm in _MODIFIERS:
            index, skipped = index + 1, skipped + 1
        else:
            return False
    return False


def _named(scan: _Scan, start: int, fact_type: str | None, value: Decimal) -> bool:
    """The small number at ``start`` belongs to a name or a label: a code written onto it
    ("MC4", "PuREPower5"), a model name joined by a hyphen in a product mention
    ("PuREPower-5"; round 6, D1: "PuREPower 5" with a space is no longer a model), an
    address label in a site ("Plot 45", "Sector 21") or a ground-plus floor count up to 10 in
    a site or load ("G+2")."""
    if start == 0:
        return False
    previous, gap = start - 1, scan.gaps[start]
    if gap == "" and scan.kinds[start] == "num" and _name(scan, previous):
        return True
    if (
        fact_type == "product_mention"
        and gap in {"-", "–"}
        and scan.kinds[start] == "num"
        and scan.found[previous].lastgroup == "latin"
        and _name(scan, previous)
    ):
        return True
    if (
        fact_type == "site"
        and _LABEL_GAP.fullmatch(gap) is not None
        and scan.norms[previous] in _SITE_LABELS
    ):
        return True
    return (
        fact_type in {"site", "load"}
        and value <= _GROUND_PLUS_MAX
        and _GROUND_PLUS.search(scan.text[: scan.found[start].start()]) is not None
    )


def _model_suffix(scan: _Scan, index: int, value: Decimal | None) -> bool:
    """A model number with capital letters written onto it in a product mention ("Solis 5G";
    round 6, D1), never a money or per-unit sign ("45k", "2.95L", "45/W")."""
    parts = _parts(scan, index)
    if parts is None or value is None or value > _COUNT_MAX:
        return False
    raw = parts.group("suffix")
    norm = normalise(raw)
    return (
        _MODEL_SUFFIX.fullmatch(raw) is not None
        and norm not in _SHORT
        and money_scale(norm) is None
        and not is_currency(norm)
    )


def _explained(
    scan: _Scan,
    start: int,
    end: int,
    fact_type: str | None,
    *,
    warranty: bool,
    litres: frozenset[str],
) -> bool:
    """Whether the number in tokens [start, end) is explained by what follows it (R1)."""
    value = _value(scan, start, end)
    suffix = _suffix(scan, end - 1)
    following = scan.norms[end] if scan.tight(end) else None
    if suffix:  # "5kW", "150Ah", "48V", "3rd"; "45/W", "45/-", "18%" are not explained
        if _unit(suffix, litres):
            return _unit_explains(suffix, value) and not _price_tail_ends(scan, end)
        if suffix in _ORDINAL_SUFFIXES:  # "3rd floor", in a site only (round 6)
            return (
                fact_type == "site"
                and value is not None
                and value <= _COUNT_MAX
                and following not in _PRICE_TAIL
            )
        return fact_type == "product_mention" and _model_suffix(scan, end - 1, value)
    if following is not None and _unit(following, litres):
        return _unit_explains(following, value) and not _price_tail_ends(scan, end + 1)
    if following == "kilo" and scan.tight(end + 1) and scan.norms[end + 1].startswith("watt"):
        return True
    if following in _PRICE_TAIL or value is None:
        return False
    if value <= _COUNT_MAX and _counted_after(scan, end):
        return True
    if warranty and value <= _WARRANTY_YEARS_MAX and _year_word(following):
        return True
    return value <= _COUNT_MAX and _named(scan, start, fact_type, value)


def _bare_per_unit_word(scan: _Scan) -> bool:
    """A watt or unit word without its own number directly before it ("watt ke 45", "हर
    वॉट पे ४६", "45 lagenge per watt"; check 5, BL6)."""
    for index, norm in enumerate(scan.norms):
        if scan.kinds[index] == "num":
            continue
        if norm not in _BARE_PER_UNIT and _DEVA_PER_WORD.fullmatch(norm) is None:
            continue
        before = index - 1
        if scan.norm_at(before) == "kilo" and scan.tight(index):
            before -= 1
        own = (
            before >= 0
            and scan.tight(before + 1)
            and scan.masked[before]
            and scan.kinds[before] != "cur"
        )
        if not own:
            return True
    return False


def _dimension_pairs(scan: _Scan, groups: list[tuple[int, int]]) -> set[int]:
    """Groups that are the two sides of an area ("30 by 40", "30x40", "30 × 40")."""
    paired: set[int] = set()
    for position in range(len(groups) - 1):
        (first, first_end), (second, second_end) = groups[position], groups[position + 1]
        glued = (
            second == first_end and _suffix(scan, first_end - 1) == "x" and scan.gaps[second] == ""
        )
        sign = second == first_end and _DIMENSION_SIGN.fullmatch(scan.gaps[second]) is not None
        word = (
            second == first_end + 1
            and scan.norms[first_end] in _DIMENSION_WORDS
            and scan.tight(first_end)
            and scan.tight(second)
        )
        if not (glued or sign or word):
            continue
        sides = (_value(scan, first, first_end), _value(scan, second, second_end))
        if all(
            side is not None and side <= _DIMENSION_MAX and side == side.to_integral_value()
            for side in sides
        ):
            paired.update({position, position + 1})
    return paired


def fact_carries_money(text: str, fact_type: str | None = None) -> bool:
    """True when the stated words of a fact that is not a price must be dropped (round 5,
    the coordinator's decision R1: an allow rule).

    - Any rupee, money, cost, hundred or GST word, or bill, AMC, maintenance, rent,
      subscription, advance, token, booking, deposit, subsidy, पैसे, आगाऊ, incl/excl.
    - Any number (digits in any script, spaced digit groups, keycaps, fractions and every
      number word the summary mask reads) not explained by what follows it: a size, power,
      capacity, length or area unit ("5 kW", "150Ah", "2 BHK", "1.5 ton", "800 sq ft";
      litres in a load only); a countable noun for a count up to 100 ("2 panels", "तीन
      पंखे"); a year word for up to 30 years in a warranty ("25 saal"); a model name for up
      to 100 in a product mention ("PuREPower 5"). Also kept: codes ("MC4"), ordinals
      ("3rd floor"), "G+2", address labels in a site ("Plot 45") and areas ("30 by 40").
      Time words never explain a number ("bill 3000 mahina", "AMC 2500 saal").
    - A watt or unit word without its own number before it, while any number is said
      ("watt ke 45").

    Round 6 (D1, D2): watts explain only from 100 up; a rate verb with any number drops the
    fact; in a product mention only a number written onto letters or joined by a hyphen is
    a model ("PuREPower5", "PuREPower-5"; "PuREPower 5" and "Adani forty" drop).
    """
    keycaps = {0xFE0F: None, 0x20E3: None}  # "1️⃣9️⃣9️⃣9️⃣" reads 1999
    cleaned = clean_text(text).translate(keycaps)
    said = tokens_of(cleaned)
    if money_word_said(cleaned) or soft_price(cleaned) or any(word in _FACT_DENY for word in said):
        return True
    scan = _scan(cleaned)
    litres = _litres(scan, fact_type)
    for index, kind in enumerate(scan.kinds):
        if kind == "short" and scan.norms[index] in litres:
            scan.masked[index] = False  # "250 L fridge": litres, not lakh (R4)
    groups = _number_groups(scan)
    if not groups:
        return False
    if _bare_per_unit_word(scan) or any(norm in _RATE_VERBS for norm in scan.norms):
        return True  # "watt ke 45"; a rate verb with any number (round 6, D2)
    if fact_type == "product_mention" and any(
        kind != "num" for start, end in groups for kind in scan.kinds[start:end]
    ):
        return True  # any number word in a product mention (round 6, D1: "Adani forty")
    paired = _dimension_pairs(scan, groups) if fact_type == "site" else set()
    warranty = fact_type == "warranty" or any(word in _WARRANTY_WORDS for word in said)
    return not all(
        position in paired
        or _explained(scan, start, end, fact_type, warranty=warranty, litres=litres)
        for position, (start, end) in enumerate(groups)
    )


def _litres(scan: _Scan, fact_type: str | None) -> frozenset[str]:
    """The litre words that explain a number: in a load only, and "L" only with an
    appliance or other counted thing named ("250 L fridge"; "3.7 L" alone is lakh, R4)."""
    if fact_type != "load":
        return frozenset()
    if any(norm in _COUNTABLE for norm in scan.norms):
        return _LITRES
    return _LITRES - _SHORT
