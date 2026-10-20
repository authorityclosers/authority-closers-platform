"""The canary's provider probe: one tiny request, status codes and token counts only.

No network: the HTTPS connection and the infisical child are local fakes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ac_platform.ai_spend import probe_cli


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.body = status, body

    def read(self, _: int) -> bytes:
        return json.dumps(self.body).encode()


class FakeConnection:
    requests: list[tuple[str, str, dict[str, str]]] = []

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.response = FakeResponse(status, body)

    def request(self, method: str, path: str, body: str | None = None, headers: Any = None) -> None:
        FakeConnection.requests.append((method, path, dict(headers or {})))
        if body is not None:
            sent = json.loads(body)
            assert sent["generationConfig"]["maxOutputTokens"] == probe_cli.MAX_OUTPUT_TOKENS
            assert sent["contents"][0]["parts"][0]["text"] == probe_cli.PROMPT

    def getresponse(self) -> FakeResponse:
        return self.response

    def close(self) -> None:
        pass


def _serve(monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, Any]) -> None:
    FakeConnection.requests = []
    monkeypatch.setattr(probe_cli, "_connection", lambda host: FakeConnection(status, body))


def test_gemini_probe_costs_about_a_paisa(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, 200, {"usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 1}})
    record = probe_cli.probe_gemini("gemini-3.8-flash", "test-key")
    assert record == {
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "http_status": 200,
        "tokens": [9, 1],
        "cost_paise": 1,
        "ok": True,
    }
    method, path, headers = FakeConnection.requests[0]
    assert (method, path) == ("POST", "/v1beta/models/gemini-3.8-flash:generateContent")
    assert headers["x-goog-api-key"] == "test-key"


def test_used_up_credit_fails_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, 402, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    record = probe_cli.probe_gemini("gemini-3.8-flash", "test-key")
    assert record["ok"] is False and record["http_status"] == 402
    assert set(record) == {"provider", "model", "http_status", "ok"}  # no body kept


def test_elevenlabs_reads_the_free_subscription_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, 200, {"status": "active", "character_count": 5})
    record = probe_cli.probe_elevenlabs("test-key")
    assert record == {
        "provider": "elevenlabs",
        "http_status": 200,
        "status": "active",
        "ok": True,
        "cost_paise": 0,
    }
    assert FakeConnection.requests[0][:2] == ("GET", "/v1/user/subscription")


def _arguments(tmp_path: Path) -> Any:
    config = tmp_path / "service.json"
    config.write_text(
        json.dumps(
            {
                "environment": "staging",
                "providers": [
                    {
                        "provider_id": name,
                        "executable": "/opt/infisical",
                        "project_ref": "p",
                        "environment_ref": "staging",
                        "secret_path_ref": f"/sales-xray/{name}",
                        "token_file_ref": str(tmp_path / f"{name}.token"),
                    }
                    for name in ("gemini", "elevenlabs")
                ],
            }
        )
    )
    argv = ["--service-config", str(config), "--environment", "staging"]
    return probe_cli._arguments(argv), argv


def test_probe_record_matches_the_canary_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    arguments, argv = _arguments(tmp_path)
    seen: list[str] = []

    def child(provider: dict[str, Any], _: list[str]) -> dict[str, Any]:
        seen.append(provider["secret_path_ref"])
        ok = provider["provider_id"] == "elevenlabs"
        return {"provider": provider["provider_id"], "ok": ok, "http_status": 200 if ok else 402}

    monkeypatch.setattr(probe_cli, "_child", child)
    result = probe_cli.probe(arguments, argv)
    assert seen == ["/sales-xray/gemini", "/sales-xray/elevenlabs"]
    assert result["ok"] is False
    assert result["mode"] == "probe" and result["stage_reached"] == "probe"
    assert result["failure_code"] == "probe_gemini_http_402"
    assert result["report_present"] is False


def test_child_needs_its_identity_and_never_passes_a_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    arguments, argv = _arguments(tmp_path)
    provider = json.loads(arguments.service_config.read_text())["providers"][0]
    assert probe_cli._child(provider, argv) == {
        "provider": "gemini",
        "ok": False,
        "error": "identity_unreadable",
    }
    Path(provider["token_file_ref"]).write_text("INFISICAL_TOKEN=identity-token\n")
    captured: dict[str, Any] = {}

    class Done:
        stdout = '{"provider": "gemini", "ok": true}\n'

    def run(command: list[str], **options: Any) -> Done:
        captured.update(command=command, env=options["env"])
        return Done()

    monkeypatch.setenv("GEMINI_API_KEY", "must-not-pass")
    monkeypatch.setattr(probe_cli.subprocess, "run", run)
    assert probe_cli._child(provider, argv) == {"provider": "gemini", "ok": True}
    assert captured["env"]["INFISICAL_TOKEN"] == "identity-token"  # noqa: S105 - fake
    assert "GEMINI_API_KEY" not in captured["env"]
    command = captured["command"]
    assert command[:2] == ["/opt/infisical", "run"]
    assert command[command.index("--path") + 1] == "/sales-xray/gemini"
    assert command[-3:] == ["--provider", "gemini", probe_cli.INNER]


def test_inner_without_a_key_says_so(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    arguments, argv = _arguments(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    inner = probe_cli._arguments([*argv, "--provider", "gemini", probe_cli.INNER])
    assert probe_cli._inner(inner) == {
        "provider": "gemini",
        "ok": False,
        "error": "credential_missing",
    }
