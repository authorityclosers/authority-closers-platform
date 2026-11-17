"""admin.py arguments, command groups and runtime gates; no runtime secrets or data."""

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
    return tool.parse(argv)


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


def grouped(*argv, write=True, environment="development"):
    given = [*argv, "--environment", environment]
    if argv[:2] not in (("workspaces", "list"), ("workspaces", "create")):
        given += ["--tenant-id", str(uuid4())]
    if write:
        given += [
            "--actor-person-id",
            str(uuid4()),
            "--approver",
            "owner-chat-20261117",
            "--issue",
            "orch:admin-cli-20261117",
        ]
    return tool.parse(given)


def test_every_group_and_command_is_handled_and_flat_names_still_work():
    for group, names in tool.COMMANDS.items():
        for name in names:
            assert (group, name) in tool.HANDLERS
    legacy = arguments("rename-person")
    assert (legacy.group, legacy.command, legacy.legacy) == ("people", "rename", "rename-person")
    assert legacy.json is True
    assert arguments("reassign-leads", extra=("--to-person-id", str(uuid4()))).group == "leads"
    assert grouped("people", "list", write=False).json is False


def test_reads_need_no_approver_and_writes_need_one():
    for argv in (
        ("people", "list"),
        ("workspaces", "list"),
        ("workspaces", "show"),
        ("workspaces", "switches"),
        ("leads", "list"),
    ):
        args = grouped(*argv, write=False)
        assert not tool._writes(args)
        tool._check_command(args)
    args = grouped("workspaces", "switches", "--stage", "on", write=False)
    assert tool._writes(args)
    with pytest.raises(OrganisationCommandError, match="approver"):
        tool._check_command(args)
    tool._check_command(grouped("workspaces", "switches", "--stage", "on"))
    with pytest.raises(OrganisationCommandError):
        grouped("workspaces", "switches", "--stage", "maybe")


def test_lead_selections_are_ids_or_a_filter():
    lead = str(uuid4())
    tool._check_command(grouped("leads", "archive", "--lead-id", lead))
    tool._check_command(grouped("leads", "bin", "--where-step", "new", "--where-side", "cold"))
    for argv in (
        ("leads", "archive"),
        ("leads", "archive", "--lead-id", lead, "--where-step", "new"),
        ("leads", "assign", "--lead-id", lead),
        ("leads", "assign", "--lead-id", lead, "--rules", "--to-person-id", lead),
        (
            "leads",
            "reassign",
            "--person-id",
            lead,
            "--to-person-id",
            str(uuid4()),
            "--lead-id",
            lead,
        ),
    ):
        with pytest.raises(OrganisationCommandError):
            tool._check_command(grouped(*argv))
    tool._check_command(grouped("leads", "assign", "--lead-id", lead, "--rules"))
    with pytest.raises(OrganisationCommandError):
        tool._check_command(grouped("workspaces", "domains"))
    with pytest.raises(OrganisationCommandError):
        tool._check_command(grouped("workspaces", "domains", "--clear", "--auto-join"))
    tool._check_command(grouped("workspaces", "domains", "--domain", "example.com"))
    with pytest.raises(OrganisationCommandError):
        grouped("people", "set-role", "--person-id", lead, "--role", "owner")
    assert grouped("people", "set-role", "--person-id", lead, "--role", "viewer").role == "viewer"


def test_a_rerun_gets_the_same_command_id_and_a_new_change_another():
    tenant, person, actor = str(uuid4()), str(uuid4()), str(uuid4())

    def made(role):
        args = tool.parse(
            [
                "people",
                "set-role",
                "--environment",
                "staging",
                "--tenant-id",
                tenant,
                "--person-id",
                person,
                "--role",
                role,
                "--actor-person-id",
                actor,
                "--approver",
                "a",
                "--issue",
                "b",
            ]
        )
        return tool._command_id(args, tool._intent(args))

    assert made("admin") == made("admin")
    assert made("admin") != made("member")
    given = uuid4()
    args = arguments(command_id=given)
    assert tool._command_id(args, tool._intent(args)) == given


def test_receipts_read_as_lines_and_hide_lead_names_and_emails():
    lines = tool._words(
        {"status": "read", "people": [{"person_id": "p", "email": tool._mask("asha@example.com")}]}
    )
    assert lines == ["status: read", "people:", "  - person_id=p, email=a***@example.com"]
    assert tool._mask(None) is None
