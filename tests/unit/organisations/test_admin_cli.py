"""admin.py arguments and runtime gates; no runtime secrets or data."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.organisations.service import OrganisationCommandError

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/data-changes/admin.py"
SPEC = importlib.util.spec_from_file_location("admin_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def arguments(
    command="set-role",
    tenant=None,
    person=None,
    actor=None,
    *,
    extra=(),
    environment="staging",
    allow=False,
    apply=False,
    command_id=None,
):
    argv = [
        command,
        "--environment",
        environment,
        "--tenant-id",
        str(tenant or uuid4()),
        "--person-id",
        str(person or uuid4()),
        "--actor-person-id",
        str(actor or uuid4()),
        "--command-id",
        str(command_id or uuid4()),
        "--approver",
        "owner-chat-20261117",
        "--issue-reference",
        "orch:wl-isolar-admin-20261117",
        "--operator-reference",
        "luna-pipeline",
        "--run-reference",
        "01010101-0101-4101-8101-010101010101",
        *extra,
    ]
    if command == "set-role" and "--role" not in extra:
        argv += ["--role", "admin"]
    if command == "rename-person" and "--name" not in extra:
        argv += ["--name", "  Wise   Life Admin "]
    if allow:
        argv.append("--allow-production")
    if apply:
        argv += ["--apply", "--snapshot-reference", "snapshot-fixture"]
    return tool._parser().parse_args(argv)


def test_commands_take_only_their_own_options_and_names_are_normalised():
    assert arguments("rename-person").name == "Wise Life Admin"
    assert arguments("set-role").role == "admin"
    for command, extra in (
        ("transfer-owner", ("--role", "admin")),
        ("transfer-owner", ("--name", "x")),
        ("set-role", ("--role", "admin", "--name", "x")),
    ):
        with pytest.raises(OrganisationCommandError):
            tool._check_command(arguments(command, extra=extra))
    for bad in ("", " ", "a" * 201, "bad\x07name"):
        with pytest.raises(OrganisationCommandError):
            arguments("rename-person", extra=("--name", bad))
    with pytest.raises(OrganisationCommandError):
        arguments("set-role", extra=("--role", "owner"))
    with pytest.raises(OrganisationCommandError):
        arguments("delete-person")
    with pytest.raises(OrganisationCommandError):
        tool._check_command(
            arguments("set-role", extra=("--role", "admin", "--to-person-id", str(uuid4())))
        )
    with pytest.raises(OrganisationCommandError):
        tool._check_command(arguments("reassign-leads"))
    same = uuid4()
    with pytest.raises(OrganisationCommandError, match="already belong"):
        tool._check_command(
            arguments("reassign-leads", person=same, extra=("--to-person-id", str(same)))
        )
    assert arguments("remove-member").command == "remove-member"


def test_production_needs_its_flag_and_its_own_runtime(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    with pytest.raises(OrganisationCommandError, match="allow-production"):
        tool._settings(arguments(environment="production"))
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    with pytest.raises(OrganisationCommandError, match="named environment"):
        tool._settings(arguments(environment="production", allow=True))


def test_a_refusal_prints_one_fixed_line(monkeypatch, capsys):
    monkeypatch.setenv("AC_ENVIRONMENT", "test")
    argv = [
        "rename-person",
        "--environment",
        "production",
        "--tenant-id",
        str(uuid4()),
        "--person-id",
        str(uuid4()),
        "--name",
        "Private Person Name",
        "--actor-person-id",
        str(uuid4()),
        "--command-id",
        str(uuid4()),
        "--approver",
        "a",
        "--issue-reference",
        "b",
        "--operator-reference",
        "c",
        "--run-reference",
        str(uuid4()),
    ]
    assert tool.main(argv) == 2
    out = capsys.readouterr()
    assert "Private Person" not in out.out + out.err
    assert "refused or failed" in out.err
