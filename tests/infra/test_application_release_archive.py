from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Iterable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
VERIFIER = APPLICATION / "scripts" / "verify-release-archive.py"
INSTALLER = APPLICATION / "scripts" / "install-application-release.sh"

REQUIRED_FILES = (
    "infra/application/compose.yaml",
    "infra/application/environments/staging.env",
    "infra/application/environments/production.env",
    "infra/application/scripts/install-application-release.sh",
    "infra/application/scripts/verify-release-archive.py",
)
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _archive_sha256(archive_path: Path) -> str:
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def _add_directory(archive: tarfile.TarFile, name: str) -> None:
    entry = tarfile.TarInfo(name)
    entry.mode = 0o755
    entry.mtime = 0
    entry.type = tarfile.DIRTYPE
    archive.addfile(entry)


def _add_member(
    archive: tarfile.TarFile,
    name: str,
    payload: bytes = b"",
    *,
    member_type: bytes = tarfile.REGTYPE,
    linkname: str = "",
) -> None:
    entry = tarfile.TarInfo(name)
    entry.mode = 0o644
    entry.mtime = 0
    entry.type = member_type
    entry.linkname = linkname
    if member_type == tarfile.REGTYPE:
        entry.size = len(payload)
        archive.addfile(entry, io.BytesIO(payload))
        return
    archive.addfile(entry)


def _write_fixture_archive(
    archive_path: Path,
    *,
    commit: str = COMMIT,
    without: Iterable[str] = (),
    extra_members: Iterable[dict[str, object]] = (),
    embedded_verifier: bytes | None = None,
) -> None:
    omitted = set(without)
    contents = {name: f"synthetic release fixture: {name}\n".encode() for name in REQUIRED_FILES}
    contents["infra/application/scripts/verify-release-archive.py"] = (
        VERIFIER.read_bytes() if embedded_verifier is None else embedded_verifier
    )

    with tarfile.open(
        archive_path,
        mode="w",
        format=tarfile.PAX_FORMAT,
        pax_headers={"comment": commit},
    ) as archive:
        _add_directory(archive, "infra")
        _add_directory(archive, "infra/application")
        for name, payload in contents.items():
            if name not in omitted:
                _add_member(archive, name, payload)
        for member in extra_members:
            _add_member(archive, **member)


def _run_verifier(
    archive_path: Path, expected_sha256: str, expected_commit: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [sys.executable, str(VERIFIER), str(archive_path), expected_sha256, expected_commit],
        capture_output=True,
        check=False,
        text=True,
    )


def _git_archive_fixture(tmp_path: Path) -> tuple[Path, str]:
    git = shutil.which("git")
    if git is None:
        pytest.fail("git is required to produce a commit-bound release fixture")

    repository = tmp_path / "release-repository"
    repository.mkdir()
    for name in REQUIRED_FILES:
        destination = repository / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            VERIFIER.read_bytes()
            if name.endswith("verify-release-archive.py")
            else (f"synthetic release fixture: {name}\n".encode())
        )
        destination.write_bytes(payload)

    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "init", "--quiet"],
        check=True,
    )
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "config", "user.name", "Authority Closers Test"],
        check=True,
    )
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "config", "user.email", "test@authorityclosers.invalid"],
        check=True,
    )
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "add", "infra/application"],
        check=True,
    )
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "commit", "--quiet", "-m", "synthetic release fixture"],
        check=True,
    )
    commit = subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [git, "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    archive_path = tmp_path / "valid-release.tar"
    subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [
            git,
            "-C",
            str(repository),
            "archive",
            "--format=tar",
            f"--output={archive_path}",
            commit,
            "--",
            "infra/application",
        ],
        check=True,
    )
    return archive_path, commit


def test_accepts_valid_git_commit_bound_archive(tmp_path: Path) -> None:
    archive_path, commit = _git_archive_fixture(tmp_path)

    result = _run_verifier(archive_path, _archive_sha256(archive_path), commit)

    assert result.returncode == 0, result.stderr
    assert f"PASS  Application archive is path-safe and commit-bound to {commit}." in result.stdout


def test_rejects_archive_with_wrong_sha256(tmp_path: Path) -> None:
    archive_path = tmp_path / "wrong-sha.tar"
    _write_fixture_archive(archive_path)

    result = _run_verifier(archive_path, "0" * 64, COMMIT)

    assert result.returncode != 0
    assert "release archive SHA-256 does not match" in result.stderr


def test_rejects_archive_with_wrong_commit_marker(tmp_path: Path) -> None:
    archive_path = tmp_path / "wrong-commit.tar"
    _write_fixture_archive(archive_path)

    result = _run_verifier(archive_path, _archive_sha256(archive_path), "f" * 40)

    assert result.returncode != 0
    assert "Git archive commit does not match the release ID" in result.stderr


