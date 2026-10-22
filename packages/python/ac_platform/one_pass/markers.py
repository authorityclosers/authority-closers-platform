"""What identifies the one-pass C4 request (``one_pass.stage``), with no product imports,
so the provider adapters, the plan and the broker can recognise it without loading the
analysis."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Final
from zoneinfo import ZoneInfo

RECIPE: Final = "one-pass-facts-v1"
PROMPT_REVISION: Final = "one-pass-v1"
MARKER: Final = "FACT_OUTPUT: one-pass-facts-v1."
# Output bound of the one request (call data, notes and the review: 6.5-9.1k tokens on
# the 16 real calls, 21 Oct 2026; thinking counts inside it).
MAX_COMPLETION_TOKENS: Final = 20_000
# v2 (22 Oct 2026, built with the cost research session): the same request plus the Brain
# 4.0 18-skill part (one_pass.brain4_part). Its own recipe and marker, so the v1 prompt,
# schema and every sealed v1 configuration stay byte-identical; a v2 configuration needs
# its own Root seal (profiles gemini-one-pass-v2, -flex).
RECIPE_V2: Final = "one-pass-facts-v2"
PROMPT_REVISION_V2: Final = "one-pass-v2"
MARKER_V2: Final = "FACT_OUTPUT: one-pass-facts-v2."
RECIPES: Final = frozenset({RECIPE, RECIPE_V2})
PROMPT_REVISIONS: Final = frozenset({PROMPT_REVISION, PROMPT_REVISION_V2})
PROMPT_REVISION_BY_RECIPE: Final[Mapping[str, str]] = MappingProxyType(
    {RECIPE: PROMPT_REVISION, RECIPE_V2: PROMPT_REVISION_V2}
)
RECIPE_BY_PROMPT_REVISION: Final[Mapping[str, str]] = MappingProxyType(
    {PROMPT_REVISION: RECIPE, PROMPT_REVISION_V2: RECIPE_V2}
)
_MARKERS: Final = ((RECIPE, MARKER), (RECIPE_V2, MARKER_V2))
# Input bound: the whole call's transcript envelope, its instructions and schema.
MAX_INPUT_BYTES: Final = 512 * 1024
# The routes the request is implemented for: Gemini 3.8 Flash and GPT-6 Luna (the
# cheapest, cost research 21 Oct 2026), each standard or Flex.
ROUTES: Final = frozenset(
    {
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.8-flash:flex"),
        ("openai", "gpt-6-luna"),
        ("openai", "gpt-6-luna:flex"),
    }
)


IST: Final = ZoneInfo("Asia/Kolkata")


def recipe_of(system: object) -> str | None:
    """The one-pass recipe whose marker starts this system prompt, or None."""
    if not isinstance(system, str):
        return None
    return next((recipe for recipe, marker in _MARKERS if system.startswith(marker + "\n")), None)


def is_one_pass(system: object) -> bool:
    return recipe_of(system) is not None


def call_date(created_at: datetime) -> str:
    """The call's date as the call data instructions read it ("Tuesday 21 October 2026")."""
    return created_at.astimezone(IST).strftime("%A %d %B %Y")
