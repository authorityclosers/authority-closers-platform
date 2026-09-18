from __future__ import annotations

import hashlib
import io
import shlex
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
PREPARER = APPLICATION / "scripts" / "prepare-release-inputs.py"

REQUIRED_FILES = (
    "infra/application/compose.yaml",
    "infra/application/compose.filesystem-media.yaml",
    "infra/application/compose.staging-public-films.yaml",
    "infra/application/capabilities/staging-public-films.json",
    "infra/application/data/alpha_public_films_12s_v1.json",
    "infra/application/compose.public-films.yaml",
    "infra/application/capabilities/public-films.json",
    "infra/application/data/public_films_technical_demo_12s_v1.json",
    "infra/application/edge-routes/production-hold.caddy",
    "infra/application/edge-routes/production.caddy",
    "infra/application/edge-routes/staging-hold.caddy",
    "infra/application/edge-routes/staging.caddy",
    "infra/application/scripts/public-films.py",
    "infra/application/scripts/studio-video-upload.py",
    "infra/application/environments/staging.env",
    "infra/application/environments/production.env",
    "infra/application/scripts/install-application-release.sh",
    "infra/application/scripts/install-sales-xray-startup-recovery.py",
    "infra/application/scripts/prepare-release-inputs.py",
    "infra/application/scripts/recover-sales-xray-startup.py",
    "infra/application/scripts/restore-drill.py",
    "infra/application/scripts/staging-public-films.py",
    "infra/application/scripts/validate-google-oauth-secrets.py",
    "infra/application/scripts/verify-release-archive.py",
)
COMMIT = "0123456789abcdef0123456789abcdef01234567"
IMAGE_VALUES = {
    "AC_ADMIN_IMAGE": "sha256:" + "1" * 64,
    "AC_ADMIN_REGISTRY_DIGEST": (
        "ghcr.io/authorityclosers/authority-closers-admin-web@sha256:" + "b" * 64
    ),
    "AC_ADMIN_TRANSPORT_DIGEST": "sha256:" + "1" * 64,
    "AC_API_IMAGE": "sha256:" + "2" * 64,
    "AC_API_REGISTRY_DIGEST": ("ghcr.io/authorityclosers/authority-closers-api@sha256:" + "d" * 64),
    "AC_API_TRANSPORT_DIGEST": "sha256:" + "2" * 64,
    "AC_COACH_IMAGE": "sha256:" + "4" * 64,
    "AC_COACH_REGISTRY_DIGEST": (
        "ghcr.io/authorityclosers/authority-closers-coach-web@sha256:" + "a" * 64
    ),
    "AC_COACH_TRANSPORT_DIGEST": "sha256:" + "4" * 64,
    "AC_LEARNER_IMAGE": "sha256:" + "3" * 64,
    "AC_LEARNER_REGISTRY_DIGEST": (
        "ghcr.io/authorityclosers/authority-closers-learner-web@sha256:" + "f" * 64
    ),
    "AC_LEARNER_TRANSPORT_DIGEST": "sha256:" + "3" * 64,
    "AC_MIGRATION_HEAD": "20000101_0001",
    "AC_RELEASE_ID": COMMIT,
}


def _archive_sha256(archive_path: Path) -> str:
    return hashlib.sha256(archive_path.read_bytes()).hexdigest()


def _write_image_bundle(bundle: Path, values: dict[str, str] | None = None) -> None:
    bundle.mkdir()
    manifest_values = IMAGE_VALUES if values is None else values
    manifest = bundle / "release-images.env"
    manifest.write_bytes(
        "".join(f"{key}={manifest_values[key]}\n" for key in sorted(manifest_values)).encode(
            "ascii"
        )
    )
    images = bundle / "application-images.tar.gz"
    images.write_bytes(b"reviewed image transport fixture")
    (bundle / "SHA256SUMS").write_bytes(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (images, manifest)
        ).encode("ascii")
    )


def _refresh_bundle_checksums(bundle: Path) -> None:
    images = bundle / "application-images.tar.gz"
    manifest = bundle / "release-images.env"
    (bundle / "SHA256SUMS").write_bytes(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (images, manifest)
        ).encode("ascii")
    )


