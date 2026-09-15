"""The bounded connectivity check must observe a final answer, not HTTP alone."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ac_platform.conversation_intelligence import inference_smoke
from ac_platform.conversation_intelligence.checkpoints import content_hash


@pytest.mark.parametrize(
    ("parts", "finish", "expected"),
    [
        ([{"text": "READY"}], "STOP", True),
        ([], "MAX_TOKENS", False),
        ([{"text": "READY", "thought": True}], "MAX_TOKENS", False),
    ],
)
def test_gemini_smoke_requires_final_answer_and_preserves_bound_quote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    parts: list[dict[str, object]],
    finish: str,
    expected: bool,
) -> None:
    directory = tmp_path / "private-smoke"
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke", "--model", "gemini-3.8-flash", "--private-receipt-directory", str(directory)],
    )
    monkeypatch.setenv("GEMINI_API_KEY", "unit-placeholder")

    class Provider:
        def __init__(self, *, credentials, authorize):
            self.authorize = authorize
            assert credentials == {"gemini": "unit-placeholder"}

        def generate(self, reservation, body):
            self.authorize(reservation)
            assert reservation.quote.input_sha256 == content_hash(body)
            assert reservation.quote.max_cost_paise == 0
            assert body["generationConfig"]["maxOutputTokens"] == 256
            assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}
            return SimpleNamespace(
                data={"candidates": [{"content": {"parts": parts}, "finishReason": finish}]},
                usage={"promptTokenCount": 10, "totalTokenCount": 30},
                response_sha256="a" * 64,
            )

    monkeypatch.setattr(inference_smoke, "BoundedProviders", Provider)
    inference_smoke.main()
    result = json.loads(capsys.readouterr().out)
    assert result["generation_worked"] is expected
    assert result["finish_reason"] == finish
    events = [
        json.loads(line) for line in (directory / "inference-smoke.jsonl").read_text().splitlines()
    ]
    assert [entry["event"] for entry in events] == ["reserved", "in_flight", "response"]
    assert result["requests"] == 1
    assert result["max_output_tokens"] == 256
    assert result["customer_recording_bytes"] == 0
