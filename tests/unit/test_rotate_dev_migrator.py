from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts.ops import rotate_dev_migrator as rotation

BRIDGE = "172.27.0.2"
OLD_PASSWORD = "fictional-old-migrator-password-0001"  # noqa: S105 - fictional
OLD_URL = f"postgresql+psycopg://ac_migrator:{OLD_PASSWORD}@{BRIDGE}:5432/ac_platform"
RUNTIME_URL = (
    "postgresql+psycopg://ac_runtime:fictional-runtime-password-01@172.27.0.2:5432/ac_platform"
)


def verifier_matches(verifier: str, password: str) -> bool:
    head, server_part = verifier.split("$", 1)[1].rsplit("$", 1)
    iterations, salt = head.split(":")
    stored_key = base64.b64decode(server_part.split(":")[0])
    salted = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(salt), int(iterations)
    )
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    return hashlib.sha256(client_key).digest() == stored_key


class FakeDatabase:
    """Checks logins against the SCRAM verifier the script actually sends."""

    def __init__(self, password: str = OLD_PASSWORD, *, trust: bool = False) -> None:
        self.verifier = rotation.scram_verifier(password)
        self.trust = trust
        self.set_calls = 0
        self.fail_snapshot_after_set = False
        self.state = {"database": "ac_platform", "role": "ac_migrator", "rolsuper": False}
        self.bridge = {BRIDGE}
        self.published = {("127.0.0.1", 55432)}

    def endpoints(self) -> tuple[set[str], set[tuple[str, int]]]:
        return set(self.bridge), set(self.published)

    def login(self, host: str, password: str) -> bool:
        assert host == BRIDGE
        return self.trust or verifier_matches(self.verifier, password)

    def snapshot(self) -> dict[str, Any]:
        if self.fail_snapshot_after_set and self.set_calls == 1:
            return {**self.state, "rolsuper": True}
        return dict(self.state)

    def set_verifier(self, verifier: str) -> None:
        self.set_calls += 1
        self.verifier = verifier

    def accepts(self, password: str) -> bool:
        return verifier_matches(self.verifier, password)


@pytest.fixture
def host(tmp_path: Path) -> rotation.Paths:
    development = tmp_path / "etc-development"
    development.mkdir(mode=0o700)
    write_env(
        development / "migrator.env",
        f"AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL={OLD_URL}\n",
    )
    consumer = tmp_path / "acdev-database.env"
    consumer.write_text(
        f"AC_ENVIRONMENT=development\nAC_DATABASE_URL={RUNTIME_URL}\n"
        f"AC_DATABASE_MIGRATOR_URL={OLD_URL}\n"
    )
    return rotation.Paths(
        development=development,
        lock=tmp_path / "rotation.lock",
        consumers=(consumer, tmp_path / "missing.env"),
        owner_uid=os.getuid(),
        owner_gid=os.getgid(),
    )


def write_env(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o600)


