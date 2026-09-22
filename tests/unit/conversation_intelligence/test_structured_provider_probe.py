import json
import sys

import pytest

from ac_platform.conversation_intelligence import inference_smoke
from ac_platform.conversation_intelligence.admin_pricing import estimate_provider_usage
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.providers import ProviderError


def test_fixed_probe_fits_one_rupee_conservative_envelope():
    body = inference_smoke.structured_probe_body()
    estimate = estimate_provider_usage(
        "gemini",
        "gemini-3.8-flash",
        {"promptTokenCount": len(canonical(body)) + 128, "candidatesTokenCount": 256},
    )
    assert estimate["paise"] <= 100
    assert body["generationConfig"]["maxOutputTokens"] == 256


def test_probe_reserves_before_one_dispatch_and_never_retries(tmp_path, monkeypatch, capsys):
    receipt = tmp_path / "probe"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--private-receipt-directory",
            str(receipt),
            "--structured-coaching-probe",
            "--paid-approval-ref",
            "ref:approval/owner-recovery-testing-inr1000-20260922",
        ],
    )
    calls = []

    class Provider:
        def __init__(self, **kwargs):
            self.authorize = kwargs["authorize"]

        def generate(self, reservation, body):
            journal = [
                json.loads(row)
                for row in (receipt / "inference-smoke.jsonl").read_text().splitlines()
            ]
            assert [row["event"] for row in journal] == ["reserved", "in_flight"]
            assert reservation.quote.max_cost_paise == 100
            assert reservation.state == "in_flight"
            self.authorize(reservation)
            calls.append(body)
            error = ProviderError("provider_http_400")
            error.diagnostic = "structured_schema_complexity"
            raise error

    monkeypatch.setattr(inference_smoke, "BoundedProviders", Provider)
    inference_smoke.main()
    result = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    assert result["max_paid_paise"] == 100
    assert result["customer_recording_bytes"] == 0
    assert result["report_quality_test"] is False
    assert result["diagnostic"] == "structured_schema_complexity"
    with pytest.raises(FileExistsError):
        inference_smoke.main()
    assert len(calls) == 1


@pytest.mark.parametrize("extra", [[], ["--paid-approval-ref", "unapproved"]])
def test_probe_refuses_missing_or_different_approval(tmp_path, monkeypatch, extra):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe",
            "--private-receipt-directory",
            str(tmp_path / "probe"),
            "--structured-coaching-probe",
            *extra,
        ],
    )
    with pytest.raises(SystemExit):
        inference_smoke.main()
    assert not (tmp_path / "probe").exists()
