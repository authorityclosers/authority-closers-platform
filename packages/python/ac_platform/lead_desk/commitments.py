"""Promises in a seller's words become task proposals (work-memory engine, section 4;
docs/product/lead-desk/work-memory-engine.md).

"Call back at 5:30", "kal shaam 6 baje whatsapp bhejna", "उद्या सकाळी 11 वाजता फोन करा",
"meeting Thursday 4pm at Baner office": each becomes a proposal with a kind, a time, an
end and a place when it has them, how sure the rules are, and the words they read. A
proposal is only ever offered; a person confirms it in one tap (principle 4).

Pure: the text, the moment it was written and the work hours in; proposals out. Times
are read in India time (no daylight saving), and a promise is never in the past.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

IST: Final = ZoneInfo("Asia/Kolkata")

TaskKind = Literal["call_back", "whatsapp", "email", "send_file", "meeting", "other"]
TASK_KINDS: Final[tuple[TaskKind, ...]] = (
    "call_back",
    "whatsapp",
    "email",
    "send_file",
    "meeting",
    "other",
)

# How long a meeting runs when nobody says.
MEETING_LENGTH: Final = timedelta(hours=1)
# Two proposals of one kind this close together are one promise.
SAME_PROMISE: Final = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class Proposal:
    kind: TaskKind
    starts_at: datetime
    ends_at: datetime | None
    location: str | None
    title: str
    # 0.5 (a time alone) to 0.9 (a kind and an exact time).
    confidence: float
    # The words the rules read, as written.
    evidence: str
    # A promise outside the seller's work hours stays (a promise is a promise), marked.
    outside_hours: bool = False


# ----- words ------------------------------------------------------------------------------

_DEVANAGARI_DIGITS: Final = str.maketrans("०१२३४५६७८९", "0123456789")

# Latin cues match whole words; Devanagari cues match as written (Python's word
# boundaries split Devanagari vowel signs).
_KIND_CUES: Final[dict[TaskKind, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "meeting": (
        (
            "meeting",
            "meet",
            "visit",
            "site visit",
            "demo",
            "appointment",
            "milna",
            "milte",
            "bhet",
        ),
        ("मीटिंग", "भेट", "भेटू", "मिलना", "मिलेंगे", "डेमो"),
    ),
    "whatsapp": (
        ("whatsapp", "whats app", "wa", "watsapp", "msg", "message"),
        ("व्हॉट्सअ‍ॅप", "व्हॉट्सॲप", "व्हाट्सएप", "मेसेज"),
    ),
    "email": (("email", "e-mail", "mail"), ("ईमेल", "मेल")),
    "send_file": (
        (
            "brochure",
            "pdf",
            "quotation",
            "quote",
            "details",
            "price list",
            "catalogue",
            "catalog",
            "file",
            "send",
            "bhejo",
            "bhejna",
            "bhej",
        ),
        ("ब्रोशर", "पाठवा", "पाठव", "भेजो", "भेजना"),
    ),
    "call_back": (
        (
            "call back",
            "callback",
            "call",
            "phone",
            "ring",
            "baat",
            "fon",
        ),
        ("फोन", "कॉल", "बात"),
    ),
}
# When several kinds are named, the most specific wins ("send the brochure on WhatsApp"
# is a WhatsApp; "call to fix the meeting" is a meeting).
_KIND_ORDER: Final[tuple[TaskKind, ...]] = (
    "meeting",
    "whatsapp",
    "email",
    "send_file",
    "call_back",
)

_DAY_WORDS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...], int], ...]] = (
    (("day after tomorrow", "parso", "parson"), ("परवा", "परसों"), 2),
    (("tomorrow", "tmrw", "tmr", "kal", "udya", "udyaa"), ("उद्या", "कल"), 1),
    (("today", "aaj", "aj", "tonight"), ("आज",), 0),
)

_WEEKDAYS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = (
    (("monday", "mon", "somvar", "somwar"), ("सोमवार",)),
    (("tuesday", "tue", "tues", "mangalvar", "mangalwar"), ("मंगळवार", "मंगलवार")),
    (("wednesday", "wed", "budhvar", "budhwar"), ("बुधवार",)),
    (("thursday", "thu", "thurs", "guruvar", "guruwar", "brihaspativar"), ("गुरुवार",)),
    (("friday", "fri", "shukravar", "shukrawar"), ("शुक्रवार",)),
    (("saturday", "sat", "shanivar", "shaniwar"), ("शनिवार",)),
    (("sunday", "sun", "ravivar", "raviwar", "itvar"), ("रविवार",)),
)

# A part of the day, and the hour it means when no clock time is said.
_PARTS: Final[tuple[tuple[tuple[str, ...], tuple[str, ...], int], ...]] = (
    (("morning", "subah", "subha", "sakali"), ("सकाळी", "सुबह"), 10),
    (("afternoon", "dopahar", "dupari", "lunch"), ("दुपारी", "दोपहर"), 14),
    (("evening", "shaam", "sham", "sandhyakali"), ("संध्याकाळी", "शाम"), 18),
    (("night", "tonight", "raat", "ratri"), ("रात्री", "रात"), 20),
)

_LOCATION_WORDS: Final = (
    r"office|branch|site|showroom|cafe|café|hotel|mall|road|nagar|park|centre|center"
    r"|campus|clinic|hospital|school|college|station|home|house|flat|plot"
)
_LOCATION: Final = re.compile(
    rf"\b(?:at|in|near)\s+((?:[a-z0-9'&.-]+\s){{0,3}}(?:{_LOCATION_WORDS}))\b"
)
_LOCATION_DEVANAGARI: Final = re.compile(r"(\S+\s?(?:ऑफिस|कार्यालय|साइट))")

_CLOCK_COLON: Final = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(am|pm)?\b")
_CLOCK_AMPM: Final = re.compile(r"\b(\d{1,2})\s*(am|pm)\b")
_CLOCK_BAJE: Final = re.compile(r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:baje|bje|बजे|वाजता|वाजे)")
_CLOCK_AT: Final = re.compile(r"\b(?:at|by|@|around|till)\s+(\d{1,2})(?![\d:.])")
_RELATIVE: Final = re.compile(
    r"\b(?:in|after)\s+(\d{1,3})\s*(min|mins|minutes|minute|hr|hrs|hour|hours|day|days)\b"
    r"|\b(\d{1,3})\s*(ghante|ghanta|ghante\s+baad|din)\s*(?:baad|bad|mein|me)?\b"
)
_NEXT_WEEK: Final = re.compile(r"\bnext week\b|\bagle hafte\b|पुढच्या आठवड्यात")
_CLAUSES: Final = re.compile(
    r"[.;!?\n]+|,\s+(?=(?:and|aur|then|also)\b)|\b(?:and then|also|aur phir)\b|आणि नंतर"
)


def normalise(text: str) -> str:
    """Lower case, Devanagari digits as 0-9, spaces folded."""
    folded = text.translate(_DEVANAGARI_DIGITS).lower()
    return " ".join(folded.split())


def _has(text: str, latin: tuple[str, ...], devanagari: tuple[str, ...]) -> str | None:
    for word in latin:
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text):
            return word
    for word in devanagari:
        if word in text:
            return word
    return None


def kind_of(text: str) -> TaskKind | None:
    for kind in _KIND_ORDER:
        latin, devanagari = _KIND_CUES[kind]
        if _has(text, latin, devanagari):
            return kind
    return None


# ----- time -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _When:
    day_offset: int | None
    weekday: int | None
    clock: time | None
    part_hour: int | None
    relative: timedelta | None
    next_week: bool
    exact: bool  # a clock time was said


def _clock(text: str, part_hour: int | None) -> tuple[time | None, bool]:
    """The clock time said, if any, read as a promise: 1 to 7 without am or pm is the
    afternoon or evening; 8 to 11 is the morning unless the evening or night is said."""
    hour: int | None = None
    minute = 0
    meridiem: str | None = None
    found = _CLOCK_COLON.search(text)
    if found:
        hour, minute, meridiem = int(found.group(1)), int(found.group(2)), found.group(3)
    else:
        found = _CLOCK_AMPM.search(text)
        if found:
            hour, meridiem = int(found.group(1)), found.group(2)
        else:
            found = _CLOCK_BAJE.search(text)
            if found:
                hour = int(found.group(1))
                minute = int(found.group(2) or 0)
            else:
                found = _CLOCK_AT.search(text)
                if found:
                    hour = int(found.group(1))
    if hour is None or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None, False
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    elif meridiem is None and hour < 12:
        late = part_hour is not None and part_hour >= 14
        if late or 1 <= hour <= 7:
            hour += 12
    return time(hour % 24, minute), True


def _read_when(text: str) -> _When:
    day_offset: int | None = None
    for latin, devanagari, offset in _DAY_WORDS:
        if _has(text, latin, devanagari):
            day_offset = offset
            break
    weekday: int | None = None
    for index, (latin, devanagari) in enumerate(_WEEKDAYS):
        if _has(text, latin, devanagari):
            weekday = index
            break
    part_hour: int | None = None
    for latin, devanagari, hour in _PARTS:
        if _has(text, latin, devanagari):
            part_hour = hour
            break
    if _has(text, ("tonight",), ()):
        part_hour, day_offset = 20, 0
    relative: timedelta | None = None
    found = _RELATIVE.search(text)
    if found:
        amount = int(found.group(1) or found.group(3))
        unit = found.group(2) or found.group(4) or ""
        if unit.startswith(("min",)):
            relative = timedelta(minutes=amount)
        elif unit.startswith(("hr", "hour", "ghant")):
            relative = timedelta(hours=amount)
        else:
            relative = timedelta(days=amount)
    clock, exact = _clock(text, part_hour)
    return _When(
        day_offset=day_offset,
        weekday=weekday,
        clock=clock,
        part_hour=part_hour,
        relative=relative,
        next_week=bool(_NEXT_WEEK.search(text)),
        exact=exact,
    )


def _on(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=IST)


def default_due(kind: TaskKind, at: datetime) -> datetime:
    """When a task is due when nobody said (design, 2.4)."""
    local = at.astimezone(IST)
    if kind in ("call_back", "whatsapp", "send_file"):
        return local + timedelta(hours=1)
    if kind == "email":
        five = _on(local.date(), time(17, 0))
        return five if five > local else _on(local.date() + timedelta(days=1), time(17, 0))
    return _on(local.date() + timedelta(days=1), time(10, 0))


def resolve(when: _When, kind: TaskKind, at: datetime) -> tuple[datetime, bool]:
    """The moment a promise means, never before ``at``; and whether any time was said."""
    local = at.astimezone(IST)
    if when.relative is not None:
        return local + max(when.relative, timedelta(minutes=1)), True
    said = (
        when.clock is not None
        or when.part_hour is not None
        or when.day_offset is not None
        or when.weekday is not None
        or when.next_week
    )
    if not said:
        return default_due(kind, at), False
    clock = when.clock or (time(when.part_hour, 0) if when.part_hour is not None else time(10, 0))
    if when.weekday is not None:
        ahead = (when.weekday - local.weekday()) % 7 or 7
        if when.day_offset == 0 and when.weekday == local.weekday():
            ahead = 0
        moment = _on(local.date() + timedelta(days=ahead), clock)
    elif when.next_week:
        moment = _on(local.date() + timedelta(days=7), clock)
    elif when.day_offset is not None:
        moment = _on(local.date() + timedelta(days=when.day_offset), clock)
        if moment <= local:
            # "Today 4pm" said at 5pm: the next day at that time, never the past.
            moment = moment + timedelta(days=1)
    else:
        moment = _on(local.date(), clock)
        if moment <= local:
            moment = moment + timedelta(days=1)
    while moment <= local:
        moment = moment + timedelta(days=1)
    return moment, True


# ----- proposals --------------------------------------------------------------------------

_TITLES: Final[dict[TaskKind, str]] = {
    "call_back": "Call back {name}",
    "whatsapp": "WhatsApp {name}",
    "email": "Email {name}",
    "send_file": "Send the file to {name}",
    "meeting": "Meeting with {name}",
    "other": "Follow up with {name}",
}


def title_for(kind: TaskKind, name: str) -> str:
    who = " ".join(name.split()) or "the lead"
    return _TITLES[kind].format(name=who)


def _location(text: str) -> str | None:
    found = _LOCATION.search(text)
    if found:
        return found.group(1).strip().title()
    found = _LOCATION_DEVANAGARI.search(text)
    return found.group(1).strip() if found else None


def clauses(text: str) -> list[str]:
    parts = [part.strip(" ,") for part in _CLAUSES.split(text)]
    return [part for part in parts if part]


def propose(
    text: str,
    at: datetime,
    *,
    lead_name: str = "",
    after_call: bool = False,
    inside: Callable[[datetime], bool] | None = None,
) -> list[Proposal]:
    """The promises in a note, an after-call note or a message, as proposals.

    ``after_call``: a time said with no kind is a call back (the seller just spoke to
    them). ``inside``: whether the seller works at a moment (``hours.inside`` bound to
    the workspace's work hours), or None when none are set.
    """
    found: list[Proposal] = []
    for clause in clauses(normalise(text)):
        kind = kind_of(clause)
        when = _read_when(clause)
        timed = (
            when.clock is not None
            or when.part_hour is not None
            or when.relative is not None
            or when.day_offset is not None
            or when.weekday is not None
            or when.next_week
        )
        if kind is None:
            if not (timed and after_call):
                continue
            kind = "call_back"
            confidence = 0.5
        elif when.exact or when.relative is not None:
            confidence = 0.9
        elif timed:
            confidence = 0.75
        else:
            confidence = 0.6
        starts_at, _ = resolve(when, kind, at)
        ends_at = starts_at + MEETING_LENGTH if kind == "meeting" else None
        location = _location(clause) if kind == "meeting" else None
        found.append(
            Proposal(
                kind=kind,
                starts_at=starts_at,
                ends_at=ends_at,
                location=location,
                title=title_for(kind, lead_name),
                confidence=confidence,
                evidence=clause,
                outside_hours=inside is not None and not inside(starts_at),
            )
        )
    return merge(found)


def merge(proposals: list[Proposal]) -> list[Proposal]:
    """One proposal per promise: the same kind within 30 minutes is one, the surer wins."""
    kept: list[Proposal] = []
    for proposal in sorted(proposals, key=lambda item: -item.confidence):
        if any(
            other.kind == proposal.kind
            and abs(other.starts_at - proposal.starts_at) <= SAME_PROMISE
            for other in kept
        ):
            continue
        kept.append(proposal)
    return sorted(kept, key=lambda item: item.starts_at)
