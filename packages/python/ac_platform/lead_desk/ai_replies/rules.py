"""The rules AI replies keep, before and after the model, with no model involved.

An AI reply only ever talks about the organisation's own business, from what the
organisation wrote down about itself. It never acts as a general assistant (Meta
does not allow general-purpose AI chat on WhatsApp). These checks run on every
message, in English, Hindi, Marathi and the Hinglish leads write:

- A person asks to stop (STOP, unsubscribe, "band karo", "बंद करो", "थांबवा"): no
  reply, and no more automatic messages to them.
- A person asks for a human, complains, or talks price while the organisation hasn't
  allowed price answers, or bargains at all: no AI reply; the lead's seller is told.
- A drafted reply that names a price while price answers are off, or a phone number,
  email or link the organisation didn't write down, is not sent.

Settings are data per organisation (``ai_replies`` in its Lead Desk settings).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

Mode = Literal["off", "suggest", "auto"]
Reason = Literal[
    "opt_out",
    "human",
    "complaint",
    "price",
    "discount",
    "unsure",
    "off_topic",
    "not_text",
    "no_profile",
    "window",
    "blocked_reply",
]
KEY: Final[str] = "ai_replies"
CHANNELS: Final[tuple[str, ...]] = ("whatsapp", "messenger", "instagram")
MAX_FAQS: Final[int] = 40
MAX_TEXT: Final[int] = 4000
REPLY_LIMIT: Final[int] = 700

# Words are matched as whole words (any case) or, for scripts without spaces between
# the words that matter here, as phrases.
_OPT_OUT: Final[tuple[str, ...]] = (
    "stop",
    "unsubscribe",
    "stop messaging",
    "stop messages",
    "don't message",
    "dont message",
    "do not message",
    "remove me",
    "opt out",
    "band karo",
    "mat bhejo",
    "message mat",
    "बंद करो",
    "बंद करें",
    "मत भेजो",
    "मैसेज मत",
    "थांबवा",
    "पाठवू नका",
)
_HUMAN: Final[tuple[str, ...]] = (
    "human",
    "real person",
    "a person",
    "agent",
    "representative",
    "talk to someone",
    "speak to someone",
    "call me",
    "manager",
    "insaan",
    "kisi se baat",
    "baat karni",
    "call karo",
    "phone karo",
    "इंसान",
    "किसी से बात",
    "बात करनी",
    "कॉल करो",
    "फोन करो",
    "माणसाशी",
    "फोन करा",
)
_COMPLAINT: Final[tuple[str, ...]] = (
    "complaint",
    "complain",
    "refund",
    "fraud",
    "cheat",
    "cheated",
    "scam",
    "worst",
    "pathetic",
    "angry",
    "disappointed",
    "legal",
    "consumer court",
    "shikayat",
    "dhokha",
    "शिकायत",
    "धोखा",
    "तक्रार",
    "फसवणूक",
)
_PRICE: Final[tuple[str, ...]] = (
    "price",
    "prices",
    "pricing",
    "cost",
    "costs",
    "rate",
    "rates",
    "fees",
    "fee",
    "charges",
    "how much",
    "budget",
    "emi",
    "lakh",
    "lakhs",
    "crore",
    "kitna",
    "kitne",
    "kitni",
    "daam",
    "keemat",
    "kimat",
    "कीमत",
    "दाम",
    "कितना",
    "कितने",
    "किंमत",
    "किती",
    "शुल्क",
)
_DISCOUNT: Final[tuple[str, ...]] = (
    "discount",
    "negotiate",
    "negotiable",
    "best price",
    "final price",
    "lowest",
    "cheaper",
    "reduce",
    "kam karo",
    "kam kar",
    "thoda kam",
    "कम करो",
    "कम कर",
    "डिस्काउंट",
    "सवलत",
)
_MONEY: Final[re.Pattern[str]] = re.compile(
    r"(₹|\brs\.?\s*\d|\binr\b|\$\s*\d|\d[\d,]*(\.\d+)?\s*(/-|lakh|lac|crore|cr\b|k\b))",
    re.IGNORECASE,
)
_PHONE: Final[re.Pattern[str]] = re.compile(r"\+?\d[\d\s-]{7,}\d")
_EMAIL: Final[re.Pattern[str]] = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINK: Final[re.Pattern[str]] = re.compile(r"(https?://|www\.)\S+", re.IGNORECASE)


def _has(text: str, phrases: Sequence[str]) -> bool:
    folded = text.casefold()
    words = set(re.findall(r"[\w']+", folded))
    for phrase in phrases:
        key = phrase.casefold()
        if " " in key or not key.isascii():
            if key in folded:
                return True
        elif key in words:
            return True
    return False


def opt_out(text: str | None) -> bool:
    """They asked to stop: the whole message is a stop word, or it says so plainly."""
    if not text:
        return False
    stripped = text.strip().casefold().strip(".!")
    if stripped in {"stop", "unsubscribe", "stop all", "बंद"}:
        return True
    return _has(text, [p for p in _OPT_OUT if p != "stop"])


@dataclass(frozen=True, slots=True)
class Settings:
    mode: Mode = "suggest"
    channels: tuple[str, ...] = CHANNELS
    quote_prices: bool = False
    business_name: str = ""
    about: str = ""
    offerings: str = ""
    faqs: tuple[tuple[str, str], ...] = ()
    notes: str = ""

    @property
    def has_profile(self) -> bool:
        return bool(self.about.strip() or self.offerings.strip() or self.faqs)

    def knowledge(self) -> str:
        """What the organisation wrote about itself: the only facts a reply may use."""
        parts = [
            f"Business: {self.business_name}" if self.business_name else "",
            f"About: {self.about}" if self.about else "",
            f"Products and services: {self.offerings}" if self.offerings else "",
            *(f"Q: {q}\nA: {a}" for q, a in self.faqs),
            f"Notes: {self.notes}" if self.notes else "",
        ]
        return "\n\n".join(part for part in parts if part)[: MAX_TEXT * 4]


def read(config: Mapping[str, Any]) -> Settings:
    raw = config.get(KEY)
    value: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    mode = value.get("mode")
    channels = value.get("channels")
    found = value.get("faqs")
    faqs: list[Any] = found if isinstance(found, list) else []
    return Settings(
        mode=mode if mode in ("off", "suggest", "auto") else "suggest",
        channels=tuple(c for c in channels if c in CHANNELS)
        if isinstance(channels, list)
        else CHANNELS,
        quote_prices=value.get("quote_prices") is True,
        business_name=str(value.get("business_name") or "")[:200],
        about=str(value.get("about") or "")[:MAX_TEXT],
        offerings=str(value.get("offerings") or "")[:MAX_TEXT],
        faqs=tuple(
            (str(item.get("question") or "")[:300], str(item.get("answer") or "")[:1000])
            for item in faqs[:MAX_FAQS]
            if isinstance(item, Mapping) and item.get("question") and item.get("answer")
        ),
        notes=str(value.get("notes") or "")[:MAX_TEXT],
    )


def as_config(settings: Settings) -> dict[str, Any]:
    return {
        "mode": settings.mode,
        "channels": list(settings.channels),
        "quote_prices": settings.quote_prices,
        "business_name": settings.business_name,
        "about": settings.about,
        "offerings": settings.offerings,
        "faqs": [{"question": q, "answer": a} for q, a in settings.faqs],
        "notes": settings.notes,
    }


@dataclass(frozen=True, slots=True)
class Before:
    """What the rules say before any model is asked."""

    go: bool
    reason: Reason | None = None
    stop: bool = False  # they opted out: no automatic message to them again


def before(text: str | None, settings: Settings, *, window_open: bool) -> Before:
    if not text or not text.strip():
        return Before(False, "not_text")
    if opt_out(text):
        return Before(False, "opt_out", stop=True)
    if not window_open:
        return Before(False, "window")
    if not settings.has_profile:
        return Before(False, "no_profile")
    if _has(text, _HUMAN):
        return Before(False, "human")
    if _has(text, _COMPLAINT):
        return Before(False, "complaint")
    if _has(text, _DISCOUNT):
        return Before(False, "discount")
    if not settings.quote_prices and (_has(text, _PRICE) or _MONEY.search(text)):
        return Before(False, "price")
    return Before(True)


@dataclass(frozen=True, slots=True)
class After:
    ok: bool
    reply: str = ""
    reason: Reason | None = None
    notes: list[str] = field(default_factory=list)


def after(
    reply: str | None, settings: Settings, *, model_handoff: bool, model_reason: str | None
) -> After:
    """The model's draft, checked: a hand-off it asked for, or anything it shouldn't say."""
    if model_handoff:
        reason: Reason = (
            model_reason  # type: ignore[assignment]
            if model_reason in ("human", "complaint", "price", "discount", "unsure", "off_topic")
            else "unsure"
        )
        return After(False, reason=reason)
    text = (reply or "").strip()
    if not text:
        return After(False, reason="unsure")
    text = text[:REPLY_LIMIT]
    known = settings.knowledge()
    notes: list[str] = []
    if not settings.quote_prices and _MONEY.search(text):
        notes.append("names a price")
    known_digits = re.sub(r"\D", "", known)
    for match in _PHONE.finditer(text):
        if re.sub(r"\D", "", match.group(0)) not in known_digits:
            notes.append("gives a phone number you didn't write down")
    for pattern, what in ((_EMAIL, "an email"), (_LINK, "a link")):
        for match in pattern.finditer(text):
            if match.group(0).casefold().rstrip(".,") not in known.casefold():
                notes.append(f"gives {what} you didn't write down")
    if notes:
        return After(False, reason="blocked_reply", notes=sorted(set(notes)))
    return After(True, reply=text)


def script_of(text: str) -> str:
    """The writing system of a message, as a hint for the reply's language."""
    if re.search(r"[ऀ-ॿ]", text):
        return "Devanagari"
    if re.search(r"[ঀ-৿]", text):
        return "Bengali"
    if re.search(r"[஀-௿]", text):
        return "Tamil"
    if re.search(r"[ఀ-౿]", text):
        return "Telugu"
    if re.search(r"[઀-૿]", text):
        return "Gujarati"
    return "Latin"
