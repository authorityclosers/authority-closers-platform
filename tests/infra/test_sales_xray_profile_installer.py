from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
INSTALLER_PATH = APPLICATION / "scripts" / "install-application-release.sh"
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8")


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
    pytest.fail("Bash is required for the installer profile regression")


def _installer_function(name: str, next_marker: str) -> str:
    start = INSTALLER.index(f"{name}() {{")
    return INSTALLER[start : INSTALLER.index(next_marker, start)]


def _bash_path(path: Path) -> str:
    """Render a Windows path in the POSIX form understood by Git Bash."""
    raw = path.as_posix()
    if len(raw) >= 2 and raw[1] == ":":
        return f"/{raw[0].lower()}{raw[2:]}"
    return raw


def _run_profile(
    tmp_path: Path,
    profile: bytes,
    *,
    target_environment: str,
) -> subprocess.CompletedProcess[str]:
    profile_file = tmp_path / f"{target_environment}.env"
    profile_file.write_bytes(profile)
    initialize_profile_contract = _installer_function(
        "initialize_release_profile_contract", "\n\nload_release_profile() {"
    )
    load_profile = _installer_function("load_release_profile", "\n\nprofile_value() {")
    profile_value = _installer_function("profile_value", "\n\nvalidate_release_profile() {")
    validate_profile = _installer_function(
        "validate_release_profile", "\n\nvalidate_release_profile\n"
    )
    script = f"""#!/usr/bin/env bash
set -euo pipefail
profile_file={shlex.quote(profile_file.as_posix())}
target_environment={shlex.quote(target_environment)}
declare -a profile_required_keys=()
declare -A profile_values=()
declare -A profile_allowed_keys=()
{initialize_profile_contract}
{load_profile}
{profile_value}
{validate_profile}
initialize_release_profile_contract
validate_release_profile
printf '%s\\n' "${{profile_values[AC_SALES_XRAY_APP_URL]-MISSING}}"
"""
    return subprocess.run(  # noqa: S603 - Bash and profile are test-controlled
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        text=True,
    )


@pytest.mark.parametrize(
    ("target_environment", "expected_origin"),
    (
        ("staging", "https://salesxray-staging.authorityclosers.com"),
        ("production", "https://salesxray.authorityclosers.com"),
    ),
)
def test_installer_accepts_exact_sales_xray_origin_in_frozen_profiles(
    tmp_path: Path,
    target_environment: str,
    expected_origin: str,
) -> None:
    profile = (APPLICATION / "environments" / f"{target_environment}.env").read_bytes()

    result = _run_profile(tmp_path, profile, target_environment=target_environment)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{expected_origin}\n"


def test_installer_keeps_sales_xray_origin_optional_for_older_profiles(tmp_path: Path) -> None:
    profile = (APPLICATION / "environments" / "staging.env").read_bytes()
    profile = profile.replace(
        b"AC_SALES_XRAY_APP_URL=https://salesxray-staging.authorityclosers.com\n", b""
    )

    result = _run_profile(tmp_path, profile, target_environment="staging")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "MISSING\n"


@pytest.mark.parametrize(
    ("target_environment", "reviewed_origin"),
    (
        ("staging", "https://salesxray-staging.authorityclosers.com"),
        ("production", "https://salesxray.authorityclosers.com"),
    ),
)
def test_installer_rejects_unreviewed_sales_xray_origin(
    tmp_path: Path,
    target_environment: str,
    reviewed_origin: str,
) -> None:
    profile = (APPLICATION / "environments" / f"{target_environment}.env").read_bytes()
    profile = profile.replace(
        f"AC_SALES_XRAY_APP_URL={reviewed_origin}\n".encode(),
        b"AC_SALES_XRAY_APP_URL=https://salesxray-attacker.example\n",
    )

    result = _run_profile(tmp_path, profile, target_environment=target_environment)

    assert result.returncode != 0
    assert "unexpected value for AC_SALES_XRAY_APP_URL" in result.stderr


def test_compose_profile_cannot_be_overridden_by_ambient_sales_xray_url(tmp_path: Path) -> None:
    release = tmp_path / "release"
    (release / "environments").mkdir(parents=True)
    (release / "environments" / "staging.env").write_text(
        "AC_SALES_XRAY_APP_URL=https://salesxray-staging.authorityclosers.com\n",
        encoding="utf-8",
    )
    (release / "release-images.env").write_text("", encoding="utf-8")
    (release / "compose.yaml").write_text("name: probe\nservices: {}\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture = tmp_path / "captured-url"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\' "${AC_SALES_XRAY_APP_URL-unset}" > "$AC_CAPTURE"\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    compose_for = _installer_function(
        "compose_for", '\n\ncompose_for "$release_dir" config --quiet'
    )
    filesystem_selector = _installer_function(
        "filesystem_media_compose_file_for", "\n\nvalidate_filesystem_media_activation() {"
    )
    script = f"""#!/usr/bin/env bash
set -euo pipefail
target_environment=staging
release_dir={shlex.quote(release.as_posix())}
compose_project=ac-application-staging
with_practice_pilot_scope() {{ "$@"; }}
    export PATH={shlex.quote(_bash_path(fake_bin))}:$PATH
export AC_SALES_XRAY_APP_URL=https://ambient-attacker.example
{filesystem_selector}
{compose_for}
compose_for "$release_dir" config
    """
    environment = os.environ.copy()
    environment["AC_CAPTURE"] = _bash_path(capture)
    result = subprocess.run(  # noqa: S603 - Bash and fake Docker are test-controlled
        [_bash_executable(), "-s"],
        input=script,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8") == "unset"
