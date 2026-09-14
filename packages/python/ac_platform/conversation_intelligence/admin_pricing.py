"""Immutable, non-billing pricing snapshots for Admin usage estimates.

These snapshots mirror the exact release evidence used by the hosted activation
bundle.  They are deliberately planning rates: a provider receipt may include
usage counters, but settlement and invoice reconciliation remain canonical
budget-account transitions outside this read-only view.
"""

from __future__ import annotations

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
    usd_per_hour: Decimal | None = None
    input_usd_per_million_tokens: Decimal | None = None
    output_usd_per_million_tokens: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": _SNAPSHOT_SCHEMA,
            # This is the release that supplied the immutable pricing evidence;
            # it is not a claim about the release currently serving the API.
            "evidence_release_sha": _EVIDENCE_RELEASE_SHA,
            "provider": self.provider_id,
            "model": self.model_id,
            "currency": "INR",
            "usd_to_inr": int(_FX_USD_TO_INR),
            "source_date": _SOURCE_DATE,
            "pricing_ref": self.pricing_ref,
            "evidence_sha256": self.evidence_sha256,
            "source_url": self.source_url,
            "rate_basis": self.rate_basis,
            "usd_per_hour": (None if self.usd_per_hour is None else float(self.usd_per_hour)),
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
}


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

    if snapshot.rate_basis == "per_hour":
        if duration_ms is None or type(duration_ms) is not int or duration_ms <= 0:
            return {
                "paise": None,
                "state": "usage_unavailable",
                "basis": "native_duration_ms_x_approved_hourly_rate",
                "pricing_snapshot": snapshot.as_dict(),
            }
        hourly_rate = snapshot.usd_per_hour
        if hourly_rate is None:
            return {
                "paise": None,
                "state": "rate_unavailable",
                "basis": None,
                "pricing_snapshot": None,
            }
        hours = Decimal(duration_ms) / Decimal(3_600_000)
        paise = _ceil_paise(hours * hourly_rate * _FX_USD_TO_INR * _PAISE_PER_INR)
        return {
            "paise": paise,
            "state": "available",
            "basis": "native_duration_ms_x_approved_hourly_rate",
            "pricing_snapshot": snapshot.as_dict(),
        }

    input_tokens = _counter(usage, "promptTokenCount", "prompt_tokens", "input_tokens")
    output_tokens = _counter(usage, "candidatesTokenCount", "completion_tokens", "output_tokens")
    thoughts = _counter(usage, "thoughtsTokenCount", "thoughts_tokens")
    if output_tokens is not None and thoughts is not None:
        output_tokens += thoughts
    if input_tokens is None or output_tokens is None:
        return {
            "paise": None,
            "state": "usage_unavailable",
            "basis": "provider_input_and_output_tokens_x_approved_token_rates",
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
    paise = _ceil_paise(
        Decimal(input_tokens) * input_rate * _FX_USD_TO_INR * _PAISE_PER_INR / _MILLION
        + Decimal(output_tokens) * output_rate * _FX_USD_TO_INR * _PAISE_PER_INR / _MILLION
    )
    return {
        "paise": paise,
        "state": "available",
        "basis": "provider_input_and_output_tokens_x_approved_token_rates",
        "pricing_snapshot": snapshot.as_dict(),
    }


__all__ = ["PRICING_SNAPSHOTS", "PricingSnapshot", "estimate_provider_usage"]
