"""A suggested WhatsApp or SMS after a call, in the call's language (owner, 25 Oct 2026:
the after-call chain). Fixed wording, never a model: thanks for the call and, when the
call agreed one, the next time to talk. The page fills {my_name} and {org} as it does
for its other ready messages; the seller reads it, changes it if they like, and sending
only opens their own WhatsApp or SMS with it.

Pure: the call's quoted words, the lead's name and the agreed follow-up in; the draft out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

Language = Literal["en", "hinglish", "hi", "mr"]
# The key the lead's message log keeps (lead_desk.vocabulary AFTER_CALL_REPLY).
TEMPLATE: Final = "after_call"
WHEN_LIMIT: Final = 60

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Words, without the danda (।, ॥) that ends a sentence.
_DEVANAGARI_WORD = re.compile(r"[ऀ-ॣ०-ॿ]+")
_LETTER = re.compile(r"[^\W\d_]")
_LATIN_WORD = re.compile(r"[a-z]+")

# Common words only one language uses: enough to tell Marathi from Hindi in Devanagari,
# and Hinglish (or Marathi) from English in Latin letters.
_MARATHI: Final = frozenset(
    {"आहे", "आहेत", "नाही", "काय", "तुम्ही", "मला", "करा", "होय", "उद्या", "आणि", "पण", "झाले"}
)
_HINDI: Final = frozenset(
    {"है", "हैं", "नहीं", "क्या", "आप", "मुझे", "करो", "करें", "हाँ", "हां", "कल", "और", "बात"}
)
_HINGLISH: Final = frozenset(
    {
        "hai",
        "hain",
        "nahi",
        "nahin",
        "haan",
        "kya",
        "aap",
        "aapko",
        "mujhe",
        "hum",
        "karo",
        "karenge",
        "kal",
        "ji",
        "theek",
        "thik",
        "accha",
        "acha",
        "baat",
        "bataunga",
        "bataiye",
        "hoon",
        "kaise",
        "kab",
        "abhi",
        "matlab",
        "sab",
    }
)
_MARATHI_LATIN: Final = frozenset(
    {"aahe", "ahe", "kay", "tumhi", "mala", "kara", "udya", "ani", "zala", "bolu", "aapan"}
)

# (thanks, the agreed next talk, an open door), then the signature.
_WORDS: Final[dict[str, tuple[str, str, str]]] = {
    "en": (
        "Hi{name}, thank you for your time on the call today.",
        " As we agreed, we'll talk again {when}.",
        " If you have any questions, just message me here.",
    ),
    "hinglish": (
        "Namaste{name} ji, aaj call par baat karne ke liye dhanyavaad.",
        " Jaisa tay hua, hum {when} phir baat karenge.",
        " Koi bhi sawaal ho to yahin message kar dijiye.",
    ),
    "hi": (
        "नमस्ते{name} जी, आज कॉल पर बात करने के लिए धन्यवाद।",
        " जैसा तय हुआ, हम {when} फिर बात करेंगे।",
        " कोई भी सवाल हो तो यहीं मैसेज कर दीजिए।",
    ),
    "mr": (
        "नमस्कार{name}, आज कॉलवर वेळ दिल्याबद्दल धन्यवाद.",
        " ठरल्याप्रमाणे आपण {when} पुन्हा बोलू.",
        " काही प्रश्न असल्यास इथेच मेसेज करा.",
    ),
}
_SIGNATURE: Final = " - {my_name}, {org}"
# Without a name, the greeting stands alone ("Namaste ji" reads oddly).
_NO_NAME: Final[dict[str, str]] = {"hinglish": " ji", "hi": " जी"}


@dataclass(frozen=True, slots=True)
class Draft:
    language: Language
    text: str
    follow_up: str | None


def language(quotes: Iterable[str]) -> Language:
    """The call's language from its quoted words; English when it can't tell."""
    words = " ".join(quotes)
    letters = len(_LETTER.findall(words))
    if not letters:
        return "en"
    if len(_DEVANAGARI.findall(words)) * 3 >= letters:
        spoken = _DEVANAGARI_WORD.findall(words)
        marathi = sum(word in _MARATHI for word in spoken)
        return "mr" if marathi > sum(word in _HINDI for word in spoken) else "hi"
    latin = _LATIN_WORD.findall(words.casefold())
    hinglish = sum(word in _HINGLISH for word in latin)
    marathi = sum(word in _MARATHI_LATIN for word in latin)
    most = max(hinglish, marathi)
    if most < 3 or most * 12 < len(latin):
        return "en"
    return "mr" if marathi > hinglish else "hinglish"


def first_name(name: str | None, placeholders: Iterable[str] = ()) -> str | None:
    """The lead's first name, or None for a placeholder or a number."""
    words = (name or "").split()
    if not words or " ".join(words).casefold() in set(placeholders):
        return None
    first = words[0].strip(".,").replace("{", "").replace("}", "")
    return first if any(char.isalpha() for char in first) else None


def _clean(when: str | None) -> str | None:
    text = " ".join((when or "").replace("{", "").replace("}", "").split())
    return text[:WHEN_LIMIT].strip() or None


def draft(quotes: Iterable[str], *, name: str | None, when: str | None) -> Draft:
    """The suggested reply; {my_name} and {org} are left for the page to fill."""
    spoken = language(quotes)
    thanks, agreed, open_door = _WORDS[spoken]
    follow_up = _clean(when)
    greeting = (
        thanks.replace("{name}", f" {name}")
        if name
        else thanks.replace("{name}" + _NO_NAME.get(spoken, ""), "").replace("{name}", "")
    )
    middle = agreed.replace("{when}", follow_up) if follow_up else open_door
    return Draft(spoken, greeting + middle + _SIGNATURE, follow_up)