def _run_preparer(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - executable and arguments are test-controlled
        [sys.executable, str(PREPARER), *(str(argument) for argument in arguments)],
        capture_output=True,
        check=False,
        text=True,
    )


def _bash_executable() -> str:
    git = shutil.which("git")
    candidates = []
    if git is not None and sys.platform == "win32":
        candidates.append(Path(git).parent.parent / "bin" / "bash.exe")
    discovered = shutil.which("bash")
    if discovered is not None:
        candidates.append(Path(discovered))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    pytest.fail("Bash is required for installer finalizer tests")


def _installer_function(name: str, next_marker: str) -> str:
    installer = INSTALLER.read_text(encoding="utf-8")
    start = installer.index(f"{name}() {{")
    return installer[start : installer.index(next_marker, start)]


def _run_finalizer_harness(
    tmp_path: Path,
    *,
    exit_status: int,
    mutation_started: bool,
    release_committed: bool,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    application_root = tmp_path / "application"
    releases_root = application_root / "releases"
    artifacts_root = application_root / "artifacts"
    input_stage = application_root / ".inputs-fixture.123456"
    stage_dir = releases_root / ".stage-fixture.123456"
    artifact_stage = artifacts_root / ".stage-fixture.123456"
    rollback_marker = tmp_path / "rollback-observed-stages"
    cleanup = _installer_function("cleanup_stages", "\n\nfinish_before_mutation()")
    finish = _installer_function("finish", "\ntrap finish EXIT")
    quoted = {
        "application_root": shlex.quote(application_root.as_posix()),
        "releases_root": shlex.quote(releases_root.as_posix()),
        "artifacts_root": shlex.quote(artifacts_root.as_posix()),
        "input_stage": shlex.quote(input_stage.as_posix()),
        "stage_dir": shlex.quote(stage_dir.as_posix()),
        "artifact_stage": shlex.quote(artifact_stage.as_posix()),
        "rollback_marker": shlex.quote(rollback_marker.as_posix()),
    }
    harness = tmp_path / "finalizer-harness.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -uo pipefail
application_root={quoted["application_root"]}
releases_root={quoted["releases_root"]}
artifacts_root={quoted["artifacts_root"]}
input_stage={quoted["input_stage"]}
stage_dir={quoted["stage_dir"]}
artifact_stage={quoted["artifact_stage"]}
mkdir -p "$input_stage" "$stage_dir" "$artifact_stage"
{cleanup}
rollback_release() {{
  [[ -d "$input_stage" && -d "$stage_dir" && -d "$artifact_stage" ]] || return 1
  printf 'rollback-before-cleanup\n' > {quoted["rollback_marker"]}
}}
record_forward_recovery_required() {{ return 99; }}
{finish}
mutation_started={int(mutation_started)}
release_committed={int(release_committed)}
write_exposure_started=0
trap finish EXIT
exit {exit_status}
""",
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(  # noqa: S603 - executable and script are test-controlled
        [_bash_executable(), str(harness)],
        capture_output=True,
        check=False,
        text=True,
    )
    return result, rollback_marker


def _run_pre_mutation_finalizer_harness(
    tmp_path: Path,
    *,
    exit_status: int,
) -> subprocess.CompletedProcess[str]:
    application_root = tmp_path / "application"
    releases_root = application_root / "releases"
    artifacts_root = application_root / "artifacts"
    input_stage = application_root / ".inputs-fixture.123456"
    stage_dir = releases_root / ".stage-fixture.123456"
    artifact_stage = artifacts_root / ".stage-fixture.123456"
    cleanup = _installer_function("cleanup_stages", "\n\nfinish_before_mutation()")
    early_finish = _installer_function(
        "finish_before_mutation", "\ntrap finish_before_mutation EXIT"
    )
    paths = {
        "application_root": application_root,
        "releases_root": releases_root,
        "artifacts_root": artifacts_root,
        "input_stage": input_stage,
        "stage_dir": stage_dir,
        "artifact_stage": artifact_stage,
    }
    assignments = "\n".join(
        f"{name}={shlex.quote(path.as_posix())}" for name, path in paths.items()
    )
    harness = tmp_path / "pre-mutation-finalizer-harness.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -uo pipefail
{assignments}
mkdir -p "$input_stage" "$stage_dir" "$artifact_stage"
{cleanup}
{early_finish}
trap finish_before_mutation EXIT
exit {exit_status}
""",
        encoding="utf-8",
        newline="\n",
    )
    return subprocess.run(  # noqa: S603 - executable and script are test-controlled
        [_bash_executable(), str(harness)],
        capture_output=True,
        check=False,
        text=True,
    )


