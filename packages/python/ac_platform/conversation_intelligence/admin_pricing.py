"""Immutable, non-billing pricing snapshots for Admin usage estimates.

These snapshots mirror the exact release evidence used by the hosted activation
bundle.  They are deliberately planning rates: a provider receipt may include
usage counters, but settlement and invoice reconciliation remain canonical
budget-account transitions outside this read-only view.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any

_PAISE_PER_INR = Decimal("100")
_MILLION = Decimal("1000000")
_SNAPSHOT_SCHEMA = "ac.sales-xray.pricing-snapshot/1"
_EVIDENCE_RELEASE_SHA = "0847db5d3ca1ed825b68c226713d0f52d11683b1"
_SOURCE_DATE = "2026-09-14"
_FX_USD_TO_INR = Decimal("100")


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    provider_id: str
    model_id: str
    pricing_ref: str
    evidence_sha256: str
    source_url: str
    rate_basis: str
    evidence_release_sha: str | None = _EVIDENCE_RELEASE_SHA
    source_date: str = _SOURCE_DATE
    usd_per_hour: Decimal | None = None
    usd_per_minute: Decimal | None = None
    input_usd_per_million_tokens: Decimal | None = None
    output_usd_per_million_tokens: Decimal | None = None
    cached_input_usd_per_million_tokens: Decimal | None = None
    cache_write_usd_per_million_tokens: Decimal | None = None
    long_context_threshold_tokens: int | None = None
    long_input_usd_per_million_tokens: Decimal | None = None
    long_cached_input_usd_per_million_tokens: Decimal | None = None
    long_cache_write_usd_per_million_tokens: Decimal | None = None
    long_output_usd_per_million_tokens: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": _SNAPSHOT_SCHEMA,
            # This is the release that supplied the immutable pricing evidence;
            # it is not a claim about the release currently serving the API.
            "evidence_release_sha": self.evidence_release_sha,
            "provider": self.provider_id,
            "model": self.model_id,
            "currency": "INR",
            "usd_to_inr": int(_FX_USD_TO_INR),
            "source_date": self.source_date,
            "pricing_ref": self.pricing_ref,
            "evidence_sha256": self.evidence_sha256,
            "source_url": self.source_url,
            "rate_basis": self.rate_basis,
            "usd_per_hour": (None if self.usd_per_hour is None else float(self.usd_per_hour)),
            **(
                {}
                if self.usd_per_minute is None
                else {"usd_per_minute": float(self.usd_per_minute)}
            ),
            "input_usd_per_million_tokens": (
                None
                if self.input_usd_per_million_tokens is None
                else float(self.input_usd_per_million_tokens)
            ),
            "output_usd_per_million_tokens": (
                None
                if self.output_usd_per_million_tokens is None
                else float(self.output_usd_per_million_tokens)
            ),
            "cached_input_usd_per_million_tokens": (
                None
                if self.cached_input_usd_per_million_tokens is None
                else float(self.cached_input_usd_per_million_tokens)
            ),
            "cache_write_usd_per_million_tokens": (
                None
                if self.cache_write_usd_per_million_tokens is None
                else float(self.cache_write_usd_per_million_tokens)
            ),
            "long_context_threshold_tokens": self.long_context_threshold_tokens,
            "long_input_usd_per_million_tokens": (
                None
                if self.long_input_usd_per_million_tokens is None
                else float(self.long_input_usd_per_million_tokens)
            ),
            "long_cached_input_usd_per_million_tokens": (
                None
                if self.long_cached_input_usd_per_million_tokens is None
                else float(self.long_cached_input_usd_per_million_tokens)
            ),
            "long_cache_write_usd_per_million_tokens": (
                None
                if self.long_cache_write_usd_per_million_tokens is None
                else float(self.long_cache_write_usd_per_million_tokens)
            ),
            "long_output_usd_per_million_tokens": (
                None
                if self.long_output_usd_per_million_tokens is None
                else float(self.long_output_usd_per_million_tokens)
            ),
            "is_billing_rate": False,
        }


PRICING_SNAPSHOTS: dict[tuple[str, str], PricingSnapshot] = {
    ("elevenlabs", "scribe_v2"): PricingSnapshot(
        provider_id="elevenlabs",
        model_id="scribe_v2",
        pricing_ref="ref:pricing/elevenlabs-scribe-v2-20260914",
        evidence_sha256="294beecdac8d241c8fdee210eb8802e05f54a8369a748d90a0c823a10bae6448",
        source_url="https://elevenlabs.io/pricing/api",
        rate_basis="per_hour",
        usd_per_hour=Decimal("0.22"),
    ),
    ("deepgram", "nova-3"): PricingSnapshot(
        provider_id="deepgram",
        model_id="nova-3",
        pricing_ref="ref:pricing/deepgram-nova-3-multilingual-20260915",
        evidence_sha256="e4ac299a8e030cd9b6e22d517293fb979bf9bd8797f4d67faee86a28e3ffd1a7",
        source_url="https://deepgram.com/pricing",
        rate_basis="per_minute",
        evidence_release_sha="724f3ab549e1837bc0f5ed49aa298d4fd0f308a1",
        source_date="2026-09-15",
        usd_per_minute=Decimal("0.0052"),
    ),
    ("gemini", "gemini-3.8-flash"): PricingSnapshot(
        provider_id="gemini",
        model_id="gemini-3.8-flash",
        pricing_ref="ref:pricing/gemini-38-intro-20260914",
        evidence_sha256="d2be76be50be45b17b66aa528eeff86806705bf9e90dce36772c715e3c312fde",
        source_url="https://ai.google.dev/gemini-api/docs/latest-model",
        rate_basis="per_million_tokens",
        input_usd_per_million_tokens=Decimal("0.75"),
        output_usd_per_million_tokens=Decimal("3.75"),
    ),
    ("gemini", "gemini-3.1-pro-preview"): PricingSnapshot(
        provider_id="gemini",
        model_id="gemini-3.1-pro-preview",
        pricing_ref="ref:pricing/gemini-31-pro-preview-20260914",
        evidence_sha256="6adde7cf988414764bea2ce84160ef38afb91d95ba7ae2816433bf310cd1bb1d",
        source_url="https://ai.google.dev/gemini-api/docs/pricing#gemini-31-pro-preview",
        rate_basis="per_million_tokens",
        evidence_release_sha="33d81894488d812b2f09023e23e6b0bd706ca0e0",
        input_usd_per_million_tokens=Decimal("2"),
        output_usd_per_million_tokens=Decimal("12"),
    ),
}


def _openai_snapshot(model: str, rates: tuple[str, ...]) -> PricingSnapshot:
    (
        input_rate,
        cached_rate,
        write_rate,
        output_rate,
        long_input_rate,
        long_cached_rate,
        long_write_rate,
        long_output_rate,
    ) = rates
    fact_record = (
        f"OpenAI API pricing facts|2026-09-24|{model}|"
        + ",".join(rates)
        + "|long-context-threshold=272000"
    )
    return PricingSnapshot(
        provider_id="openai",
        model_id=model,
        pricing_ref=f"ref:pricing/openai-{model}-20260924",
        # Fingerprint of the normalized, dated fact record. The linked OpenAI
        # pricing page is the source; this is not a hash of its HTML bytes.
        evidence_sha256=hashlib.sha256(fact_record.encode("utf-8")).hexdigest(),
        source_url="https://developers.openai.com/api/docs/pricing",
        rate_basis="per_million_tokens_with_cache_categories_and_long_context_tier",
        evidence_release_sha=None,
        source_date="2026-09-24",
        input_usd_per_million_tokens=Decimal(input_rate),
        output_usd_per_million_tokens=Decimal(output_rate),
        cached_input_usd_per_million_tokens=Decimal(cached_rate),
        cache_write_usd_per_million_tokens=Decimal(write_rate),
        long_context_threshold_tokens=272_000,
        long_input_usd_per_million_tokens=Decimal(long_input_rate),
        long_cached_input_usd_per_million_tokens=Decimal(long_cached_rate),
        long_cache_write_usd_per_million_tokens=Decimal(long_write_rate),
        long_output_usd_per_million_tokens=Decimal(long_output_rate),
    )


PRICING_SNAPSHOTS.update(
    {
        ("openai", "gpt-6-luna"): _openai_snapshot(
            "gpt-6-luna", ("0.10", "0.01", "0.125", "0.50", "0.20", "0.02", "0.25", "0.75")
        ),
        ("openai", "gpt-6-sol"): _openai_snapshot(
            "gpt-6-sol", ("2", "0.20", "2.50", "10", "4", "0.40", "5", "15")
        ),
        ("openai", "gpt-6-astra"): _openai_snapshot(
            "gpt-6-astra", ("10", "1", "12.50", "50", "20", "2", "25", "75")
        ),
    }
)


def _ceil_paise(value: Decimal) -> int:
    return max(0, int(value.quantize(Decimal("1"), rounding=ROUND_CEILING)))


def _counter(usage: Mapping[str, Any] | None, *keys: str) -> int | None:
    if usage is None:
        return None
    for key in keys:
        value = usage.get(key)
        if type(value) is int and 0 <= value <= 1_000_000_000:
            return value
    return None


def estimate_provider_usage(
    provider_id: str | None,
    model_id: str | None,
    usage: Mapping[str, Any] | None,
    *,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Return a deterministic planning estimate, never a settlement amount."""

    snapshot = (
        None
        if provider_id is None or model_id is None
        else PRICING_SNAPSHOTS.get((provider_id, model_id))
    )
    if snapshot is None:
        return {
            "paise": None,
            "state": "rate_unavailable",
            "basis": None,
            "pricing_snapshot": None,
        }

    if snapshot.rate_basis in {"per_hour", "per_minute"}:
        if duration_ms is None or type(duration_ms) is not int or duration_ms <= 0:
            return {
                "paise": None,
                "state": "usage_unavailable",
                "basis": (
                    "native_duration_ms_x_approved_per_minute_rate"
                    if snapshot.rate_basis == "per_minute"
                    else "native_duration_ms_x_approved_hourly_rate"
                ),
                "pricing_snapshot": snapshot.as_dict(),
            }
        rate = (
            snapshot.usd_per_minute
            if snapshot.rate_basis == "per_minute"
            else snapshot.usd_per_hour
        )
        if rate is None:
            return {
                "paise": None,
                "state": "rate_unavailable",
                "basis": None,
                "pricing_snapshot": None,
            }
        duration_units = Decimal(duration_ms) / (
            Decimal(60_000) if snapshot.rate_basis == "per_minute" else Decimal(3_600_000)
        )
        paise = _ceil_paise(duration_units * rate * _FX_USD_TO_INR * _PAISE_PER_INR)
        return {
            "paise": paise,
            "state": "available",
            "basis": (
                "native_duration_ms_x_approved_per_minute_rate"
                if snapshot.rate_basis == "per_minute"
                else "native_duration_ms_x_approved_hourly_rate"
            ),
            "pricing_snapshot": snapshot.as_dict(),
        }

    input_tokens = _counter(usage, "promptTokenCount", "prompt_tokens", "input_tokens")
    output_tokens = _counter(usage, "candidatesTokenCount", "completion_tokens", "output_tokens")
    thoughts = _counter(usage, "thoughtsTokenCount", "thoughts_tokens")
    if provider_id != "openai" and output_tokens is not None and thoughts is not None:
        output_tokens += thoughts
    if input_tokens is None or output_tokens is None:
        return {
            "paise": None,
            "state": "usage_unavailable",
            "basis": "provider_input_and_output_tokens_x_approved_token_rates",
            "pricing_snapshot": snapshot.as_dict(),
        }
    if provider_id == "openai":
        total_tokens = _counter(usage, "total_tokens")
        cached_counter = _counter(usage, "cached_tokens")
        write_counter = _counter(usage, "cache_write_tokens")
        reasoning_counter = _counter(usage, "reasoning_tokens")
        if any(
            counter is None
            for counter in (total_tokens, cached_counter, write_counter, reasoning_counter)
        ):
            return {
                "paise": None,
                "state": "usage_unavailable",
                "basis": "provider_input_cache_and_output_tokens_x_approved_token_rates",
                "pricing_snapshot": snapshot.as_dict(),
            }
        if (
            total_tokens != input_tokens + output_tokens
            or cached_counter + write_counter > input_tokens
            or reasoning_counter > output_tokens
        ):
            return {
                "paise": None,
                "state": "usage_invalid",
                "basis": "provider_input_cache_and_output_tokens_x_approved_token_rates",
                "pricing_snapshot": snapshot.as_dict(),
            }
    input_rate = snapshot.input_usd_per_million_tokens
    output_rate = snapshot.output_usd_per_million_tokens
    if input_rate is None or output_rate is None:
        return {
            "paise": None,
            "state": "rate_unavailable",
            "basis": None,
            "pricing_snapshot": None,
        }
    cached_tokens = _counter(usage, "cached_tokens") or 0
    cache_write_tokens = _counter(usage, "cache_write_tokens") or 0
    if cached_tokens + cache_write_tokens > input_tokens:
        return {
            "paise": None,
            "state": "usage_invalid",
            "basis": "provider_input_cache_and_output_tokens_x_approved_token_rates",
            "pricing_snapshot": snapshot.as_dict(),
        }
    long_context = (
        snapshot.long_context_threshold_tokens is not None
        and input_tokens > snapshot.long_context_threshold_tokens
    )
    cached_rate = snapshot.cached_input_usd_per_million_tokens
    write_rate = snapshot.cache_write_usd_per_million_tokens
    if long_context:
        input_rate = snapshot.long_input_usd_per_million_tokens or input_rate
        cached_rate = snapshot.long_cached_input_usd_per_million_tokens
        write_rate = snapshot.long_cache_write_usd_per_million_tokens
        output_rate = snapshot.long_output_usd_per_million_tokens or output_rate
    if (cached_tokens and cached_rate is None) or (cache_write_tokens and write_rate is None):
        return {
            "paise": None,
            "state": "rate_unavailable",
            "basis": None,
            "pricing_snapshot": snapshot.as_dict(),
        }
    ordinary_input_tokens = input_tokens - cached_tokens - cache_write_tokens
    input_cost = Decimal(ordinary_input_tokens) * input_rate
    if cached_rate is not None:
        input_cost += Decimal(cached_tokens) * cached_rate
    if write_rate is not None:
        input_cost += Decimal(cache_write_tokens) * write_rate
    paise = _ceil_paise(
        input_cost * _FX_USD_TO_INR * _PAISE_PER_INR / _MILLION
        + Decimal(output_tokens) * output_rate * _FX_USD_TO_INR * _PAISE_PER_INR / _MILLION
    )
    return {
        "paise": paise,
        "state": "available",
        "basis": (
            "provider_input_cache_write_and_output_tokens_x_approved_token_rates"
            + ("_long_context" if long_context else "")
        ),
        "usage_breakdown": {
            "input_tokens": input_tokens,
            "ordinary_input_tokens": ordinary_input_tokens,
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
            "output_tokens": output_tokens,
            # OpenAI reasoning tokens are already included in output_tokens.
            "reasoning_tokens": _counter(usage, "reasoning_tokens"),
        },
        "pricing_snapshot": snapshot.as_dict(),
    }


__all__ = ["PRICING_SNAPSHOTS", "PricingSnapshot", "estimate_provider_usage"]
