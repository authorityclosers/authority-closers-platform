from __future__ import annotations

from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage


def test_gemini_estimate_uses_receipt_tokens_and_release_snapshot() -> None:
    estimate = estimate_provider_usage(
        "gemini",
        "gemini-3.8-flash",
        {"promptTokenCount": 100, "candidatesTokenCount": 20},
    )

    assert estimate["paise"] == 2
    assert estimate["state"] == "available"
    assert estimate["pricing_snapshot"] == {
        "schema": "ac.sales-xray.pricing-snapshot/1",
        "evidence_release_sha": "0847db5d3ca1ed825b68c226713d0f52d11683b1",
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "currency": "INR",
        "usd_to_inr": 100,
        "source_date": "2026-09-14",
        "pricing_ref": "ref:pricing/gemini-38-intro-20260914",
        "evidence_sha256": "d2be76be50be45b17b66aa528eeff86806705bf9e90dce36772c715e3c312fde",
        "source_url": "https://ai.google.dev/gemini-api/docs/latest-model",
        "rate_basis": "per_million_tokens",
        "usd_per_hour": None,
        "input_usd_per_million_tokens": 0.75,
        "output_usd_per_million_tokens": 3.75,
        "is_billing_rate": False,
    }


def test_gemini_pro_estimate_uses_pinned_pricing_evidence() -> None:
    estimate = estimate_provider_usage(
        "gemini",
        "gemini-3.1-pro-preview",
        {"promptTokenCount": 1_000, "candidatesTokenCount": 200},
    )

    assert estimate["paise"] == 44
    assert estimate["state"] == "available"
    snapshot = estimate["pricing_snapshot"]
    assert snapshot["pricing_ref"] == "ref:pricing/gemini-31-pro-preview-20260914"
    assert (
        snapshot["evidence_sha256"]
        == "6adde7cf988414764bea2ce84160ef38afb91d95ba7ae2816433bf310cd1bb1d"
    )
    assert snapshot["input_usd_per_million_tokens"] == 2.0
    assert snapshot["output_usd_per_million_tokens"] == 12.0


def test_elevenlabs_estimate_uses_native_duration_and_hourly_snapshot() -> None:
    estimate = estimate_provider_usage(
        "elevenlabs",
        "scribe_v2",
        None,
        duration_ms=30 * 60 * 1000,
    )

    assert estimate["paise"] == 1_100
    assert estimate["state"] == "available"
    assert estimate["pricing_snapshot"]["rate_basis"] == "per_hour"
    assert estimate["pricing_snapshot"]["is_billing_rate"] is False


def test_deepgram_estimate_uses_native_duration_and_multilingual_snapshot() -> None:
    estimate = estimate_provider_usage(
        "deepgram",
        "nova-3",
        None,
        duration_ms=25_933,
    )

    assert estimate["paise"] == 23
    assert estimate["state"] == "available"
    assert estimate["basis"] == "native_duration_ms_x_approved_per_minute_rate"
    snapshot = estimate["pricing_snapshot"]
    assert snapshot["source_date"] == "2026-09-15"
    assert snapshot["evidence_release_sha"] == "724f3ab549e1837bc0f5ed49aa298d4fd0f308a1"
    assert snapshot["pricing_ref"] == "ref:pricing/deepgram-nova-3-multilingual-20260915"
    assert snapshot["rate_basis"] == "per_minute"
    assert snapshot["usd_per_minute"] == 0.0052
    assert snapshot["evidence_sha256"] == (
        "e4ac299a8e030cd9b6e22d517293fb979bf9bd8797f4d67faee86a28e3ffd1a7"
    )


def test_estimate_stays_unavailable_for_unknown_model_or_missing_units() -> None:
    unknown = estimate_provider_usage("gemini", "unknown-model", {"total_tokens": 10})
    missing_units = estimate_provider_usage("gemini", "gemini-3.8-flash", {"total_tokens": 10})

    assert unknown["paise"] is None
    assert unknown["state"] == "rate_unavailable"
    assert unknown["pricing_snapshot"] is None
    assert missing_units["paise"] is None
    assert missing_units["state"] == "usage_unavailable"
    assert missing_units["pricing_snapshot"]["currency"] == "INR"


def test_gemini_estimate_stays_unavailable_when_only_thought_tokens_exist() -> None:
    estimate = estimate_provider_usage(
        "gemini",
        "gemini-3.8-flash",
        {"thoughtsTokenCount": 20},
    )

    assert estimate["paise"] is None
    assert estimate["state"] == "usage_unavailable"


def test_openai_estimate_prices_disjoint_cache_buckets_and_not_reasoning_twice() -> None:
    estimate = estimate_provider_usage(
        "openai",
        "gpt-6-luna",
        {
            "input_tokens": 100_000,
            "cached_tokens": 20_000,
            "cache_write_tokens": 10_000,
            "output_tokens": 8_000,
            "reasoning_tokens": 3_000,
            "total_tokens": 108_000,
        },
    )

    assert estimate["state"] == "available"
    assert estimate["paise"] == 125
    assert estimate["usage_breakdown"] == {
        "input_tokens": 100_000,
        "ordinary_input_tokens": 70_000,
        "cached_tokens": 20_000,
        "cache_write_tokens": 10_000,
        "output_tokens": 8_000,
        "reasoning_tokens": 3_000,
    }
    assert estimate["pricing_snapshot"]["source_date"] == "2026-09-24"
    assert estimate["pricing_snapshot"]["evidence_sha256"]


def test_openai_long_context_uses_long_rate_and_missing_counters_are_not_zero() -> None:
    long_context = estimate_provider_usage(
        "openai",
        "gpt-6-luna",
        {
            "input_tokens": 272_001,
            "cached_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 272_001,
        },
    )
    missing_cache_detail = estimate_provider_usage(
        "openai",
        "gpt-6-luna",
        {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
    )
    malformed_cache_detail = estimate_provider_usage(
        "openai",
        "gpt-6-luna",
        {
            "input_tokens": 10,
            "cached_tokens": 8,
            "cache_write_tokens": 3,
            "output_tokens": 1,
            "reasoning_tokens": 0,
            "total_tokens": 11,
        },
    )

    assert long_context["basis"].endswith("_long_context")
    assert long_context["paise"] == 545
    assert missing_cache_detail["state"] == "usage_unavailable"
    assert malformed_cache_detail["state"] == "usage_invalid"
