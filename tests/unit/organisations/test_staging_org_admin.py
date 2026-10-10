"""Staging tool argument and error containment; no runtime secrets or data."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.organisations.service import OrganisationCommandError

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/staging-org-admin.py"
SPEC = importlib.util.spec_from_file_location("staging_org_admin", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def arguments(tenant=None, actor=None, targets=None, *, action="add-members", apply=False):
    argv = [
        action,
        "--environment",
        "staging",
        "--tenant-id",
        str(tenant or uuid4()),
        "--actor-person-id",
        str(actor or uuid4()),
        "--approver",
        "owner-approval-1694",
        "--issue-reference",
        "AUT-1694",
        "--operator-reference",
        "claude-operator",
        "--run-reference",
        "01010101-0101-4101-8101-010101010101",
    ]
    for target in targets or ["Worker@EXAMPLE.test"]:
        argv += ["--target", str(target), "--command-id", str(uuid4())]
    if apply:
        argv += ["--apply", "--snapshot-reference", "staging-snapshot-fixture"]
    return tool._parser().parse_args(argv)


def test_preview_is_default_and_targets_normalize():
    args = arguments()
    assert args.target == ["worker@example.test"]
    assert not args.apply and args.snapshot_reference is None
    assert tool._mask(args.target[0]) == "w***@example.test"


@pytest.mark.parametrize("environment", ["production", "development", "test", ""])
def test_only_injected_staging_runtime_is_allowed(monkeypatch, environment):
    monkeypatch.setenv("AC_ENVIRONMENT", environment)
    with pytest.raises(OrganisationCommandError, match="staging runtime"):
        tool._settings(arguments())


@pytest.mark.parametrize(
    "error", [ValueError, RuntimeError, OSError, SQLAlchemyError, AuthorizationDenied]
)
def test_failures_do_not_echo_exception_contents(monkeypatch, capsys, error):
    async def fail(_args):
        raise error("fictional-private-input")

    monkeypatch.setattr(tool, "_run", fail)
    monkeypatch.setattr(
        tool, "_parser", lambda: type("Parser", (), {"parse_args": lambda *_: None})()
    )
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "fictional-private-input" not in output.err
    assert "no batch changes committed" in output.err


@pytest.mark.parametrize("value", ["owner@example.test", "private-password", "production"])
def test_invalid_cli_does_not_echo_inputs(capsys, value):
    assert tool.main(["--actor-person-id", value]) == 2
    output = capsys.readouterr()
    assert value not in output.out + output.err


def test_committed_result_delivery_failure_is_distinct_from_rollback(monkeypatch, capsys):
    async def fail(_args):
        raise tool.ResultDeliveryError

    monkeypatch.setattr(tool, "_run", fail)
    monkeypatch.setattr(
        tool, "_parser", lambda: type("Parser", (), {"parse_args": lambda *_: None})()
    )
    assert tool.main([]) == 3
    output = capsys.readouterr()
    assert "transaction completed" in output.err
    assert "no batch changes committed" not in output.err