def run(
    host: rotation.Paths, database: FakeDatabase, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    code = rotation.main(list(argv), paths=host, database=database)
    out, err = capsys.readouterr()
    return code, out, err


APPLY = ("--apply", "--issue", "AUT-119", "--approver", "CEO (AUT-119 comment 99cb032a)")


def snapshot_tree(host: rotation.Paths) -> dict[str, bytes]:
    return {
        str(path): path.read_bytes()
        for path in sorted(host.development.rglob("*"))
        if path.is_file()
    } | {str(path): path.read_bytes() for path in host.consumers if path.exists()}


def assert_no_secret(text: str, *secrets: str) -> None:
    for secret in (OLD_PASSWORD, *secrets):
        assert secret not in text
    assert "postgresql" not in text


def current_password(host: rotation.Paths) -> str:
    line = [
        item
        for item in host.migrator_env.read_text().splitlines()
        if item.startswith("AC_DATABASE_MIGRATOR_URL=")
    ][0]
    return rotation.parse_url(line.partition("=")[2])[1]


def test_dry_run_is_default_and_changes_nothing(host, capsys):
    database = FakeDatabase()
    before = snapshot_tree(host)
    code, out, err = run(host, database, capsys)
    assert code == 0, err
    plan = json.loads(out)
    assert plan["mode"] == "dry-run" and plan["changed"] is False
    assert plan["current_login_verified"] and plan["wrong_password_refused"]
    assert snapshot_tree(host) == before
    assert not host.rotation.exists()
    assert database.set_calls == 0
    assert_no_secret(out + err)
    consumer = plan["consumers"][0]
    assert consumer == {
        "path": str(host.consumers[0]),
        "present": True,
        "changed": False,
        "has_migrator_url": True,
        "holds_pre_rotation_credential": True,
    }
    assert plan["consumers"][1]["present"] is False


def test_apply_rotates_once_with_verified_backup_and_redacted_receipt(host, capsys):
    database = FakeDatabase()
    original = host.migrator_env.read_bytes()
    consumer_before = host.consumers[0].read_bytes()
    code, out, err = run(host, database, capsys, *APPLY)
    assert code == 0, err
    result = json.loads(out)
    new = current_password(host)
    assert result["status"] == "rotated" and result["changed"] is True
    assert database.accepts(new) and not database.accepts(OLD_PASSWORD)
    assert database.set_calls == 1
    assert len(new) >= 40 and new != OLD_PASSWORD
    assert host.migrator_env.read_text().startswith("AC_ENVIRONMENT=development\n")
    assert oct(host.migrator_env.stat().st_mode & 0o777) == "0o600"
    run_id = result["run_id"]
    assert (host.rotation / f"{run_id}.backup.env").read_bytes() == original
    receipt_text = (host.rotation / f"{run_id}.receipt.json").read_text()
    receipt = json.loads(receipt_text)
    assert receipt["issue"] == "AUT-119"
    assert receipt["approver"] == "CEO (AUT-119 comment 99cb032a)"
    assert receipt["new_login_verified"] and receipt["old_login_refused"]
    assert receipt["secret_values_emitted"] is False
    assert_no_secret(out + err + receipt_text, new)
    # Other consumers are reported, never rewritten.
    assert host.consumers[0].read_bytes() == consumer_before

    before = snapshot_tree(host)
    code, out, err = run(host, database, capsys, *APPLY)
    assert code == 0, err
    again = json.loads(out)
    assert again["result"] == "already_rotated" and again["changed"] is False
    assert again["run_id"] == run_id
    assert database.set_calls == 1
    assert snapshot_tree(host) == before


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            f"AC_ENVIRONMENT=staging\nAC_DATABASE_MIGRATOR_URL={OLD_URL}\n",
            "development_environment_required",
        ),
        (
            f"AC_ENVIRONMENT=production\nAC_DATABASE_MIGRATOR_URL={OLD_URL}\n",
            "development_environment_required",
        ),
        (
            f"AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL={RUNTIME_URL}\n",
            "migrator_url_invalid",
        ),
        (
            "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL="
            f"postgresql+psycopg://ac_migrator:{OLD_PASSWORD}@{BRIDGE}:5432/ac_staging\n",
            "migrator_url_invalid",
        ),
        (
            "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL="
            f"postgresql+psycopg://ac_migrator:{OLD_PASSWORD}@postgres:5432/ac_platform\n",
            "migrator_endpoint_not_ip",
        ),
        (
            "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL="
            f"postgresql+psycopg://ac_migrator:{OLD_PASSWORD}@172.19.0.9:5432/ac_platform\n",
            "endpoint_not_dev_container",
        ),
        (
            "AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL="
            f"postgresql+psycopg://ac_owner:{OLD_PASSWORD}@{BRIDGE}:5432/ac_platform\n",
            "migrator_url_invalid",
        ),
    ],
)
def test_refuses_wrong_environment_role_database_and_endpoint(host, capsys, text, code):
    write_env(host.migrator_env, text)
    database = FakeDatabase()
    before = snapshot_tree(host)
    status, out, err = run(host, database, capsys, *APPLY)
    assert status == 2 and out == ""
    assert err.strip() == f"FAIL dev migrator rotation refused: {code}"
    assert snapshot_tree(host) == before and database.set_calls == 0
    assert_no_secret(err)


def test_published_loopback_endpoint_is_accepted_and_preserved(host, capsys):
    loopback = OLD_URL.replace(f"{BRIDGE}:5432", "127.0.0.1:55432")
    write_env(
        host.migrator_env, f"AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL={loopback}\n"
    )
    database = FakeDatabase()
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 0, err
    assert "@127.0.0.1:55432/ac_platform" in host.migrator_env.read_text()
    assert database.accepts(current_password(host))


