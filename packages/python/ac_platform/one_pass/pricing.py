"""List-price estimates for the one-pass pipeline (never a charge, never on a user screen).

Google AI Studio paid-tier list prices, US dollars per million tokens, read 20 Oct 2026
from https://ai.google.dev/gemini-api/docs/pricing by the cost research:

| model | text in | audio in | output (incl. thinking) |
|---|---|---|---|
| gemini-3.1-flash-lite | 0.25 | 0.50 | 1.50 |
| gemini-3.8-flash | 0.75 | 0.75 | 3.75 (both double on 1 Jan 2027) |

Cached input is 10% of the input price. Flex is half of every rate. Rupees use the price
sheet's one planning rate (``admin_pricing.FX_USD_TO_INR``), as every Admin cost does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from ac_platform.conversation_intelligence.admin_pricing import FX_USD_TO_INR

SOURCE: Final = "https://ai.google.dev/gemini-api/docs/pricing (read 2026-10-20)"
MILLION: Final = Decimal(1_000_000)
CACHED_SHARE: Final = Decimal("0.10")
FLEX_SHARE: Final = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class Rates:
    text_in: Decimal
    audio_in: Decimal
    output: Decimal


RATES: Final[dict[str, Rates]] = {
    "gemini-3.1-flash-lite": Rates(Decimal("0.25"), Decimal("0.50"), Decimal("1.50")),
    "gemini-3.8-flash": Rates(Decimal("0.75"), Decimal("0.75"), Decimal("3.75")),
}


@dataclass(frozen=True, slots=True)
class Usage:
    """One request's counted tokens, from the provider's own usage report."""

    prompt: int = 0  # every input token, audio and cached included
    audio: int = 0  # the audio share of ``prompt``
    cached: int = 0  # the cached share of ``prompt``
    output: int = 0  # answer tokens
    thoughts: int = 0  # thinking tokens, billed as output

    @property
    def billed_output(self) -> int:
        return self.output + self.thoughts

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt": self.prompt,
            "audio": self.audio,
            "cached": self.cached,
            "output": self.output,
            "thoughts": self.thoughts,
        }

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt + other.prompt,
            self.audio + other.audio,
            self.cached + other.cached,
            self.output + other.output,
            self.thoughts + other.thoughts,
        )


def _count(value: Any) -> int:
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else 0


def usage_from_gemini(metadata: Mapping[str, Any] | None) -> Usage:
    """Gemini's ``usageMetadata``; anything missing or malformed counts as zero."""
    if not isinstance(metadata, Mapping):
        return Usage()
    audio = 0
    for detail in metadata.get("promptTokensDetails") or []:
        if isinstance(detail, Mapping) and detail.get("modality") == "AUDIO":
            audio += _count(detail.get("tokenCount"))
    prompt = _count(metadata.get("promptTokenCount"))
    return Usage(
        prompt=prompt,
        audio=min(audio, prompt),
        cached=min(_count(metadata.get("cachedContentTokenCount")), prompt),
        output=_count(metadata.get("candidatesTokenCount")),
        thoughts=_count(metadata.get("thoughtsTokenCount")),
    )


def usage_from_openrouter(usage: Mapping[str, Any] | None) -> Usage:
    """OpenRouter's chat ``usage`` (benchmark route only); reasoning is inside completion."""
    if not isinstance(usage, Mapping):
        return Usage()
    details = usage.get("prompt_tokens_details")
    details = details if isinstance(details, Mapping) else {}
    prompt = _count(usage.get("prompt_tokens"))
    return Usage(
        prompt=prompt,
        audio=min(_count(details.get("audio_tokens")), prompt),
        cached=min(_count(details.get("cached_tokens")), prompt),
        output=_count(usage.get("completion_tokens")),
    )


def cost_usd(model: str, usage: Usage, *, tier: str) -> Decimal:
    """List-price dollars; a model without rates is priced as Gemini 3.8 Flash, so it never
    reads as free."""
    rates = RATES.get(model, RATES["gemini-3.8-flash"])
    uncached = max(0, usage.prompt - usage.cached)
    audio = min(usage.audio, uncached)
    text_in = uncached - audio
    dollars = (
        Decimal(text_in) * rates.text_in
        + Decimal(audio) * rates.audio_in
        + Decimal(usage.cached) * rates.text_in * CACHED_SHARE
        + Decimal(usage.billed_output) * rates.output
    ) / MILLION
    if tier == "flex":
        dollars *= FLEX_SHARE
    return dollars


def cost_inr(model: str, usage: Usage, *, tier: str) -> Decimal:
    return (cost_usd(model, usage, tier=tier) * FX_USD_TO_INR).quantize(Decimal("0.0001"))


def per_minute(inr: Decimal | float | None, audio_ms: int | None) -> float | None:
    if inr is None or not audio_ms:
        return None
    return round(float(inr) / (audio_ms / 60_000), 4)
