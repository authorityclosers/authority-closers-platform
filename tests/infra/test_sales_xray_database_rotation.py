from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / "infra"
    / "application"
    / "scripts"
    / "rotate-sales-xray-database.py"
)
SPEC = importlib.util.spec_from_file_location("sales_xray_database_rotation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
rotation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rotation
SPEC.loader.exec_module(rotation)

OLD_PASSWORD = "synthetic-old-runtime-password-123456789"  # noqa: S105
MIGRATOR_PASSWORD = "synthetic-migrator-password-123456789"  # noqa: S105
OWNER_PASSWORD = "synthetic-owner-password-123456789"  # noqa: S105
RUNTIME_URL = f"postgresql+psycopg://ac_runtime:{OLD_PASSWORD}@postgres/ac_platform"
MIGRATOR_URL = f"postgresql+psycopg://ac_migrator:{MIGRATOR_PASSWORD}@postgres/ac_platform"


class FakeStore:
    def __init__(
        self,
        values: dict[tuple[str, str], str],
        *,
        fail_url_once: bool = False,
        apply_then_raise_key: str | None = None,
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, str]] = []
        self.fail_url_once = fail_url_once
        self.apply_then_raise_key = apply_then_raise_key

    def get(self, key: str, environment: str) -> str:
        return self.values[(key, environment)]

    def set(self, key: str, value: str, environment: str) -> None:
        self.calls.append((key, value, environment))
        if key == "AC_DATABASE_URL" and self.fail_url_once:
            self.fail_url_once = False
            raise rotation.RotationError("synthetic store failure")
        self.values[(key, environment)] = value
        if key == self.apply_then_raise_key:
            self.apply_then_raise_key = None
            raise RuntimeError("synthetic applied store failure")


class FakeDatabase:
    def __init__(self, *, apply_then_raise: bool = False) -> None:
        self.altered: list[str] = []
        self.verified: list[str] = []
        self.apply_then_raise = apply_then_raise
        self.snapshots = [
            {"role": "ac_runtime", "table_grants": ["same"], "database_create": False},
            {"role": "ac_runtime", "table_grants": ["same"], "database_create": False},
        ]

    def verify_runtime(self, profile: rotation.DatabaseProfile) -> None:
        self.verified.append(profile.password)

    def privilege_snapshot(self, profile: rotation.DatabaseProfile) -> dict[str, Any]:
        assert profile.username == "ac_owner"
        return self.snapshots.pop(0)

    def alter_runtime_password(self, owner: rotation.DatabaseProfile, password: str) -> None:
        assert owner.username == "ac_owner"
        self.altered.append(password)
        if self.apply_then_raise and len(self.altered) == 1:
            raise RuntimeError("synthetic applied database failure")


def _store(
    *,
    production_password: str = "synthetic-production-runtime-password-123456",  # noqa: S107
) -> FakeStore:
    return FakeStore(
        {
            ("AC_DB_RUNTIME_PASSWORD", "staging"): OLD_PASSWORD,
            ("AC_DATABASE_URL", "staging"): RUNTIME_URL,
            ("AC_DATABASE_MIGRATOR_URL", "staging"): MIGRATOR_URL,
            ("AC_POSTGRES_OWNER_PASSWORD", "staging"): OWNER_PASSWORD,
            ("AC_DB_RUNTIME_PASSWORD", "prod"): production_password,
        }
    )


def test_rotation_updates_store_file_and_role_without_secret_receipt(tmp_path: Path) -> None:
    path = tmp_path / "database-url"
    path.write_text(RUNTIME_URL, encoding="utf-8")
    store = _store()
    database = FakeDatabase()

    receipt = rotation.rotate_staging(
        store,
        database,
        database_file=path,
        require_file_owner=False,
    )

    new_password = store.values[("AC_DB_RUNTIME_PASSWORD", "staging")]
    new_url = store.values[("AC_DATABASE_URL", "staging")]
    assert new_password != OLD_PASSWORD
    assert path.read_text(encoding="utf-8") == new_url
    assert database.altered == [new_password]
    assert database.verified == [OLD_PASSWORD, new_password]
    assert receipt == {
        "schema": "ac.sales-xray.database-credential-rotation/1",
        "status": "rotated",
        "environment": "staging",
        "updated_infisical_keys": ["AC_DB_RUNTIME_PASSWORD", "AC_DATABASE_URL"],
        "worker_credential_file_updated": True,
        "privilege_snapshot_unchanged": True,
        "production_runtime_password_matches_staging_before_rotation": False,
        "restart_required": True,
        "provider_calls": 0,
        "secret_values_emitted": False,
    }
    assert OLD_PASSWORD not in repr(receipt)
    assert new_password not in repr(receipt)


def test_rotation_rolls_database_and_file_back_when_store_update_fails(tmp_path: Path) -> None:
    path = tmp_path / "database-url"
    path.write_text(RUNTIME_URL, encoding="utf-8")
    store = _store()
    store.fail_url_once = True
    database = FakeDatabase()

    with pytest.raises(rotation.RotationError):
        rotation.rotate_staging(
            store,
            database,
            database_file=path,
            require_file_owner=False,
        )

    assert path.read_text(encoding="utf-8") == RUNTIME_URL
    assert store.values[("AC_DATABASE_URL", "staging")] == RUNTIME_URL
    assert store.values[("AC_DB_RUNTIME_PASSWORD", "staging")] == OLD_PASSWORD
    assert database.altered[-1] == OLD_PASSWORD


