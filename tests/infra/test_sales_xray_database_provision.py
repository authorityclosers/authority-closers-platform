from __future__ import annotations

import importlib.util
import os
import shutil
import stat
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = (
    Path(__file__).parents[2]
    / "infra"
    / "application"
    / "scripts"
    / "provision-sales-xray-database.py"
)
SPEC = importlib.util.spec_from_file_location("sales_xray_database_provision", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
provisioner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisioner)

VALID_URL = "postgresql+psycopg://ac_runtime:staging-runtime-password-123@postgres/ac_platform"


@pytest.mark.parametrize(
    "value",
    [
        "postgresql+psycopg://ac_owner:owner-password-123456@postgres/ac_platform",
        "postgresql+psycopg://ac_migrator:migrator-password-123456@postgres/ac_platform",
        "postgresql+psycopg://ac_runtime:local-runtime-password@127.0.0.1/ac_platform",
        "postgresql+psycopg://ac_runtime:local-runtime-only@postgres/ac_platform",
        "postgresql+psycopg://ac_runtime:runtime-password-123456@other-db/ac_platform",
        "postgresql+psycopg://ac_runtime:runtime-password-123456@postgres/other_db",
        "postgresql+psycopg://ac_runtime:runtime-password-123456@postgres:5433/ac_platform",
        "postgresql+psycopg://ac_runtime:runtime-password-123456@postgres/ac_platform?sslmode=require&x=1",
        "postgresql+psycopg://ac_runtime:runtime-password-123456%ZZ@postgres/ac_platform",
        "postgresql+psycopg://ac_runtime:runtime-password-123456%FF@postgres/ac_platform",
    ],
)
def test_database_url_rejects_foreign_roles_local_values_and_hosts(value: str) -> None:
    with pytest.raises(provisioner.ProvisioningError):
        provisioner._validate_database_url(value)


def test_database_url_validation_never_echoes_secret() -> None:
    credential_fragment = "runtime-password-123456"
    value = f"postgresql+psycopg://ac_runtime:{credential_fragment}@postgres/ac_platform"
    with pytest.raises(provisioner.ProvisioningError) as error:
        provisioner._validate_database_url(value + "\n")
    assert credential_fragment not in str(error.value)


def test_database_url_accepts_the_private_postgres_port() -> None:
    provisioner._validate_database_url(
        "postgresql+psycopg://ac_runtime:runtime-password-123456@postgres:5432/ac_platform"
    )


def test_database_url_rejects_invalid_utf8_surrogate_without_echoing() -> None:
    with pytest.raises(provisioner.ProvisioningError) as error:
        provisioner._validate_database_url(
            "postgresql+psycopg://ac_runtime:runtime-password-123456@postgres/ac_platform"
            + "\ud800"
        )
    assert "runtime-password-123456" not in str(error.value)


@pytest.mark.parametrize("root", [Path("relative-root"), Path.cwd() / ".." / "unsafe"])
def test_target_path_rejects_foreign_or_traversal_root(root: Path) -> None:
    with pytest.raises(provisioner.ProvisioningError):
        provisioner._target_path("staging", root)


@pytest.fixture
def posix_root() -> Path:
    if os.name != "posix" or os.geteuid() != 0:
        pytest.skip("trusted UID/GID file provisioning requires root on POSIX")
    root = Path("/run") / f"ac-xray-db-provision-test-{os.getpid()}-{uuid4().hex}"
    root.mkdir(mode=0o700)
    try:
        yield root / "sales-xray"
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.skipif(os.name != "posix", reason="atomic ownership proof requires POSIX")
def test_provision_is_atomic_trusted_and_idempotent(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    assert (
        provisioner.provision("staging", secrets_root=posix_root, require_root=True) == "installed"
    )
    target = posix_root / "staging" / "database-url"
    first_inode = target.stat().st_ino
    assert target.read_text(encoding="utf-8") == VALID_URL
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    assert target.stat().st_uid == 10001
    assert target.stat().st_gid == 0
    assert target.stat().st_nlink == 1
    assert (
        provisioner.provision("staging", secrets_root=posix_root, require_root=True)
        == "already-present"
    )
    assert target.stat().st_ino == first_inode
    assert not list(target.parent.glob(".database-url.*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="trusted ownership proof requires POSIX")
def test_provision_refuses_differing_existing_file(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    assert (
        provisioner.provision("staging", secrets_root=posix_root, require_root=True) == "installed"
    )
    target = posix_root / "staging" / "database-url"
    target.write_bytes(b"different-runtime-credential")
    os.chown(target, 10001, 0)
    os.chmod(target, 0o400)
    with pytest.raises(provisioner.ProvisioningError):
        provisioner.provision("staging", secrets_root=posix_root, require_root=True)


@pytest.mark.skipif(os.name != "posix", reason="ancestor trust proof requires POSIX")
def test_provision_refuses_writable_existing_ancestor(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    ancestor = posix_root.parent
    original_mode = stat.S_IMODE(ancestor.stat().st_mode)
    os.chmod(ancestor, original_mode | 0o020)
    try:
        with pytest.raises(provisioner.ProvisioningError):
            provisioner.provision("staging", secrets_root=posix_root, require_root=True)
        assert not posix_root.exists()
    finally:
        os.chmod(ancestor, original_mode)


@pytest.mark.skipif(os.name != "posix", reason="ancestor trust proof requires POSIX")
def test_provision_refuses_foreign_owned_existing_ancestor(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    ancestor = posix_root.parent
    original_uid = ancestor.stat().st_uid
    original_gid = ancestor.stat().st_gid
    os.chown(ancestor, 10001, original_gid)
    try:
        with pytest.raises(provisioner.ProvisioningError):
            provisioner.provision("staging", secrets_root=posix_root, require_root=True)
        assert not posix_root.exists()
    finally:
        os.chown(ancestor, original_uid, original_gid)


@pytest.mark.skipif(os.name != "posix", reason="ancestor symlink proof requires POSIX")
def test_provision_refuses_symlinked_existing_ancestor(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    link = posix_root.parent / "linked-root"
    link.symlink_to(posix_root.parent, target_is_directory=True)
    try:
        with pytest.raises(provisioner.ProvisioningError):
            provisioner.provision("staging", secrets_root=link / "sales-xray", require_root=True)
    finally:
        link.unlink()


@pytest.mark.skipif(os.name != "posix", reason="symlink refusal proof requires POSIX")
def test_provision_refuses_symlink_target(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    parent = posix_root / "staging"
    parent.mkdir(parents=True)
    referent = posix_root.parent / "outside"
    referent.write_text("do not touch", encoding="utf-8")
    (parent / "database-url").symlink_to(referent)
    with pytest.raises(provisioner.ProvisioningError):
        provisioner.provision("staging", secrets_root=posix_root, require_root=True)
    assert referent.read_text(encoding="utf-8") == "do not touch"


@pytest.mark.skipif(os.name != "posix", reason="FIFO refusal proof requires POSIX")
def test_provision_refuses_fifo_target_without_blocking(posix_root: Path, monkeypatch) -> None:
    monkeypatch.setenv("AC_DATABASE_URL", VALID_URL)
    parent = posix_root / "staging"
    parent.mkdir(parents=True)
    target = parent / "database-url"
    os.mkfifo(target, 0o600)
    with pytest.raises(provisioner.ProvisioningError):
        provisioner.provision("staging", secrets_root=posix_root, require_root=True)


def test_cli_has_no_destination_or_url_override() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--path" not in source
    assert "--database-url" not in source
    assert "hashlib" not in source
    assert "AC_DATABASE_URL" in source
