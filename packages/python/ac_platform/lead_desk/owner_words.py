"""Who a lead is with, in plain words, for a notification (persona QA, 31 Oct 2026: the
bell said "(fewest)", the lead rules' own shorthand).

The lead rules keep a short note when they pick an owner (``allocation.py``), and leads keep
that note. This says it for a person the way the web's ``owner-words.ts`` does: to the seller
themselves ("you") in their bell, or about them ("they") elsewhere. Notes that already read
well pass through as they are.
"""

from __future__ import annotations

import re
from typing import Final

_VERB: Final = {"speaks": "speak", "covers": "cover", "sells": "sell"}
_MOVED: Final = re.compile(r"^Moved by (.+?)\.?$")
_GAP: Final = re.compile(r"^Nobody free speaks (.+?); \d+ open leads?, the fewest\.?$", re.I)
_RULES: Final = re.compile(r"^(.*?)(?:,\s*)?\d+ open leads?( \(fewest\))?\.?$", re.I)
_LATE: Final = re.compile(r"^No call in (\d+) minutes?\.\s*", re.I)


def _joined(parts: list[str]) -> str:
    if len(parts) < 2:
        return parts[0] if parts else ""
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _reword(text: str, who: str) -> str:
    moved = _MOVED.match(text)
    if moved:
        return f"Reassigned by {moved.group(1)}."
    gap = _GAP.match(text)
    if gap:
        return (
            f"Picked automatically: nobody free speaks {gap.group(1)}, so it went to whoever "
            "had the fewest open leads."
        )
    rules = _RULES.match(text)
    if not rules:
        return text
    clauses = [
        part.strip()[:1].lower() + part.strip()[1:]
        for part in re.split(r",\s*", rules.group(1))
        if part.strip()
    ]
    relaxed = [part for part in clauses if part.startswith("nobody free")]
    fits = [
        re.sub(r"^(\w+)", lambda verb: _VERB.get(verb.group(1), verb.group(1)), part)
        for part in clauses
        if not part.startswith("nobody free")
    ]
    fits.append(
        "had the fewest open leads" if rules.group(2) else "were the only seller who could take it"
    )
    sentence = f"Picked automatically because {who} {_joined(fits)}."
    if relaxed:
        rest = _joined(relaxed)
        sentence += f" {rest[:1].upper()}{rest[1:]}."
    return sentence


def note(reason: str | None, *, you: bool = False) -> str | None:
    """The lead rules' note, reworded for a person; None when there is none."""
    text = (reason or "").strip()
    if not text:
        return None
    late = _LATE.match(text)
    rest = text[late.end() :] if late else text
    parts = [
        f"Moved on after {late.group(1)} min with no call." if late else "",
        _reword(rest, "you" if you else "they") if rest else "",
    ]
    return " ".join(part for part in parts if part) or None