def test_rotation_marks_database_attempt_before_applied_write_failure(tmp_path: Path) -> None:
    path = tmp_path / "database-url"
    path.write_text(RUNTIME_URL, encoding="utf-8")
    database = FakeDatabase(apply_then_raise=True)

    with pytest.raises(rotation.RotationError) as error:
        rotation.rotate_staging(
            _store(),
            database,
            database_file=path,
            require_file_owner=False,
        )

    assert error.value.rollback == {
        "store": "not-attempted",
        "file": "not-attempted",
        "database": "verified",
    }
    assert len(database.altered) == 2
    assert database.altered[-1] == OLD_PASSWORD
    assert path.read_text(encoding="utf-8") == RUNTIME_URL


def test_rotation_verifies_store_rollback_when_patch_applies_then_raises(tmp_path: Path) -> None:
    path = tmp_path / "database-url"
    path.write_text(RUNTIME_URL, encoding="utf-8")
    store = _store()
    store.apply_then_raise_key = "AC_DB_RUNTIME_PASSWORD"
    database = FakeDatabase()

    with pytest.raises(rotation.RotationError) as error:
        rotation.rotate_staging(
            store,
            database,
            database_file=path,
            require_file_owner=False,
        )

    assert error.value.rollback == {
        "store": "verified",
        "file": "verified",
        "database": "verified",
    }
    assert store.values[("AC_DB_RUNTIME_PASSWORD", "staging")] == OLD_PASSWORD
    assert store.values[("AC_DATABASE_URL", "staging")] == RUNTIME_URL
    assert path.read_text(encoding="utf-8") == RUNTIME_URL
    assert database.altered[-1] == OLD_PASSWORD


def test_rotation_verifies_file_rollback_when_replace_applies_then_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "database-url"
    path.write_text(RUNTIME_URL, encoding="utf-8")
    real_replace = rotation._replace_private_file
    calls = 0

    def apply_then_raise(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        real_replace(*args, **kwargs)
        if calls == 1:
            raise RuntimeError("synthetic applied file failure")

    monkeypatch.setattr(rotation, "_replace_private_file", apply_then_raise)
    database = FakeDatabase()

    with pytest.raises(rotation.RotationError) as error:
        rotation.rotate_staging(
            _store(),
            database,
            database_file=path,
            require_file_owner=False,
        )

    assert error.value.rollback == {
        "store": "not-attempted",
        "file": "verified",
        "database": "verified",
    }
    assert path.read_text(encoding="utf-8") == RUNTIME_URL
    assert database.altered[-1] == OLD_PASSWORD


@pytest.mark.parametrize(
    "value, expected_user",
    [
        (
            "postgresql+psycopg://ac_owner:synthetic-owner-password-123456@postgres/ac_platform",
            "ac_runtime",
        ),
        (
            "postgresql+psycopg://ac_runtime:synthetic-password-123456@127.0.0.1/ac_platform",
            "ac_runtime",
        ),
        (
            "postgresql+psycopg://ac_runtime:local-runtime-password@postgres/ac_platform",
            "ac_runtime",
        ),
    ],
)
def test_database_url_parser_rejects_wrong_scope_without_echoing(
    value: str, expected_user: str
) -> None:
    with pytest.raises(rotation.RotationError) as error:
        rotation.parse_database_url(value, expected_user)
    assert "synthetic" not in str(error.value)


def _compose_release(tmp_path: Path) -> Path:
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "staging.env").write_text("", encoding="utf-8")
    (tmp_path / "release-images.env").write_text("", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text("", encoding="utf-8")
    return tmp_path


def test_psql_command_keeps_password_out_of_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, stdout=b"1\n", stderr=b"")

    monkeypatch.setattr(rotation.subprocess, "run", fake_run)
    database = rotation.PsqlDatabase(release_dir=_compose_release(tmp_path))
    assert database._run("SELECT 1;", stdin="synthetic-input\n") == "1"
    assert OLD_PASSWORD not in " ".join(captured["command"])
    assert captured["env"].get("PGPASSWORD") is None
    assert captured["input"] == b"synthetic-input\n"


def test_psql_password_change_uses_stdin_not_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(rotation.subprocess, "run", fake_run)
    new_password = "synthetic-new-runtime-password-123456789"  # noqa: S105
    rotation.PsqlDatabase(release_dir=_compose_release(tmp_path)).alter_runtime_password(
        rotation.DatabaseProfile("ac_owner", OWNER_PASSWORD),
        new_password,
    )
    assert new_password not in " ".join(captured["command"])
    assert new_password.encode("utf-8") not in captured["input"]
    assert b"SCRAM-SHA-256$" in captured["input"]
    assert b"SET LOCAL log_statement = 'none';" in captured["input"]
    assert captured["input"].startswith(OWNER_PASSWORD.encode("utf-8") + b"\n")


@pytest.mark.parametrize(
    "rollback, expected",
    [
        (None, "not-started"),
        ({"database": "verified", "file": "not-attempted", "store": "verified"}, "verified"),
        ({"database": "uncertain", "file": "verified", "store": "verified"}, "uncertain"),
    ],
)
def test_rollback_summary_is_non_secret(rollback: dict[str, str] | None, expected: str) -> None:
    assert rotation._rollback_summary(rollback) == expected