def test_refuses_when_database_trusts_any_password(host, capsys):
    database = FakeDatabase(trust=True)
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 2 and "login_not_password_authenticated" in err
    assert database.set_calls == 0 and not host.rotation.exists()


def test_refuses_when_current_credential_does_not_log_in(host, capsys):
    database = FakeDatabase(password="fictional-other-password-000002")  # noqa: S106
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 2 and "current_login_failed" in err
    assert database.set_calls == 0


@pytest.mark.parametrize(
    "argv",
    [
        ("--apply",),
        ("--apply", "--issue", "AUT-119"),
        ("--apply", "--issue", "119", "--approver", "CEO"),
        ("--apply", "--issue", "AUT-119", "--approver", "CEO; rm -rf /"),
    ],
)
def test_apply_requires_issue_and_approver(host, capsys, argv):
    database = FakeDatabase()
    code, _, _ = run(host, database, capsys, *argv)
    assert code == 2 and database.set_calls == 0 and not host.rotation.exists()


def test_no_credential_or_url_argument_exists(host, capsys):
    with pytest.raises(SystemExit):
        rotation.main(["--password", "x"], paths=host, database=FakeDatabase())
    with pytest.raises(SystemExit):
        rotation.main(["--url", OLD_URL], paths=host, database=FakeDatabase())
    capsys.readouterr()


def test_refuses_loose_file_permissions_and_non_owner(host, capsys):
    host.migrator_env.chmod(0o640)
    code, _, err = run(host, FakeDatabase(), capsys)
    assert code == 2 and "migrator_env_invalid" in err
    host.migrator_env.chmod(0o600)
    other = rotation.Paths(
        development=host.development, lock=host.lock, consumers=(), owner_uid=os.getuid() + 1
    )
    code, _, err = run(other, FakeDatabase(), capsys, *APPLY)
    assert code == 2 and "root_required" in err


def test_failure_after_password_change_rolls_back_and_allows_retry(host, capsys):
    database = FakeDatabase()
    database.fail_snapshot_after_set = True
    original = host.migrator_env.read_bytes()
    code, out, err = run(host, database, capsys, *APPLY)
    assert code == 2 and out == ""
    assert "privilege_snapshot_changed; rollback database=verified,file=not-attempted" in err
    assert database.accepts(OLD_PASSWORD)
    assert host.migrator_env.read_bytes() == original
    receipt = json.loads(next(host.rotation.glob("*.receipt.json")).read_text())
    assert receipt["status"] == "rolled_back" and receipt["failure"] == "privilege_snapshot_changed"
    assert_no_secret(err + json.dumps(receipt))

    database.fail_snapshot_after_set = False
    database.set_calls = 5
    code, out, err = run(host, database, capsys, *APPLY)
    assert code == 0, err
    assert database.accepts(current_password(host))


def test_file_write_failure_restores_database(host, capsys, monkeypatch):
    database = FakeDatabase()
    real_write = rotation.write_private

    def failing_write(path, data, paths, *, replace=None):
        if path == host.migrator_env:
            raise rotation.RotationError("file_write_failed")
        return real_write(path, data, paths, replace=replace)

    monkeypatch.setattr(rotation, "write_private", failing_write)
    original = host.migrator_env.read_bytes()
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 2
    assert "file_write_failed; rollback database=verified,file=verified" in err
    assert database.accepts(OLD_PASSWORD)
    assert host.migrator_env.read_bytes() == original


def test_uncertain_previous_run_blocks_new_apply_until_rollback(host, capsys, monkeypatch):
    database = FakeDatabase()
    code, out, _ = run(host, database, capsys, *APPLY)
    run_id = json.loads(out)["run_id"]
    receipt_path = host.rotation / f"{run_id}.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["status"] = "prepared"
    write_env(receipt_path, json.dumps(receipt))
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 2 and "previous_run_prepared_needs_rollback" in err

    code, out, err = run(host, database, capsys, "--rollback", run_id, *APPLY)
    assert code == 0, err
    assert database.accepts(OLD_PASSWORD)
    code, out, err = run(host, database, capsys, *APPLY)
    assert code == 0 and json.loads(out)["result"] == "rotated"


