"""Gemini's Flex tier as its own approved route.

Owner, 21 Oct 2026 ("So at least get this on prod now!!!"); the ₹0.28/min the owner saw is
mostly Flex: the same models at half price, best effort. A route on Flex is a separate
model id with the ``:flex`` suffix (``gemini-3.1-flash-lite:flex``,
``gemini-3.8-flash:flex``): it is configured, sealed and activated like any route, so the
owner's switch to it is audited, and switching back is the classic one click.

Same model, same prompt, same answer contract: only the request carries
``service_tier: flex``. Flex may queue; after ``FLEX_WINDOW_SECONDS`` without an answer,
or a busy answer (429/503), the request goes once more on standard (billed at standard,
and recorded on the receipt), so a person never waits much longer than five minutes.
"""

from __future__ import annotations

from typing import Final

FLEX_SUFFIX: Final = ":flex"
FLEX_WINDOW_SECONDS: Final = 300
# A busy Flex answer (or a lost answer) goes once more on standard.
FLEX_RETRY_STATUSES: Final = frozenset({429, 500, 502, 503, 504})
# Receipt usage counters (integers only): Flex asked, and Flex fell back to standard.
FLEX_USAGE: Final = "serviceTierFlex"
FALLBACK_USAGE: Final = "flexFellBack"


def base_model(model: str) -> str:
    """The provider's own model id (Flex is a request option, not a model)."""
    return model[: -len(FLEX_SUFFIX)] if model.endswith(FLEX_SUFFIX) else model


def is_flex(model: str) -> bool:
    return model.endswith(FLEX_SUFFIX)


def flex(model: str) -> str:
    return model if is_flex(model) else model + FLEX_SUFFIX
