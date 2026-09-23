from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.analysis_settings_cli import (
    CommandError,
    parser,
    validate_environment,
)


def arguments(*extra: str) -> list[str]:
    return [
        "--environment",
        "production",
        "--tenant-id",
        str(uuid4()),
        "--person-id",
        str(uuid4()),
        "--session-id",
        str(uuid4()),
        *extra,
    ]


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    # Validation only: never opened and no database connection is made.
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://127.0.0.1/unused")


@pytest.mark.parametrize("action", ["show", "history"])
def test_read_actions_need_no_mutation_parameters(action: str) -> None:
    args = parser().parse_args(arguments("--action", action))
    assert validate_environment(args) == "production"


def test_default_remains_explicit_production_save() -> None:
    args = parser().parse_args(arguments())
    assert args.action == "save"
    with pytest.raises(CommandError, match="allow-production"):
        validate_environment(args)
    args.allow_production = True
    with pytest.raises(CommandError, match="all settings"):
        validate_environment(args)


@pytest.mark.parametrize(
    "extra",
    [
        ["--action", "show", "--c4-max-requests", "4"],
        ["--action", "history", "--idempotency-key", "must-not-save"],
        ["--action", "show", "--before-revision", "5"],
        ["--action", "history", "--limit", "51"],
        ["--action", "history", "--before-revision", "0"],
    ],
)
def test_read_commands_reject_ambiguous_or_unbounded_arguments(extra: list[str]) -> None:
    with pytest.raises(CommandError):
        validate_environment(parser().parse_args(arguments(*extra)))


def test_original_save_invocation_remains_supported() -> None:
    args = parser().parse_args(
        arguments(
            "--allow-production",
            "--expected-revision",
            "0",
            "--idempotency-key",
            "save-reviewed-settings",
            "--c4-max-requests",
            "4",
            "--c4-max-completion-tokens",
            "1400",
            "--c5-max-completion-tokens",
            "3200",
            "--c5-output-profile",
            "detailed",
        )
    )
    assert validate_environment(args) == "production"
