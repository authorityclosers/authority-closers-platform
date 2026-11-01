"""The 19:00 capture reminder's words, and how the bell shows it.

One card, one truth (orchestrator, 31 Oct 2026): the live "N calls not recorded" corner card
(capture-setup/recording-check.tsx, off Home, from Home's own calls) is the one that pops up.
This reminder stays in the bell, never a pop-up, and names its own day, so an unread one from
yesterday never says "today". Rows written before this rule (urgent, "N calls today have no
recording: fix") read the same way; nothing stored changes.
"""

from __future__ import annotations

import re
from datetime import date
from uuid import UUID

KEY = "capture-missing:"
# The words before the rule; a dated title is left as it is.
OLD = re.compile(r"(\d+) calls? today ha(?:s|ve) no recording")


def reminder_key(tenant: UUID, day: date) -> str:
    """One reminder per seller and India day (the bell ledger dedupes on it)."""
    return f"{KEY}{tenant}:{day.isoformat()}"


def words(count: int, day: date) -> tuple[str, str]:
    noun = "call" if count == 1 else "calls"
    return (
        f"{day.day} {day:%b}: {count} {noun} had no recording",
        "Pick the missing recordings from your files, or check Calls setup "
        "so the next call is captured.",
    )


def calls_href(day: date) -> str:
    """Calls, opened at that day's calls without a recording and their fix (ph1-27)."""
    return f"/analysis/calls?no-recording={day.isoformat()}"


def as_bell(
    dedupe_key: str | None, title: str, urgent: bool, href: str | None = None
) -> tuple[str, bool, str | None]:
    """The bell's title, urgency and link for a stored notification: a capture reminder is
    never urgent (urgent ones pop up), always names its own day, and its See why opens
    that day's calls without a recording (phone personas ph1-27, 1 Nov 2026: it went to
    Settings, which looked like it did nothing)."""
    if not dedupe_key or not dedupe_key.startswith(KEY):
        return title, urgent, href
    try:
        day = date.fromisoformat(dedupe_key.rsplit(":", 1)[-1])
    except ValueError:
        return title, False, href
    old = OLD.match(title)
    return (words(int(old.group(1)), day)[0] if old else title), False, calls_href(day)
