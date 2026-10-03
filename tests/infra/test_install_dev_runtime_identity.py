"""Dev runtime identity installer contract; a fake NSS database, never the host."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/install-dev-runtime-identity.py"
spec = importlib.util.spec_from_file_location("dev_runtime_identity", SCRIPT)
identity = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = identity
assert spec.loader
spec.loader.exec_module(identity)

GROUP_LINE = "ac-sales-xray-native:x:10001:"


class FakeHost:
    def __init__(self):
        self.passwd = ["root:x:0:0:root:/root:/bin/bash"]
        self.group = ["root:x:0:", "acops:x:1002:acdev", GROUP_LINE]
        self.units = dict.fromkeys(identity.DEV_UNITS, "inactive")
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        done = lambda code=0, out="": subprocess.CompletedProcess(argv, code, out, "")  # noqa: E731
        if argv[:2] == ["getent", "passwd"]:
            key = argv[2]
            hits = [x for x in self.passwd if key in (x.split(":")[0], x.split(":")[2])]
            return done(0, "\n".join(hits) + "\n") if hits else done(2)
        if argv[:2] == ["getent", "group"]:
            if len(argv) == 2:
                return done(0, "\n".join(self.group) + "\n")
            hits = [x for x in self.group if argv[2] in (x.split(":")[0], x.split(":")[2])]
            return done(0, "\n".join(hits) + "\n") if hits else done(2)
        if argv[:2] == ["id", "-G"]:
            line = next(x for x in self.passwd if x.split(":")[0] == argv[2])
            extra = [g.split(":")[2] for g in self.group if argv[2] in g.split(":")[3].split(",")]
            return done(0, " ".join([line.split(":")[3], *extra]) + "\n")
        if argv[:2] == ["systemctl", "is-active"]:
            return done(0 if self.units[argv[2]] == "active" else 3, self.units[argv[2]] + "\n")
        if argv[0] == "useradd":
            assert not {"--groups", "-G", "--create-home", "-m", "--user-group"} & set(argv)
            self.passwd.append(identity.EXPECTED)
            return done()
        if argv[0] == "userdel":
            assert argv == ["userdel", "--force", identity.USER]
            self.passwd = [x for x in self.passwd if not x.startswith(identity.USER + ":")]
            return done()
        raise AssertionError(argv)


def run(host, *args, capsys):
    code = identity.main(list(args), runner=host)
    return code, json.loads(capsys.readouterr().out)


def mutations(host):
    return [argv for argv in host.calls if argv[0] in ("useradd", "userdel")]


def test_dry_run_reports_plan_without_change(capsys):
    host = FakeHost()
    code, report = run(host, capsys=capsys)
    assert code == 0 and report["mode"] == "install-dry-run"
    assert report["action"] == "create" and not report["applied"]
    assert not mutations(host)


def test_apply_creates_exact_account_and_is_idempotent(capsys, monkeypatch):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 0)
    host = FakeHost()
    code, report = run(host, "--apply", capsys=capsys)
    assert code == 0 and report["applied"] and report["after"]["user"] == "present"
    useradd = mutations(host)[0]
    assert useradd[useradd.index("--uid") + 1] == "10001"
    assert useradd[useradd.index("--gid") + 1] == "10001"
    assert "--system" in useradd and "--no-user-group" in useradd
    # The native group's member list stays empty and acops is untouched.
    assert GROUP_LINE in host.group and "acops:x:1002:acdev" in host.group
    code, again = run(host, "--apply", capsys=capsys)
    assert code == 0 and again["action"] == "none" and len(mutations(host)) == 1


def test_apply_requires_root(capsys, monkeypatch):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 1000)
    host = FakeHost()
    code, report = run(host, "--apply", capsys=capsys)
    assert (code, report["error"]) == (1, "root_required") and not mutations(host)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda h: h.passwd.append("other:x:10001:10001::/:/bin/sh"), "runtime_user_conflict"),
        (lambda h: h.group.remove(GROUP_LINE), "runtime_group_missing"),
        (
            lambda h: h.group.__setitem__(2, GROUP_LINE + "someone"),
            "runtime_group_members_not_empty",
        ),
        (
            lambda h: h.group.__setitem__(2, "renamed:x:10001:"),
            "runtime_group_invalid",
        ),
    ],
)
def test_conflicts_refuse_without_change(capsys, monkeypatch, change, code):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 0)
    host = FakeHost()
    change(host)
    status, report = run(host, "--apply", capsys=capsys)
    assert (status, report) == (1, {"ok": False, "error": code})
    assert not mutations(host)


def test_supplementary_group_is_refused(capsys):
    host = FakeHost()
    host.passwd.append(identity.EXPECTED)
    host.group[1] = "acops:x:1002:acdev," + identity.USER
    status, report = run(host, capsys=capsys)
    assert (status, report["error"]) == (1, "runtime_user_supplementary_group")


def test_rollback_refuses_while_dev_units_run(capsys, monkeypatch):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 0)
    host = FakeHost()
    host.passwd.append(identity.EXPECTED)
    host.units["ac-dev-api.service"] = "active"
    status, report = run(host, "--rollback", "--apply", capsys=capsys)
    assert (status, report["error"]) == (1, "dev_units_active") and not mutations(host)


def test_rollback_removes_only_the_account(capsys, monkeypatch):
    monkeypatch.setattr(identity.os, "geteuid", lambda: 0)
    host = FakeHost()
    host.passwd.append(identity.EXPECTED)
    status, dry = run(host, "--rollback", capsys=capsys)
    assert status == 0 and dry["action"] == "delete" and not mutations(host)
    status, report = run(host, "--rollback", "--apply", capsys=capsys)
    assert status == 0 and report["after"] == {"user": "missing", "group": "present"}
    assert mutations(host) == [["userdel", "--force", identity.USER]]
    assert GROUP_LINE in host.group
    status, again = run(host, "--rollback", "--apply", capsys=capsys)
    assert status == 0 and again["action"] == "none" and len(mutations(host)) == 1
