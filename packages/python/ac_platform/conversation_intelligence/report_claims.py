"""Reject explicit unapproved score and financial-projection prose.

This is a deterministic backstop for known claim forms, not a factual-quality
judge. Native source quotes remain verbatim and are validated by the report
parser. Qualitative interpretations still require source and human review.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

_SCORE = re.compile(
    r"(?:\b(?:scores?|scored|ratings?|rated|grades?|marks?|points?)\b|स्कोर|रेटिंग|अंक|गुण)"
    r"\s*(?:(?:is|of|was|at|है|हैं|आहे)\s*|[:=–—-]\s*){0,3}[+−-]?\d",
    re.IGNORECASE,
)
_PROJECTION = (
    r"(?:projected|potential|estimated|additional|expected|lost|recoverable|forecast|increase|boost|"
    r"आंदाजे|अनुमानित|संभावित|अपेक्षित|अतिरिक्त)"
)
_FINANCIAL = r"(?:revenue|income|profit|earnings|loss|राजस्व|कमाई|महसूल|आमदनी|नफा|नुकसान)"
_FINANCIAL_PROJECTION = re.compile(
    rf"{_PROJECTION}[^\n.!?]{{0,32}}{_FINANCIAL}[^\n.!?]{{0,32}}\d"
    rf"|{_FINANCIAL}[^\n.!?]{{0,32}}{_PROJECTION}[^\n.!?]{{0,32}}\d"
    rf"|(?:₹|\$|€|£|INR\s*|Rs\.?\s*)\d[^\n.!?]{{0,32}}{_PROJECTION}[^\n.!?]{{0,32}}{_FINANCIAL}",
    re.IGNORECASE,
)
_SOURCE_FIELDS = frozenset(
    {"quote", "segment_id", "source_label", "source_sha256", "transcript_revision"}
)


def require_qualitative_claims(value: Any) -> None:
    """Fail with a content-free error; never redact or rewrite quoted evidence."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key not in _SOURCE_FIELDS:
                require_qualitative_claims(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            require_qualitative_claims(child)
    elif isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value)
        if _SCORE.search(normalized) or _FINANCIAL_PROJECTION.search(normalized):
            raise ValueError("report_unapproved_numeric_claim")
