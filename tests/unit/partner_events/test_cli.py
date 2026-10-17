"""Partner events CLI: arguments, dry-run defaults and the Infisical re-exec (no process runs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ac_platform.partner_events import cli
from ac_platform.partner_events.endpoints import EndpointError, validate

BASE = ["--service-config", "service.json", "--database-url-file", "database-url"]


def test_every_change_is_a_dry_run_by_default() -> None:
    tenant = str(uuid4())
    for command in (
        ["run"],
        [
            "register-endpoint",
            "--tenant",
            tenant,
            "--url",
            "https://hooks.example.test/sx",
            "--secret-ref",
            "AC_PARTNER_WEBHOOK_SECRET__WISELIFE_DEV",
            "--events",
            "analysis.completed",
            "--facts-profile",
            "wiselife-quote-v1",
            "--reason",
            "fictional",
            "--operator-reference",
            "fictional",
        ],
        ["disable-endpoint", "--endpoint-id", tenant, "--reason", "r", "--operator-reference", "o"],
        ["replay", "--event-id", tenant, "--reason", "r", "--operator-reference", "o"],
        ["test-event", "--endpoint-id", tenant],
    ):
        arguments = cli._arguments([*BASE, *command])
        assert arguments.apply is False
        assert cli._needs_secrets(arguments) is False
    run = cli._arguments([*BASE, "run"])
    assert (run.seconds, run.interval, run.limit, run.daily_cap, run.recent_hours) == (
        55,
        5,
        10,
        300,
        72,
    )
    assert cli._needs_secrets(cli._arguments([*BASE, "run", "--apply"])) is True
    assert cli._needs_secrets(cli._arguments([*BASE, "list"])) is False


@pytest.mark.parametrize(
    "command",
    [
        ["run", "--seconds", "0"],
        ["run", "--daily-cap", "5000"],
        ["register-endpoint", "--tenant", "x"],
        ["register-endpoint", "--tenant", str(uuid4()), "--url", "u", "--secret-ref", "s",
         "--events", "analysis.deleted", "--reason", "r", "--operator-reference", "o"],
    ],
)  # fmt: skip
def test_bad_arguments_are_refused(command: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli._arguments([*BASE, *command])


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"url": "http://hooks.example.test/sx"}, "url_refused"),
        ({"url": "http://127.0.0.1:8787/hook", "environment": "production"}, "url_refused"),
        ({"secret_ref": "GEMINI_API_KEY"}, "secret_ref_invalid"),
        ({"secret_ref_next": "AC_PARTNER_WEBHOOK_SECRET__A"}, "secret_ref_next_invalid"),
        ({"events": []}, "events_invalid"),
        ({"events": ["analysis.completed", "analysis.completed"]}, "events_invalid"),
        ({"facts_profile": "other-v1"}, "facts_profile_unknown"),
    ],
)
def test_endpoint_validation(changes: dict[str, Any], code: str) -> None:
    values: dict[str, Any] = {
        "url": "https://hooks.example.test/sx",
        "secret_ref": "AC_PARTNER_WEBHOOK_SECRET__A",
        "secret_ref_next": None,
        "events": ["analysis.completed"],
        "facts_profile": "wiselife-quote-v1",
        "environment": "development",
    }
    validate(**values)
    validate(**{**values, "url": "http://127.0.0.1:8787/hook"})
    with pytest.raises(EndpointError, match=code):
        validate(**{**values, **changes})


def test_apply_reexecs_inside_infisical_with_the_gemini_secret_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = tmp_path / "token"
    token.write_text("INFISICAL_TOKEN=fictional-token\n")
    service = tmp_path / "service.json"
    service.write_text(
        json.dumps(
            {
                "environment": "development",
                "providers": [
                    {"provider_id": "elevenlabs", "secret_path_ref": "/other"},
                    {
                        "provider_id": "gemini",
                        "executable": "/usr/local/bin/infisical",
                        "project_ref": "project-fictional",
                        "environment_ref": "dev",
                        "secret_path_ref": "/sales-xray-test/gemini",
                        "token_file_ref": str(token),
                    },
                ],
            }
        )
    )
    captured: dict[str, Any] = {}

    def fake_exec(path: str, command: list[str], environment: dict[str, str]) -> None:
        captured.update(path=path, command=command, environment=environment)

    async def endpoint_active(*args: Any, **kwargs: Any) -> bool:
        return True

    monkeypatch.setattr(cli.os, "execvpe", fake_exec)
    monkeypatch.setattr(cli, "_preflight_async", endpoint_active)
    argv = [
        "--service-config",
        str(service),
        "--database-url-file",
        "database-url",
        "run",
        "--apply",
    ]
    assert cli.main(argv) == 0
    command = captured["command"]
    assert command[0] == "/usr/local/bin/infisical"
    assert command[command.index("--path") + 1] == "/sales-xray-test/gemini"
    assert command[command.index("--env") + 1] == "dev"
    tail = command[command.index("--") + 1 :]
    # The hidden inner flag precedes the subcommand so argparse accepts it.
    assert tail[1:4] == ["-m", "ac_platform.partner_events.cli", "--inner"]
    assert tail[4:] == argv
    assert captured["environment"]["INFISICAL_TOKEN"] == "fictional-token"  # noqa: S105
    assert "GEMINI_API_KEY" not in captured["environment"]