@pytest.mark.parametrize("unsafe_name", ["../escape", "infra/application/../../escape", "/outside"])
def test_rejects_path_traversal_or_absolute_archive_member(
    tmp_path: Path, unsafe_name: str
) -> None:
    archive_path = tmp_path / "unsafe-path.tar"
    _write_fixture_archive(
        archive_path,
        extra_members=[{"name": unsafe_name, "payload": b"escape"}],
    )

    result = _run_verifier(archive_path, _archive_sha256(archive_path), COMMIT)

    assert result.returncode != 0
    assert "release archive contains an unsafe path" in result.stderr


def test_rejects_unexpected_archive_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "unexpected-path.tar"
    _write_fixture_archive(
        archive_path,
        extra_members=[{"name": "infra/secret.txt", "payload": b"unexpected"}],
    )

    result = _run_verifier(archive_path, _archive_sha256(archive_path), COMMIT)

    assert result.returncode != 0
    assert "release archive contains an unexpected path" in result.stderr


def test_rejects_non_regular_archive_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "non-regular.tar"
    _write_fixture_archive(
        archive_path,
        extra_members=[
            {
                "name": "infra/application/link",
                "member_type": tarfile.SYMTYPE,
                "linkname": "compose.yaml",
            }
        ],
    )

    result = _run_verifier(archive_path, _archive_sha256(archive_path), COMMIT)

    assert result.returncode != 0
    assert "release archive contains a non-regular entry" in result.stderr


@pytest.mark.parametrize("missing_file", REQUIRED_FILES)
def test_rejects_archive_missing_required_file(tmp_path: Path, missing_file: str) -> None:
    archive_path = tmp_path / "missing-required-file.tar"
    _write_fixture_archive(archive_path, without=[missing_file])

    result = _run_verifier(archive_path, _archive_sha256(archive_path), COMMIT)

    assert result.returncode != 0
    assert f"release archive is missing required files: {missing_file}" in result.stderr


def test_rejects_archive_with_mismatched_embedded_verifier(tmp_path: Path) -> None:
    archive_path = tmp_path / "mismatched-verifier.tar"
    _write_fixture_archive(archive_path, embedded_verifier=VERIFIER.read_bytes() + b"\n# tampered")

    result = _run_verifier(archive_path, _archive_sha256(archive_path), COMMIT)

    assert result.returncode != 0
    assert "trusted verifier differs from the verifier in the exact-commit archive" in result.stderr


def test_installer_verifies_archive_before_extracting_and_rejects_unsafe_inputs() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    verify_call = 'python3 "$script_dir/verify-release-archive.py"'
    extract_call = 'tar --extract --file="$release_archive"'

    # This is the installer boundary that prevents a crafted archive from reaching tar.
    assert verify_call in installer
    assert installer.index(verify_call) < installer.index(extract_call)
    assert '[[ "$release_archive" == /* && -f "$release_archive" ]]' in installer
    assert (
        '[[ "$image_bundle_dir" == /* && -d "$image_bundle_dir" && ! -L "$image_bundle_dir" ]]'
        in installer
    )
    assert 'find "$image_bundle_dir" -mindepth 1 -maxdepth 1 -type f -printf' in installer
    assert 'sha256sum "$image_bundle_dir/$filename"' in installer
    assert '[[ "$registry_digest" =~ ^ghcr\\.io/authorityclosers/' in installer


def test_installer_arms_rollback_before_starting_candidate_postgres() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    rollback_arm = "mutation_started=1"
    postgres_start = 'compose_for "$release_dir" up --detach --wait --wait-timeout 180 postgres'

    assert installer.index(rollback_arm) < installer.index(postgres_start)


def test_installer_restores_current_link_and_writes_evidence_atomically() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    advance = 'mv --no-target-directory --force "$current_tmp" "$current_link"'
    mark_advanced = "current_advanced=1"
    restore_call = "restore_current_link || rollback_failed=1"
    restart_previous = 'compose_for "$previous_release" up --detach'
    evidence_temp = 'evidence_tmp="$(mktemp "$evidence_root/.deployment-${release_id}.XXXXXX")"'
    evidence_commit = 'mv --no-target-directory "$evidence_tmp" "$evidence_file"'
    mark_committed = "release_committed=1"

    assert installer.index(advance) < installer.index(mark_advanced)
    rollback_body = installer[installer.index("rollback_release() {") :]
    assert rollback_body.index(restore_call) < rollback_body.index(restart_previous)
    assert installer.index(evidence_temp) < installer.index(evidence_commit)
    assert installer.index(evidence_commit) < installer.index(mark_committed)
