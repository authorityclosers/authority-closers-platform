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
        "release_sha": "0847db5d3ca1ed825b68c226713d0f52d11683b1",
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


def test_estimate_stays_unavailable_for_unknown_model_or_missing_units() -> None:
    unknown = estimate_provider_usage("gemini", "unknown-model", {"total_tokens": 10})
    missing_units = estimate_provider_usage("gemini", "gemini-3.8-flash", {"total_tokens": 10})

    assert unknown["paise"] is None
    assert unknown["state"] == "rate_unavailable"
    assert unknown["pricing_snapshot"] is None
    assert missing_units["paise"] is None
    assert missing_units["state"] == "usage_unavailable"
    assert missing_units["pricing_snapshot"]["currency"] == "INR"
