"""What identifies the one-pass C4 request (``one_pass.stage``), with no product imports,
so the provider adapters, the plan and the broker can recognise it without loading the
analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

RECIPE: Final = "one-pass-facts-v1"
PROMPT_REVISION: Final = "one-pass-v1"
MARKER: Final = "FACT_OUTPUT: one-pass-facts-v1."
# Output bound of the one request (call data, notes and the review: 6.5-9.1k tokens on
# the 16 real calls, 21 Oct 2026; thinking counts inside it).
MAX_COMPLETION_TOKENS: Final = 20_000
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


def is_one_pass(system: object) -> bool:
    return isinstance(system, str) and system.startswith(MARKER + "\n")


def call_date(created_at: datetime) -> str:
    """The call's date as the call data instructions read it ("Tuesday 21 October 2026")."""
    return created_at.astimezone(IST).strftime("%A %d %B %Y")
