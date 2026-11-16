"""organisation-members.py arguments and runtime gates; no runtime secrets or data."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.organisations.service import OrganisationCommandError

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/organisation-members.py"
SPEC = importlib.util.spec_from_file_location("organisation_members", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def arguments(
    tenant=None, actor=None, targets=None, *, environment="staging", allow=False, apply=False
):
    argv = [
        "--environment",
        environment,
        "--tenant-id",
        str(tenant or uuid4()),
        "--actor-person-id",
        str(actor or uuid4()),
        "--approver",
        "owner-chat-20261116",
        "--issue-reference",
        "orch:wiselife-sellers-20261116",
        "--operator-reference",
        "luna-pipeline",
        "--run-reference",
        "01010101-0101-4101-8101-010101010101",
    ]
    if allow:
        argv.append("--allow-production")
    for target in targets or ["Seller@EXAMPLE.test"]:
        argv += ["--target", str(target), "--command-id", str(uuid4())]
    if apply:
        argv += ["--apply", "--snapshot-reference", "snapshot-fixture"]
    return tool._parser().parse_args(argv)


def test_preview_is_default_targets_are_emails_and_masked():
    args = arguments()
    assert args.target == ["seller@example.test"]
    assert not args.apply and args.snapshot_reference is None
    assert tool._mask(args.target[0]) == "s***@example.test"
    with pytest.raises(OrganisationCommandError):
        arguments(targets=[str(uuid4())])
    with pytest.raises(OrganisationCommandError):
        arguments(environment="development")


def test_production_needs_its_flag_and_its_own_runtime(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    with pytest.raises(OrganisationCommandError, match="allow-production"):
        tool._settings(arguments(environment="production"))
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    with pytest.raises(OrganisationCommandError, match="named environment"):
        tool._settings(arguments(environment="production", allow=True))
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    with pytest.raises(OrganisationCommandError, match="named environment"):
        tool._settings(arguments(environment="staging"))


def test_refusals_print_nothing_but_a_fixed_line(monkeypatch, capsys):
    monkeypatch.setenv("AC_ENVIRONMENT", "test")
    argv = [
        "--environment",
        "production",
        "--tenant-id",
        str(uuid4()),
        "--actor-person-id",
        str(uuid4()),
        "--approver",
        "a",
        "--issue-reference",
        "b",
        "--operator-reference",
        "c",
        "--run-reference",
        str(uuid4()),
        "--target",
        "private.person@example.test",
        "--command-id",
        str(uuid4()),
    ]
    assert tool.main(argv) == 2
    out = capsys.readouterr()
    assert "private.person" not in out.out + out.err
    assert "refused or failed" in out.err
