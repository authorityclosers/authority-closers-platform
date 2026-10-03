"""Input and output containment for the staging-only operational tool."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.settings import Settings
from ac_platform.organisations.service import OrganisationCommandError

SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/data-changes/staging-organisation-memberships.py"
)
SPEC = importlib.util.spec_from_file_location("staging_memberships", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def arguments(tenant_id=None, targets=None, commands=None, *, apply=False):
    targets = targets or ["worker@example.test"]
    commands = commands or [uuid4() for _ in targets]
    argv = [
        "--environment",
        "staging",
        "--tenant-id",
        str(tenant_id or uuid4()),
        "--role",
        "admin",
        "--approver",
        "owner-approval-123",
        "--issue-reference",
        "AUT-440",
        "--operator-reference",
        "root-operator",
        "--run-reference",
        "01010101-0101-4101-8101-010101010101",
    ]
    for target in targets:
        argv += ["--target", str(target)]
    for command in commands:
        argv += ["--command-id", str(command)]
    if apply:
        argv += ["--apply"]
    return tool._parser().parse_args(argv)


def test_preview_is_default_and_targets_are_explicit():
    person_id = uuid4()
    args = arguments(targets=["Worker@EXAMPLE.test", person_id])
    assert not args.apply
    assert args.target == ["worker@example.test", person_id]
    assert tool._mask(args.target[0]) == "w***@example.test"
    assert tool._mask(person_id) == str(person_id)


@pytest.mark.parametrize("environment", ["production", "development", "test", "local", ""])
def test_other_runtime_environments_refused_before_settings(monkeypatch, environment):
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    with pytest.raises(OrganisationCommandError, match="staging runtime"):
        tool._settings(arguments())


def test_missing_database_injection_refused(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.delenv("AC_DATABASE_URL", raising=False)
    with pytest.raises(OrganisationCommandError, match="injected database URL"):
        tool._settings(arguments())


def test_settings_require_runtime_tenant_guards_and_baked_release(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://unused/unused")
    settings = Settings(_env_file=None, environment="test").model_copy(
        update={"environment": "staging", "release_id": "1" * 40}
    )
    monkeypatch.setattr(tool, "Settings", lambda **kwargs: settings)
    checked = []
    monkeypatch.setattr(tool, "require_baked_release_id", checked.append)
    with pytest.raises(OrganisationCommandError, match="protected tenant IDs"):
        tool._settings(arguments())
    assert checked == ["1" * 40]
    settings.operations_tenant_id, settings.public_learner_tenant_id = uuid4(), uuid4()
    assert tool._settings(arguments()) is settings


def test_mismatched_baked_release_is_refused_without_printing_runtime_values(monkeypatch, capsys):
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://unused/unused")
    settings = Settings(_env_file=None, environment="test").model_copy(
        update={"environment": "staging", "release_id": "1" * 40}
    )
    monkeypatch.setattr(tool, "Settings", lambda **kwargs: settings)

    def refuse(_release):
        raise RuntimeError("fictional-private-runtime-value")

    monkeypatch.setattr(tool, "require_baked_release_id", refuse)
    args = arguments()
    monkeypatch.setattr(
        tool, "_parser", lambda: type("Parser", (), {"parse_args": lambda *_: args})()
    )
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "fictional-private-runtime-value" not in output.err


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--target", "invalid-personal-email@example"),
        ("--role", "owner"),
        ("--environment", "production"),
        ("--approver", "owner@example.test"),
        ("--command-id", "private-credential"),
    ],
)
def test_parse_errors_do_not_echo_inputs(capsys, flag, value):
    assert tool.main([flag, value]) == 2
    output = capsys.readouterr()
    assert value not in output.out + output.err
    assert "no batch changes committed" in output.err


@pytest.mark.parametrize("error", [ValueError, RuntimeError, OSError, SQLAlchemyError])
def test_runtime_errors_never_print_secrets(monkeypatch, capsys, error):
    secret = "fictional-injected-secret@example.test"  # noqa: S105 - fictional containment marker

    async def fail(_args):
        raise error(secret)

    monkeypatch.setattr(tool, "_run", fail)
    monkeypatch.setattr(
        tool, "_parser", lambda: type("Parser", (), {"parse_args": lambda *_: None})()
    )
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert output.out == ""