def _run_rollback_harness(
    tmp_path: Path,
    *,
    fail_stage: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    rollback = _installer_function("rollback_release", "\n\ncontain_forward_recovery() {")
    hosted_helpers = "\n".join(
        (
            _installer_function(
                "load_sales_xray_hosted_inputs", "\n\nsales_xray_hosted_enabled() {"
            ),
            _installer_function(
                "sales_xray_hosted_enabled", "\n\nstop_hosted_sales_xray_worker() {"
            ),
            _installer_function(
                "stop_hosted_sales_xray_worker",
                "\n\nstop_application_services_with_hosted_drain() {",
            ),
            _installer_function(
                "stop_application_services_with_hosted_drain", "\n\ncompose_for() {"
            ),
        )
    )
    events = tmp_path / "rollback-events"
    backup = tmp_path / "pre-migration.dump"
    backup.write_bytes(b"PGDMP fixture")
    values = {
        "events": events,
        "backup": backup,
        "release_dir": tmp_path / "candidate-release",
        "previous_release": tmp_path / "previous-release",
    }
    assignments = "\n".join(
        f"{name}={shlex.quote(path.as_posix())}" for name, path in values.items()
    )
    failure = shlex.quote(fail_stage or "none")
    harness = tmp_path / f"rollback-{fail_stage or 'success'}-harness.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -uo pipefail
{assignments}
fail_stage={failure}
target_environment=staging
release_id={"a" * 40}
current_tmp=''
  evidence_tmp=''
  attempt_tmp=''
  backup_file="$backup"
  backup_ready=1
  database_mutation_started=1
  write_exposure_started=0

# Both rollback targets model a release without the optional hosted capability.
# The real loader returns status 1 for this disabled policy, so no hosted
# worker drain or provider inputs are admitted.
mkdir -p "$release_dir/capabilities" "$previous_release/capabilities"
sales_xray_hosted_inputs=()
with_release_secrets() {{ "$@"; }}

{hosted_helpers}

compose_for() {{
  if [[ "$*" == *"stop --timeout 30 api worker"* ]]; then
    printf 'compose:stop-core\n' >> "$events"
    return 0
  fi
  if [[ "$*" == *"stop --timeout 30 learner-web admin-web coach-web"* ]]; then
    printf 'compose:stop-web\n' >> "$events"
    return 0
  fi
  if [[ "$*" == *"pg_restore"* ]]; then
    printf 'compose:restore\n' >> "$events"
    [[ "$fail_stage" != restore ]]
    return
  fi
  if [[ "$*" == *"up --detach --remove-orphans --wait --wait-timeout 180"* ]]; then
    printf 'compose:restart\n' >> "$events"
    return 0
  fi
  printf 'compose:unexpected:%s\n' "$*" >> "$events"
  return 0
}}

set_database_writer_access() {{
  printf 'access:%s\n' "$1" >> "$events"
  if [[ "$1" == runtime && "$fail_stage" == runtime ]]; then
    return 1
  fi
  return 0
}}

restore_current_link() {{
  printf 'link:restore\n' >> "$events"
}}

restore_edge_route() {{
  printf 'edge:restore\n' >> "$events"
  [[ "$fail_stage" != edge ]]
}}

{rollback}
rollback_release
""",
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(  # noqa: S603 - executable and script are test-controlled
        [_bash_executable(), str(harness)],
        capture_output=True,
        check=False,
        text=True,
    )
    observed = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
    return result, observed


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


def test_private_staging_breaks_caller_replacement_after_verification(tmp_path: Path) -> None:
    archive_path, commit = _git_archive_fixture(tmp_path)
    bundle = tmp_path / "image-bundle"
    trusted_values = dict(IMAGE_VALUES)
    trusted_values["AC_RELEASE_ID"] = commit
    _write_image_bundle(bundle, trusted_values)
    staged = tmp_path / "private-inputs"
    staged.mkdir(mode=0o700)

    stage_result = _run_preparer("stage", archive_path, bundle, staged)
    assert stage_result.returncode == 0, stage_result.stderr
    staged_archive = staged / "release-archive.tar"
    staged_bundle = staged / "image-bundle"
    staged_archive_sha256 = _archive_sha256(staged_archive)
    verifier_result = _run_verifier(staged_archive, staged_archive_sha256, commit)
    assert verifier_result.returncode == 0, verifier_result.stderr

    archive_path.write_bytes(b"caller replaced archive after verification")
    (bundle / "application-images.tar.gz").write_bytes(b"caller replaced image transport")
    injected_values = dict(IMAGE_VALUES)
    injected_values["AC_API_IMAGE"] = "sha256:" + "9" * 64
    (bundle / "release-images.env").write_text(
        "".join(f"{key}={injected_values[key]}\n" for key in sorted(injected_values)),
        encoding="ascii",
    )

    bundle_result = _run_preparer("verify-bundle", staged_bundle, commit)
    assert bundle_result.returncode == 0, bundle_result.stderr
    assert bundle_result.stdout.splitlines() == [
        trusted_values[key] for key in sorted(trusted_values)
    ]
    assert _archive_sha256(staged_archive) == staged_archive_sha256
    assert (staged_bundle / "application-images.tar.gz").read_bytes() == (
        b"reviewed image transport fixture"
    )


def test_manifest_shell_syntax_is_rejected_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "shell-injection-executed"
    values = dict(IMAGE_VALUES)
    values["AC_API_IMAGE"] = f"$(touch${{IFS}}{marker.as_posix()})"
    bundle = tmp_path / "malicious-bundle"
    _write_image_bundle(bundle, values)

    result = _run_preparer("verify-bundle", bundle, COMMIT)

    assert result.returncode != 0
    assert "AC_API_IMAGE" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "wrong-repository",
        "runtime-mismatch",
        "coach-missing",
        "coach-repository",
        "coach-mismatch",
    ],
)
def test_manifest_requires_exact_keys_and_key_specific_values(
    tmp_path: Path,
    mutation: str,
) -> None:
    values = dict(IMAGE_VALUES)
    if mutation == "missing":
        del values["AC_MIGRATION_HEAD"]
    elif mutation == "extra":
        values["AC_UNREVIEWED"] = "value"
    elif mutation == "wrong-repository":
        values["AC_ADMIN_REGISTRY_DIGEST"] = values["AC_API_REGISTRY_DIGEST"]
    elif mutation == "runtime-mismatch":
        values["AC_API_IMAGE"] = "sha256:" + "9" * 64
    elif mutation == "coach-missing":
        del values["AC_COACH_IMAGE"]
    elif mutation == "coach-repository":
        values["AC_COACH_REGISTRY_DIGEST"] = values["AC_ADMIN_REGISTRY_DIGEST"]
    elif mutation == "coach-mismatch":
        values["AC_COACH_IMAGE"] = "sha256:" + "9" * 64
    bundle = tmp_path / f"malformed-{mutation}"
    _write_image_bundle(bundle, values)
    if mutation == "duplicate":
        manifest = bundle / "release-images.env"
        manifest.write_bytes(manifest.read_bytes() + f"AC_RELEASE_ID={COMMIT}\n".encode("ascii"))
        _refresh_bundle_checksums(bundle)

    result = _run_preparer("verify-bundle", bundle, COMMIT)

    assert result.returncode != 0
    assert "release image manifest" in result.stderr


def test_staging_refuses_symlink_inputs(tmp_path: Path) -> None:
    archive_path, _commit = _git_archive_fixture(tmp_path)
    bundle = tmp_path / "image-bundle"
    _write_image_bundle(bundle)
    archive_link = tmp_path / "release-link.tar"
    try:
        archive_link.symlink_to(archive_path)
    except OSError:
        pytest.skip("this host does not permit an unprivileged symlink fixture")
    staged = tmp_path / "private-inputs"
    staged.mkdir(mode=0o700)

    result = _run_preparer("stage", archive_link, bundle, staged)

    assert result.returncode != 0
    assert "regular non-symlink" in result.stderr


def test_staging_refuses_symlink_bundle_directory(tmp_path: Path) -> None:
    archive_path, _commit = _git_archive_fixture(tmp_path)
    bundle = tmp_path / "image-bundle"
    _write_image_bundle(bundle)
    bundle_link = tmp_path / "image-bundle-link"
    try:
        bundle_link.symlink_to(bundle, target_is_directory=True)
    except OSError:
        pytest.skip("this host does not permit an unprivileged symlink fixture")
    staged = tmp_path / "private-inputs"
    staged.mkdir(mode=0o700)

    result = _run_preparer("stage", archive_path, bundle_link, staged)

    assert result.returncode != 0
    assert "image bundle must be a non-symlink directory" in result.stderr


def test_staging_refuses_symlink_bundle_member(tmp_path: Path) -> None:
    archive_path, _commit = _git_archive_fixture(tmp_path)
    bundle = tmp_path / "image-bundle"
    _write_image_bundle(bundle)
    manifest = bundle / "release-images.env"
    manifest_target = tmp_path / "release-images-target.env"
    manifest_target.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(manifest_target)
    except OSError:
        pytest.skip("this host does not permit an unprivileged symlink fixture")
    staged = tmp_path / "private-inputs"
    staged.mkdir(mode=0o700)

    result = _run_preparer("stage", archive_path, bundle, staged)

    assert result.returncode != 0
    assert "image bundle contains a non-regular entry" in result.stderr


def test_installer_verifies_archive_before_extracting_and_rejects_unsafe_inputs() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    stage_call = 'python3 "$script_dir/prepare-release-inputs.py" stage'
    verify_call = 'python3 "$script_dir/verify-release-archive.py"'
    extract_call = 'tar --extract --file="$release_archive"'

    # Caller-owned inputs are consumed only by the stable-copy boundary.
    assert stage_call in installer
    assert installer.index(stage_call) < installer.index(verify_call)
    assert verify_call in installer
    assert installer.index(verify_call) < installer.index(extract_call)
    assert (
        '[[ "$release_archive" == /* && -f "$release_archive" && ! -L "$release_archive" ]]'
        in installer
    )
    assert (
        '[[ "$image_bundle_dir" == /* && -d "$image_bundle_dir" && ! -L "$image_bundle_dir" ]]'
        in installer
    )
    assert 'release_archive="$input_stage/release-archive.tar"' in installer
    assert 'image_bundle_dir="$input_stage/image-bundle"' in installer
    assert 'source "$release_images_file"' not in installer
    assert "eval " not in installer
    assert 'python3 "$script_dir/prepare-release-inputs.py" verify-bundle' in installer
    assert 'AC_API_IMAGE="${release_image_values[3]}"' in installer
    assert 'AC_API_TRANSPORT_DIGEST="${release_image_values[5]}"' in installer
    assert 'cp -- "$image_bundle_dir/$filename" "$artifact_stage/$filename"' in installer
    assert 'image_bundle_dir="$artifact_dir"' not in installer
    assert 'gzip --decompress --stdout "$image_bundle_dir/application-images.tar.gz"' in installer
    assert "-u AC_INTERNAL_API_HOST" in installer


def test_installer_cleans_private_inputs_on_preflight_failure_and_final_exit() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    early_finish = installer[
        installer.index("finish_before_mutation() {") : installer.index(
            "trap finish_before_mutation EXIT"
        )
    ]
    finish_start = installer.index("finish() {")
    final_finish = installer[finish_start : installer.index("trap finish EXIT", finish_start)]

    assert 'mktemp -d "$application_root/.inputs-${release_id}.XXXXXX"' in installer
    # The leading special-bit digit is required on GNU chmod: a plain 0700
    # preserves setgid inherited from the application root and produces 2700.
    assert 'chmod 00700 "$input_stage"' in installer
    assert 'chmod 0700 "$input_stage"' not in installer
    assert 'chown root:root "$input_stage"' in installer
    assert "cleanup_stages" in early_finish
    assert "cleanup_stages" in final_finish
    assert "trap '' HUP INT TERM" in early_finish
    assert final_finish.index("rollback_release") < final_finish.index("cleanup_stages")


def test_installer_finalizer_removes_private_stages_on_success(tmp_path: Path) -> None:
    result, rollback_marker = _run_finalizer_harness(
        tmp_path,
        exit_status=0,
        mutation_started=True,
        release_committed=True,
    )

    assert result.returncode == 0, result.stderr
    assert not rollback_marker.exists()
    assert not list((tmp_path / "application").glob(".inputs-*"))
    assert not list((tmp_path / "application" / "releases").glob(".stage-*"))
    assert not list((tmp_path / "application" / "artifacts").glob(".stage-*"))


def test_installer_pre_mutation_finalizer_removes_private_stages_and_preserves_failure(
    tmp_path: Path,
) -> None:
    result = _run_pre_mutation_finalizer_harness(tmp_path, exit_status=29)

    assert result.returncode == 29, result.stderr
    assert not list((tmp_path / "application").glob(".inputs-*"))
    assert not list((tmp_path / "application" / "releases").glob(".stage-*"))
    assert not list((tmp_path / "application" / "artifacts").glob(".stage-*"))


def test_installer_finalizer_rolls_back_then_removes_stages_and_preserves_failure(
    tmp_path: Path,
) -> None:
    result, rollback_marker = _run_finalizer_harness(
        tmp_path,
        exit_status=37,
        mutation_started=True,
        release_committed=False,
    )

    assert result.returncode == 37, result.stderr
    assert rollback_marker.read_text(encoding="utf-8") == "rollback-before-cleanup\n"
    assert not list((tmp_path / "application").glob(".inputs-*"))
    assert not list((tmp_path / "application" / "releases").glob(".stage-*"))
    assert not list((tmp_path / "application" / "artifacts").glob(".stage-*"))


def test_installer_arms_rollback_before_starting_candidate_postgres() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    rollback_arm = "mutation_started=1"
    postgres_start = 'compose_for "$release_dir" up --detach --wait --wait-timeout 180 postgres'

    assert installer.index(rollback_arm) < installer.index(postgres_start)


def test_installer_quiesces_writers_before_dump_and_reopens_connect_by_phase() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    writer_access = _installer_function(
        "set_database_writer_access",
        "\n\nrestore_current_link()",
    )
    deployment = installer[installer.index("mutation_started=1") :]

    revoke_connect = "REVOKE CONNECT ON DATABASE ac_platform FROM PUBLIC, ac_runtime, ac_migrator"
    terminate_writers = "SELECT pg_terminate_backend(pid)"
    verify_quiescence = "SELECT count(*) FROM pg_stat_activity"
    assert writer_access.index(revoke_connect) < writer_access.index(terminate_writers)
    assert writer_access.index(terminate_writers) < writer_access.index(verify_quiescence)
    assert "usename IN" in writer_access
    assert "ac_runtime" in writer_access and "ac_migrator" in writer_access
    assert '[ "$remaining" = 0 ]' in writer_access

    stop_writers = 'stop_application_services_with_hosted_drain "$writer_release" false'
    fence_writers = "set_database_writer_access fence"
    dump_database = "pg_dump "
    grant_migrator = "set_database_writer_access migrator"
    migrate_database = 'compose_for "$release_dir" --profile release run --rm migrate'
    grant_runtime = "set_database_writer_access runtime"
    start_services = 'compose_for "$release_dir" up --detach --remove-orphans'

    assert deployment.count(grant_migrator) == 1
    assert deployment.count(grant_runtime) == 1
    assert deployment.index(stop_writers) < deployment.index(fence_writers)
    assert deployment.index(fence_writers) < deployment.index(dump_database)
    assert deployment.index(dump_database) < deployment.index(grant_migrator)
    assert deployment.index(grant_migrator) < deployment.index(migrate_database)
    assert deployment.index(migrate_database) < deployment.index(grant_runtime)
    assert deployment.index(grant_runtime) < deployment.index(start_services)


def test_rollback_fences_and_restores_before_reopening_or_restarting() -> None:
    rollback = _installer_function("rollback_release", "\n\nrecord_forward_recovery_required() {")
    stop_services = 'stop_application_services_with_hosted_drain "$release_dir" true'
    fence_writers = "if set_database_writer_access fence; then"
    restore_database = "pg_restore "
    grant_runtime = "set_database_writer_access runtime || rollback_failed=1"
    restore_link = "restore_current_link || rollback_failed=1"
    restore_edge = "restore_edge_route || rollback_failed=1"
    restart_previous = 'compose_for "$previous_release" up --detach'

    assert rollback.index(stop_services) < rollback.index(fence_writers)
    assert rollback.index(fence_writers) < rollback.index(restore_database)
    assert rollback.index(restore_database) < rollback.index(restore_link)
    assert rollback.index(restore_link) < rollback.index(restore_edge)
    assert rollback.index(restore_edge) < rollback.index(grant_runtime)
    assert rollback.index(grant_runtime) < rollback.index(restart_previous)
    assert (
        '[[ "$rollback_failed" == 0 && "$backup_ready" == 1 && "$rollback_fenced" == 1 ]]'
        in rollback
    )
    assert '[[ "$rollback_fenced" == 1 && "$rollback_failed" == 0 ]]' in rollback


def test_rollback_restarts_previous_release_only_after_restore_and_runtime_grant(
    tmp_path: Path,
) -> None:
    result, events = _run_rollback_harness(tmp_path)

    assert result.returncode == 0, result.stderr
    assert events == [
        "compose:stop-core",
        "compose:stop-web",
        "access:fence",
        "compose:restore",
        "link:restore",
        "edge:restore",
        "access:runtime",
        "compose:restart",
    ]


@pytest.mark.parametrize(
    ("fail_stage", "expected_events"),
    (
        ("restore", ["compose:stop-core", "compose:stop-web", "access:fence", "compose:restore"]),
        (
            "runtime",
            [
                "compose:stop-core",
                "compose:stop-web",
                "access:fence",
                "compose:restore",
                "link:restore",
                "edge:restore",
                "access:runtime",
            ],
        ),
        (
            "edge",
            [
                "compose:stop-core",
                "compose:stop-web",
                "access:fence",
                "compose:restore",
                "link:restore",
                "edge:restore",
            ],
        ),
    ),
)
def test_rollback_failure_keeps_previous_release_stopped(
    tmp_path: Path,
    fail_stage: str,
    expected_events: list[str],
) -> None:
    result, events = _run_rollback_harness(tmp_path, fail_stage=fail_stage)

    assert result.returncode != 0
    assert events == expected_events
    assert "compose:restart" not in events
    assert "Automatic application rollback was incomplete" in result.stderr


def test_installer_serializes_deployments_and_routes_signals_through_finish() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    lock = "flock --exclusive --nonblock 9"
    artifact_mutation = 'artifacts_root="$application_root/artifacts"'
    term_trap = "trap 'exit 143' TERM"
    exit_trap = "trap finish EXIT"
    mutation_arm = "mutation_started=1"

    assert installer.index(lock) < installer.index(artifact_mutation)
    assert installer.index(term_trap) < installer.index(exit_trap)
    assert installer.index(exit_trap) < installer.index(mutation_arm)

    finish_start = installer.index("finish() {")
    finish_body = installer[finish_start : installer.index("trap finish EXIT", finish_start)]
    assert "trap - EXIT" in finish_body
    assert "trap '' HUP INT TERM" in finish_body
    assert finish_body.index("trap '' HUP INT TERM") < finish_body.index("trap - EXIT")
    assert finish_body.index("trap - EXIT") < finish_body.index("rollback_release || status=1")


def test_installer_restores_current_link_and_writes_evidence_atomically() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    advance = 'mv --no-target-directory --force "$current_tmp" "$current_link"'
    arm_switch = "current_switch_armed=1"
    restore_call = "restore_current_link || rollback_failed=1"
    restart_previous = 'compose_for "$previous_release" up --detach'
    evidence_temp = 'evidence_tmp="$(mktemp "$evidence_root/.deployment-${release_id}.XXXXXX")"'
    evidence_commit = 'mv --no-target-directory --no-clobber "$evidence_tmp" "$evidence_file"'
    mark_committed = "release_committed=1"

    assert installer.index(arm_switch) < installer.index(advance)
    rollback_body = installer[installer.index("rollback_release() {") :]
    assert rollback_body.index(restore_call) < rollback_body.index(restart_previous)
    assert installer.index(evidence_temp) < installer.index(evidence_commit)
    assert installer.index(evidence_commit) < installer.index(mark_committed)