def test_rollback_dry_run_then_apply_restores_backup(host, capsys):
    database = FakeDatabase()
    original = host.migrator_env.read_bytes()
    code, out, _ = run(host, database, capsys, *APPLY)
    run_id = json.loads(out)["run_id"]
    new = current_password(host)

    before = snapshot_tree(host)
    calls = database.set_calls
    code, out, err = run(host, database, capsys, "--rollback", run_id)
    assert code == 0, err
    assert json.loads(out)["mode"] == "dry-run"
    assert snapshot_tree(host) == before and database.set_calls == calls

    code, out, err = run(host, database, capsys, "--rollback", run_id, *APPLY)
    assert code == 0, err
    assert json.loads(out)["status"] == "rolled_back"
    assert host.migrator_env.read_bytes() == original
    assert database.accepts(OLD_PASSWORD) and not database.accepts(new)
    receipt_text = (host.rotation / f"{run_id}.rollback.receipt.json").read_text()
    assert_no_secret(out + err + receipt_text, new)
    # The original receipt stays as audit history.
    assert json.loads((host.rotation / f"{run_id}.receipt.json").read_text())["status"] == "rotated"

    code, _, err = run(host, database, capsys, "--rollback", run_id, *APPLY)
    assert code == 2 and "run_not_latest_open_rotation" in err


def test_rollback_refuses_unknown_run_and_drifted_file(host, capsys):
    database = FakeDatabase()
    code, _, err = run(host, database, capsys, "--rollback", "20261002T000000Z-deadbeef", *APPLY)
    assert code == 2 and "run_not_found" in err
    code, out, _ = run(host, database, capsys, *APPLY)
    run_id = json.loads(out)["run_id"]
    drifted = OLD_URL.replace(OLD_PASSWORD, "fictional-someone-else-password-03")
    write_env(
        host.migrator_env, f"AC_ENVIRONMENT=development\nAC_DATABASE_MIGRATOR_URL={drifted}\n"
    )
    code, _, err = run(host, database, capsys, "--rollback", run_id, *APPLY)
    assert code == 2 and "migrator_env_drift" in err
    code, _, err = run(host, database, capsys, *APPLY)
    assert code == 2 and "previous_run_rotated_needs_rollback" in err


def test_docker_database_never_puts_values_in_argv(monkeypatch):
    seen: list[tuple[list[str], bytes | None]] = []

    class Done:
        def __init__(self, stdout: bytes, returncode: int = 0) -> None:
            self.stdout, self.returncode = stdout, returncode

    def fake_run(argv, *, input, **_):  # noqa: A002 - mirrors subprocess.run
        seen.append((argv, input))
        if argv[1] == "inspect":
            return Done(
                json.dumps({"Networks": {"n": {"IPAddress": BRIDGE}}, "Ports": {}}).encode()
            )
        if b"SELECT json_build_object" in (input or b""):
            return Done(b'{"database": "ac_platform", "role": "ac_migrator"}')
        if b"ALTER ROLE" in (input or b""):
            return Done(b"")
        return Done(b"ac_migrator")

    monkeypatch.setattr(rotation.subprocess, "run", fake_run)
    database = rotation.DockerDatabase()
    assert database.endpoints() == ({BRIDGE}, set())
    assert database.login(BRIDGE, OLD_PASSWORD) is True
    assert database.snapshot()["role"] == "ac_migrator"
    secret = rotation.new_password()
    verifier = rotation.scram_verifier(secret)
    database.set_verifier(verifier)
    for argv, _stdin in seen:
        joined = " ".join(argv)
        assert OLD_PASSWORD not in joined and secret not in joined and verifier not in joined
        assert argv[0] == "/usr/bin/docker"
        assert "acdev-postgres" in argv
    alter = seen[-1][1].decode()
    assert "BEGIN;" in alter and "COMMIT;" in alter and secret not in alter
    assert "SET LOCAL log_statement = 'none'" in alter
    with pytest.raises(rotation.RotationError):
        database.set_verifier("x'; DROP ROLE ac_owner; --")


def test_docker_login_distinguishes_auth_failure_from_docker_failure(monkeypatch):
    class Done:
        def __init__(self, returncode: int) -> None:
            self.stdout, self.returncode = b"", returncode

    codes = iter([2, 125])
    monkeypatch.setattr(rotation.subprocess, "run", lambda *a, **k: Done(next(codes)))
    database = rotation.DockerDatabase()
    assert database.login(BRIDGE, OLD_PASSWORD) is False
    with pytest.raises(rotation.RotationError):
        database.login(BRIDGE, OLD_PASSWORD)
