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

Nothing here calls a model or the network.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from ac_platform.partner_events import number_words as words
from ac_platform.partner_events.amounts import (
    FRACTION_WORDS,
    HUNDRED_WORDS,
    MONEY_UNITS,
    NUMBER_WORDS,
    folded,
    is_currency,
    is_unit_word,
    money_scale,
    normalise,
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


def _deva_number(token: str) -> bool:
    """A Devanagari number word, with a Marathi case ending, a Hindi plural, a joined
    fraction ("साडेतीन", "सव्वादोन", "पावणेतीनशे") or a money word's ending."""
    if token in _NUMBER or token in _EXTRA_DEVA or money_scale(token) is not None:
        return True
    if _stem_with_ending(token):
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
    if norm in _SOFT:
        if norm == "one":
            return "one"
        if norm == "do":
            return "do"
        return "deva_do" if norm == "दो" else "soft"
    if group == "deva":
        return "number" if _deva_number(norm) or _compound(norm) else "other"
    if norm in _NUMBER or _compound(norm):
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


def mask_numbers(text: str) -> str:
    """``text`` with every number replaced by "[n]" (idempotent)."""
    found = list(_TOKEN.finditer(text))
    if not found:
        return text
    count = len(found)
    norms = [normalise(match.group()).replace("’", "'") for match in found]
    kinds = [_kind(match.lastgroup, norm) for match, norm in zip(found, norms, strict=True)]
    gaps = [""] + [text[found[index - 1].end() : found[index].start()] for index in range(1, count)]
    masked = [kind in {"num", "number"} for kind in kinds]

    def tight(index: int) -> bool:
        """Token ``index`` follows token ``index - 1`` as part of one number."""
        return 0 < index < count and _TIGHT.fullmatch(gaps[index]) is not None

    def norm_at(index: int) -> str | None:
        return norms[index] if 0 <= index < count else None

    def kind_before(index: int) -> str | None:
        return kinds[index - 1] if tight(index) else None

    def kind_after(index: int) -> str | None:
        return kinds[index + 1] if tight(index + 1) else None

    def word_beside(index: int, test: Callable[[int], bool]) -> bool:
        return (tight(index) and test(index - 1)) or (tight(index + 1) and test(index + 1))

    for index, kind in enumerate(kinds):
        if kind == "after_tens":  # "twenty first"
            masked[index] = tight(index) and norms[index - 1] in _TENS
        elif kind == "short":  # "45 k", "2.5 L", "forty k"
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
    # Everyday number words next to a number word ("saath hazaar", "दो अरब").
    for index, kind in enumerate(kinds):
        if kind == "soft":
            masked[index] = word_beside(
                index, lambda other: masked[other] and kinds[other] != "num"
            )
    # "a lakh", "a half", "a hundred"; not "a half-hearted reply" ("a [n]-hearted").
    for index, kind in enumerate(kinds):
        if kind == "article" and tight(index + 1) and masked[index + 1]:
            compound = index + 2 < count and gaps[index + 2] in {"-", "–"}
            masked[index] = norms[index + 1] in _TAKES_ARTICLE and not (
                compound and not masked[index + 2]
            )
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

    spans: list[list[int]] = []
    for index in range(count):
        if not masked[index]:
            continue
        start, end = found[index].start(), found[index].end()
        currency = "cur" in {kinds[index], kinds[index - 1] if index else None}
        joined = tight(index) or (currency and index > 0 and _joins_currency(gaps[index]))
        if spans and index > 0 and masked[index - 1] and joined:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        pieces.append(MASK)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _joins_currency(gap: str) -> bool:
    return _CURRENCY_GAP.fullmatch(gap) is not None
