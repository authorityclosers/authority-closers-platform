"""Actual transactional installer, isolated AC_TEST_MODE and fictional bytes only."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UPLOADER = "/usr/local/sbin/ac-db-snapshot"
LEGACY = b'#!/bin/sh\nprintf "fictional plaintext predecessor\\n"\n'


def command(argv, *, env=None, check=True):
    return subprocess.run(  # noqa: S603 - fixed test/installer command lists, no shell
        argv,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    # This is a disposable Git archive fixture, not a product checkout/branch.
    work = tmp_path_factory.mktemp("drive-install-source")
    source = work / "infra/vps-foundation"
    pin = os.environ.get("AC2138_VERIFY_COMMIT")
    if pin:
        assert re.fullmatch(r"[0-9a-f]{40}", pin)
        archive = work / "foundation.tar"
        command(
            [
                "git",
                "-C",
                str(ROOT),
                "archive",
                "--format=tar",
                "--output=" + str(archive),
                pin,
                "--",
                "infra/vps-foundation",
            ]
        )
        command(["tar", "--extract", "--file=" + str(archive), "--directory=" + str(work)])
        return source, pin, archive, hashlib.sha256(archive.read_bytes()).hexdigest()
    shutil.copytree(ROOT / "infra/vps-foundation", source)
    command(["git", "init", "-q", str(work)])
    command(["git", "-C", str(work), "add", "infra/vps-foundation"])
    command(
        [
            "git",
            "-C",
            str(work),
            "-c",
            "user.name=Fictional CI",
            "-c",
            "user.email=ci@example.invalid",
            "commit",
            "-qm",
            "Fictional installer fixture\n\nCo-Authored-By: Paperclip <noreply@paperclip.ing>",
        ]
    )
    sha = command(["git", "-C", str(work), "rev-parse", "HEAD"]).stdout.strip()
    archive = work / "foundation.tar"
    command(
        [
            "git",
            "-C",
            str(work),
            "archive",
            "--format=tar",
            "--output=" + str(archive),
            sha,
            "--",
            "infra/vps-foundation",
        ]
    )
    return source, sha, archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def fixture_host(tmp_path, package, *, predecessor=LEGACY):
    source, sha, archive, archive_sha = package
    root = tmp_path / "host"
    srv = root / "srv/authority-closers"
    base = srv / "releases/foundation-test-base"
    base.mkdir(parents=True)
    (base / "RELEASE-ID").write_text("foundation-test-base\n")
    (base / "RELEASE-COMMIT").write_text("1" * 40 + "\n")
    (base / "RELEASE-FILES.sha256").write_text(
        "".join(
            hashlib.sha256((base / name).read_bytes()).hexdigest() + "  " + name + "\n"
            for name in ["RELEASE-ID", "RELEASE-COMMIT"]
        )
    )
    (srv / "current").symlink_to(base)
    (srv / "application").mkdir()
    (srv / "application/unchanged").write_text("fictional application file")
    units = root / "etc/systemd/system"
    units.mkdir(parents=True)
    (units / "fictional-existing.timer").write_text("no changes")
    marker = tmp_path / "host-actions"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ["docker", "systemctl", "curl", "infisical", "rclone"]:
        path = bin_dir / tool
        path.write_text("#!/bin/sh\nprintf blocked >> " + str(marker) + "\nexit 88\n")
        path.chmod(0o700)
    uploader = root / UPLOADER.lstrip("/")
    if predecessor is not None:
        uploader.parent.mkdir(parents=True)
        uploader.write_bytes(predecessor)
        uploader.chmod(0o750)
    env = {key: os.environ[key] for key in ["PATH", "HOME", "LANG"] if key in os.environ}
    env.update(
        {
            "PATH": str(bin_dir) + ":" + env["PATH"],
            "AC_TEST_MODE": "1",
            "AC_INSTALL_SCOPE": "drive-backup",
            "AC_INSTALL_ROOT": str(root),
            "AC_RELEASE_ID": "foundation-test-drive",
            "AC_RELEASE_GIT_SHA": sha,
            "AC_RELEASE_ARCHIVE": str(archive),
            "AC_RELEASE_ARCHIVE_SHA256": archive_sha,
            "AC_DRIVE_ADMITTED_SOURCE_SHA": sha,
            "AC_DRIVE_EXPECTED_UPLOADER_SHA256": hashlib.sha256(predecessor).hexdigest()
            if predecessor is not None
            else "absent",
            "AC_TEST_DRIVE_LEGACY_SHA256": hashlib.sha256(LEGACY).hexdigest(),
        }
    )
    return root, uploader, marker, env


def install(package, env):
    return command(
        ["bash", str(package[0] / "scripts/install-foundation-release.sh")], env=env, check=False
    )


def unchanged(root, marker, *, check_unit_set=True):
    assert (root / "srv/authority-closers/current").resolve().name == "foundation-test-base"
    assert (
        root / "srv/authority-closers/application/unchanged"
    ).read_text() == "fictional application file"
    assert (root / "etc/systemd/system/fictional-existing.timer").read_text() == "no changes"
    if check_unit_set:
        assert len(list((root / "etc/systemd/system").iterdir())) == 1
    assert not marker.exists()


@pytest.mark.parametrize("missing", ["admission", "predecessor", "legacy_policy"])
def test_refuses_unadmitted_drift_or_unreviewed_plaintext_rollback(tmp_path, package, missing):
    root, uploader, marker, env = fixture_host(tmp_path, package)
    if missing == "admission":
        env.pop("AC_DRIVE_ADMITTED_SOURCE_SHA")
    elif missing == "predecessor":
        env["AC_DRIVE_EXPECTED_UPLOADER_SHA256"] = "0" * 64
    result = install(package, env)
    assert result.returncode != 0
    assert uploader.read_bytes() == LEGACY
    unchanged(root, marker)


@pytest.mark.parametrize("failure", ["AC_TEST_FAIL_AFTER_INSTALL", "AC_TEST_FAIL_AFTER_ACTIVATE"])
def test_legacy_failure_never_restores_plaintext_and_leaves_fixed_guard(tmp_path, package, failure):
    root, uploader, marker, env = fixture_host(tmp_path, package)
    env.update({"AC_DRIVE_LEGACY_FAILURE_POLICY": "disabled", failure: "1"})
    result = install(package, env)
    assert result.returncode != 0
    assert "CONTAINED" in result.stderr
    assert uploader.read_bytes() == (package[0] / "scripts/drive-backup-disabled").read_bytes()
    assert uploader.stat().st_mode & 0o777 == 0o750
    disabled = command(["bash", str(uploader)], check=False)
    assert disabled.returncode == 1
    assert "operator recovery required" in disabled.stderr
    assert not (root / "var/lib/authority-closers/foundation-scopes/drive-backup.release").exists()
    unchanged(root, marker)


def test_success_selects_only_reviewed_manifest_without_activation(tmp_path, package):
    root, uploader, marker, env = fixture_host(tmp_path, package)
    env["AC_DRIVE_LEGACY_FAILURE_POLICY"] = "disabled"
    result = install(package, env)
    assert result.returncode == 0, result.stderr
    manifest = package[0] / "config/release/install-manifest-drive-backup.tsv"
    for line in manifest.read_text().splitlines():
        if line.startswith("#"):
            continue
        kind, source, target, mode, owner, group = line.split("\t")
        installed = root / target.lstrip("/")
        assert installed.read_bytes() == (package[0] / source).read_bytes()
        assert installed.stat().st_mode & 0o777 == int(mode, 8)
        assert (owner, group) == ("root", "root")
    assert (
        root / "var/lib/authority-closers/foundation-scopes/drive-backup.release"
    ).read_text().strip() == "foundation-test-drive"
    unchanged(root, marker)


def test_reviewed_safe_predecessor_rolls_back_bytes_and_mode(tmp_path, package):
    safe = b"#!/bin/sh\n# fictional encrypted predecessor\nexit 1\n"
    root, uploader, marker, env = fixture_host(tmp_path, package, predecessor=safe)
    uploader.chmod(0o700)
    env.update(
        {
            "AC_DRIVE_SAFE_PREDECESSOR_SHA256": hashlib.sha256(safe).hexdigest(),
            "AC_TEST_FAIL_AFTER_INSTALL": "1",
        }
    )
    result = install(package, env)
    assert result.returncode != 0
    assert uploader.read_bytes() == safe
    assert uploader.stat().st_mode & 0o777 == 0o700
    unchanged(root, marker)


def test_first_install_rollback_removes_new_targets(tmp_path, package):
    root, uploader, marker, env = fixture_host(tmp_path, package, predecessor=None)
    env["AC_TEST_FAIL_AFTER_INSTALL"] = "1"
    result = install(package, env)
    assert result.returncode != 0
    assert not uploader.exists()
    unchanged(root, marker)


def test_ordinary_backup_scope_does_not_select_drive_source(tmp_path, package):
    root, uploader, marker, env = fixture_host(tmp_path, package)
    env["AC_INSTALL_SCOPE"] = "backup"
    env.pop("AC_DRIVE_ADMITTED_SOURCE_SHA")
    assert install(package, env).returncode == 0
    assert uploader.read_bytes() == LEGACY
    assert not (root / "usr/local/libexec/authority-closers/drive_postgres_backup.py").exists()
    unchanged(root, marker, check_unit_set=False)


def test_shared_release_lock_refuses_overlap(tmp_path, package):
    root, uploader, marker, env = fixture_host(tmp_path, package)
    path = root / "srv/authority-closers/application/.deployment.lock"
    with path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = install(package, env)
    assert result.returncode != 0
    assert "already active" in result.stderr
    assert uploader.read_bytes() == LEGACY
    unchanged(root, marker)
