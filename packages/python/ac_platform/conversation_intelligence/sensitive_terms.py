"""ETH-03 legal-exposure candidates; never scores, marks or returns transcript text.

The profile follows protocol-v1 ETH-03, narrowed by AUT-557/AUT-519 to exclude
BIZ-03 figures. Patterns use the same NFKC/casefold tokens as the withheld guard,
including its Devanagari token boundaries. Matching is pure after profile loading.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from ac_platform.conversation_intelligence.sensitive_segments import tokens

PROFILE = json.loads(
    (Path(__file__).parent / "profiles" / "sensitive_terms_v1.json").read_text(encoding="utf-8")
)
VERSION: str = PROFILE["version"]
RULES = tuple(
    (rule["rule_id"], rule["category"], tuple(tuple(tokens(p)) for p in rule["patterns"]))
    for rule in PROFILE["rules"]
)


def detect_sensitive_terms(segments: Iterable[tuple[str, str]]) -> tuple[tuple[str, str, str], ...]:
    """One (segment_id, category, rule_id) hit per matching rule, in input order.

    Literal, contiguous word patterns only: no digit, magnitude or neighbour rule.
    Candidates require operator review; absence of a hit is not a safety clearance.
    """
    hits: list[tuple[str, str, str]] = []
    for segment_id, text in segments:
        words = tuple(tokens(text))
        for rule_id, category, patterns in RULES:
            if any(
                words[i : i + len(pattern)] == pattern
                for pattern in patterns
                for i in range(len(words) - len(pattern) + 1)
            ):
                hits.append((segment_id, category, rule_id))
    return tuple(hits)
