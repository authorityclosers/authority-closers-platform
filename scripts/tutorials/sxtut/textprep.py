"""Script text rules: what the voice says versus what the captions show, and the words a tutorial may not use.

- `spoken(text, lang)` applies scripts/tutorials/pronounce.json so product names are read the way the team says them
  ("Brain 4.0" -> "Brain four point oh") while captions keep the written form.
- `lint(text)` refuses prices, costs, minutes, phone numbers and e-mail addresses (owner rules: never show prices,
  costs or minutes; no real customer names or numbers in tutorials).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PRONOUNCE = HERE / "pronounce.json"

# Owner rules, 23 Oct 2026: tutorials never mention prices, costs or minutes, and never carry a real number.
BANNED = [
    (re.compile(r"[₹$€£]|\b(?:rs\.?|inr|rupees?|paise|price|pricing|cost|costs|credits?)\b", re.I), "price or cost"),
    (re.compile(r"\b(?:minutes?|mins?)\b|मिनिट|मिनट", re.I), "minutes"),
    (re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b"), "phone number"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "e-mail address"),
]


def load_pronounce(path: Path = PRONOUNCE) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {term: dict(rule["say"]) for term, rule in data["terms"].items()}


def spoken(text: str, lang: str, rules: dict[str, dict[str, str]] | None = None) -> str:
    """The text sent to the voice: product terms replaced by how they are said in `lang`."""
    rules = load_pronounce() if rules is None else rules
    out = text
    # Longest term first, so "Sales X-Ray" wins over "X-Ray".
    for term in sorted(rules, key=len, reverse=True):
        say = rules[term].get(lang) or rules[term].get("default")
        if say and say != term:
            out = out.replace(term, say)
    return out


def lint(text: str) -> list[str]:
    """Owner-rule problems in one script line; empty when it may be used."""
    return [f"{label}: {m.group(0)!r}" for rx, label in BANNED for m in rx.finditer(text)]
