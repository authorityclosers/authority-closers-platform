"""Confidential input and production-only boundary for AUT-398."""

from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.application.settings import Settings

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts/data-changes/production-smoke-email-verification.py"
)
SPEC = importlib.util.spec_from_file_location("production_smoke_verification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def arguments(person_id=None, *, apply=False):
    argv = [
        "--environment",
        "production",
        "--person-id",
        str(person_id or uuid4()),
        "--approver",
        tool.OWNER,
        "--approval-reference",
        tool.APPROVAL,
        "--issue-reference",
        "AUT-398",
    ]
    for name in ("operator-reference", "run-reference", "command-id"):
        argv += [f"--{name}", str(uuid4())]
    return tool._parser().parse_args(argv + (["--apply"] if apply else []))


def test_preview_default_and_confidential_single_input(monkeypatch):
    assert not arguments().apply
    email = "fictional+ac-qa-production@authorityclosers.com"
    monkeypatch.setattr(tool.sys, "stdin", StringIO(f"'{email}'\n"))
    assert tool._email_from_stdin() == email


@pytest.mark.parametrize(
    "value", ["", "person@example.test", "two@example.test other@example.test", " " + "x" * 1100]
)
def test_unexpected_confidential_input_refused(monkeypatch, value):
    monkeypatch.setattr(tool.sys, "stdin", StringIO(value))
    with pytest.raises((ValueError, tool.SmokeVerificationError)):
        tool._email_from_stdin()


@pytest.mark.parametrize("environment", ["staging", "development", "test", "local", ""])
def test_wrong_runtime_refused_before_settings(monkeypatch, environment):
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    with pytest.raises(tool.SmokeVerificationError, match="production runtime"):
        tool._settings(arguments())


def test_missing_injection_and_canonical_tenants_refused(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    monkeypatch.delenv("AC_DATABASE_URL", raising=False)
    with pytest.raises(tool.SmokeVerificationError, match="injected"):
        tool._settings(arguments())
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://unused/unused")
    settings = Settings(_env_file=None, environment="test").model_copy(
        update={"environment": "production", "release_id": "1" * 40}
    )
    monkeypatch.setattr(tool, "Settings", lambda **_: settings)
    checked = []
    monkeypatch.setattr(tool, "require_baked_release_id", checked.append)
    with pytest.raises(tool.SmokeVerificationError, match="canonical"):
        tool._settings(arguments())
    settings.operations_tenant_id, settings.public_learner_tenant_id = uuid4(), uuid4()
    assert tool._settings(arguments()) is settings
    assert checked == ["1" * 40, "1" * 40]


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--person-id", "private-marker"),
        ("--approver", "wrong-owner"),
        ("--issue-reference", "AUT-999"),
        ("--approval-reference", "wrong-approval"),
        ("--environment", "staging"),
        ("--email", "private@example.test"),
    ],
)
def test_parse_failures_do_not_echo_confidential_inputs(capsys, flag, value):
    assert tool.main([flag, value]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert value not in output.err


@pytest.mark.parametrize("error", [ValueError, RuntimeError, OSError, SQLAlchemyError])
def test_expected_runtime_failures_are_sanitized(monkeypatch, capsys, error):
    async def fail(_args):
        raise error("fictional-private-runtime-marker")

    monkeypatch.setattr(tool, "_run", fail)
    monkeypatch.setattr(
        tool, "_parser", lambda: type("Parser", (), {"parse_args": lambda *_: None})()
    )
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "fictional-private-runtime-marker" not in output.err


@pytest.mark.asyncio
async def test_ambiguous_target_refused_before_any_other_read_or_write():
    session = AsyncMock()
    session.scalars.return_value = [object(), object()]
    with pytest.raises(tool.SmokeVerificationError, match="exactly one"):
        await tool._change(
            session,
            Settings(_env_file=None, environment="test"),
            arguments(),
            "fictional@example.test",
        )
    session.scalar.assert_not_awaited()
    session.flush.assert_not_awaited()
