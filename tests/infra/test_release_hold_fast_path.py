"""A shorter release hold (docs/ops/ZERO-DOWNTIME-RELEASES.md, S2).

One managed-secret fetch serves the whole install, and PostgreSQL's bootstrap
scripts come from a content-addressed copy so an application release no longer
recreates PostgreSQL. The installer's own functions run against fake Infisical
executables and temporary files; the last test runs Docker Compose (Linux CI).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
INSTALLER = (APPLICATION / "scripts" / "install-application-release.sh").read_text()
COMPOSE = (APPLICATION / "compose.yaml").read_text(encoding="utf-8")
LINUX_BASH = pytest.mark.skipif(sys.platform == "win32", reason="installer functions need bash")


def function(name: str) -> str:
    return name + "() {" + INSTALLER.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


MANAGED_VALUE = "fictional secret with spaces, = signs\nand a second line"

# Stands in for /usr/local/sbin/ac-infisical-run: counts each login and fetch.
FAKE_RUNNER = r"""#!/bin/bash
printf x >> "$counter"
[[ "$fetch_status" == 0 ]] || exit "$fetch_status"
export INFISICAL_PROJECT_ID=fixture-project INFISICAL_TOKEN=fictional-short-lived-token
[[ "$1" == -- ]] && shift
exec "$@"
"""
# Stands in for `infisical run ... -- command`: adds the managed values.
FAKE_INFISICAL = r"""#!/bin/bash
while [[ $# -gt 0 && "$1" != -- ]]; do shift; done
shift
[[ "$quirk" != banner ]] || printf 'A notice on stdout\n'
extra=()
[[ "$quirk" != drops-home ]] || extra=(-u HOME)
exec env "${extra[@]}" \
  AC_FICTIONAL_MANAGED_SECRET="$secret" \
  AC_GOOGLE_OAUTH_CLIENT_ID=managed-client-id \
  "$@"
"""


def _run_environment(tmp_path: Path, body: str, *, fetch_status: int = 0, quirk: str = ""):
    counter = tmp_path / "fetches"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("ac-infisical-run", FAKE_RUNNER), ("infisical", FAKE_INFISICAL)):
        (bin_dir / name).write_text(text, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    wrapper = function("with_release_secrets").replace(
        "/usr/local/sbin/ac-infisical-run", str(bin_dir / "ac-infisical-run")
    )
    script = "set -euo pipefail\n"
    script += "secret_environment=staging\nsecret_path=/application\n"
    script += "release_secrets_captured=0\nrelease_secrets_set=()\nrelease_secrets_unset=()\n"
    script += wrapper + function("capture_release_environment")
    script += r"""
visible=(sh -c 'env -0 | tr "\0" "\n" | grep -Ev "^(_|SHLVL|PWD|OLDPWD)=" | LC_ALL=C sort')
"""
    script += body
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "counter": str(counter),
        "secret": MANAGED_VALUE,
        "fetch_status": str(fetch_status),
        "quirk": quirk,
        "AC_GOOGLE_OAUTH_CLIENT_ID": "ambient-host-value",
        "AC_OPERATIONS_TENANT_ID": "ambient-host-tenant",
    }
    result = subprocess.run(  # noqa: S603 - installer functions with fake secret executables
        ["/bin/bash", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    fetches = len(counter.read_text()) if counter.exists() else 0
    return result, fetches


@LINUX_BASH
def test_every_call_after_the_capture_reuses_its_one_fetch(tmp_path: Path) -> None:
    result, fetches = _run_environment(
        tmp_path,
        r"""
reference="$(with_release_secrets "${visible[@]}")"
capture_release_environment
for attempt in 1 2 3 4 5; do
  [[ "$(with_release_secrets "${visible[@]}")" == "$reference" ]] || exit 41
done
# The captured values never enter this shell's own environment.
! env | grep -q AC_FICTIONAL_MANAGED_SECRET || exit 42
[[ "$AC_GOOGLE_OAUTH_CLIENT_ID" == ambient-host-value ]] || exit 43
with_release_secrets sh -c 'test "$AC_GOOGLE_OAUTH_CLIENT_ID" = managed-client-id' || exit 44
with_release_secrets sh -c 'test -z "${AC_OPERATIONS_TENANT_ID+set}"' || exit 45
with_release_secrets sh -c 'test "$AC_FICTIONAL_MANAGED_SECRET" = "$secret"' || exit 46
""",
    )
    assert result.returncode == 0, result.stderr
    # One reference call and one capture; the later calls fetch nothing.
    assert fetches == 2
    assert MANAGED_VALUE not in result.stdout + result.stderr


@LINUX_BASH
def test_without_a_capture_each_call_still_fetches(tmp_path: Path) -> None:
    result, fetches = _run_environment(
        tmp_path, "for attempt in 1 2 3; do with_release_secrets true; done\n"
    )
    assert result.returncode == 0, result.stderr
    assert fetches == 3


@LINUX_BASH
def test_a_failed_fetch_is_never_captured(tmp_path: Path) -> None:
    result, fetches = _run_environment(
        tmp_path,
        """
if capture_release_environment; then exit 51; fi
[[ "$release_secrets_captured" == 0 ]] || exit 52
((${#release_secrets_set[@]} == 0)) || exit 53
""",
        fetch_status=7,
    )
    assert result.returncode == 0, result.stderr
    assert fetches == 1


@LINUX_BASH
@pytest.mark.parametrize("quirk", ["banner", "drops-home"])
def test_a_capture_that_would_lose_or_garble_a_variable_is_refused(
    tmp_path: Path, quirk: str
) -> None:
    result, _ = _run_environment(
        tmp_path,
        """
if capture_release_environment; then exit 71; fi
[[ "$release_secrets_captured" == 0 ]] || exit 72
""",
        quirk=quirk,
    )
    assert result.returncode == 0, result.stderr


def test_installer_captures_once_before_every_secret_use() -> None:
    capture = INSTALLER.index("\ncapture_release_environment || {")
    assert capture < INSTALLER.index(
        '  python3 "$release_dir/scripts/validate-google-oauth-secrets.py"'
    )
    assert capture < INSTALLER.index("\nvalidate_practice_pilot_references\n")
    assert capture < INSTALLER.index('gzip --decompress --stdout "$image_bundle_dir')
    assert capture < INSTALLER.index('\ncompose_for "$release_dir" config --quiet')
    assert capture < INSTALLER.index("mutation_started=1\nactivate_edge_route")
    wrapper = function("with_release_secrets")
    cached = wrapper.index('if [[ "${release_secrets_captured:-0}" == 1 ]]; then')
    assert cached < wrapper.index("/usr/local/sbin/ac-infisical-run")
    # Captured values are exported only inside a subshell, never on a command line.
    assert 'do export "$entry"; done' in wrapper and "    (\n" in wrapper
    # The unset list it may apply is exactly the one the fetch path removes.
    for name in re.findall(r"-u (AC_[A-Z_]+)", wrapper):
        assert name in function("capture_release_environment")


def _run_init_copy(tmp_path: Path, body: str):
    script = "set -euo pipefail\n" + function("postgres_init_copy")
    script += r"""
application_root="$fixture/application"
# Root ownership needs root on the real host; modes, content and moves are real.
chown() { :; }
install() {
  local -a kept=()
  while (($#)); do
    case "$1" in -o|-g) shift 2 ;; *) kept+=("$1"); shift ;; esac
  done
  command install "${kept[@]}"
}
stat() {
  if [[ "$1" == -c && "$2" == '%U:%G %a' ]]; then
    printf 'root:root %s\n' "$(command stat -c %a "$3")"
  else
    command stat "$@"
  fi
}
mkdir -p "$fixture/application"
"""
    script += body
    return subprocess.run(  # noqa: S603 - installer function on temporary files only
        ["/bin/bash", "-c", script],
        env={**os.environ, "fixture": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )


def _release(tmp_path: Path, name: str, roles: str = "#!/bin/sh\necho roles\n") -> Path:
    init = tmp_path / name / "postgres" / "init"
    init.mkdir(parents=True)
    (init / "001-roles.sh").write_text(roles, encoding="utf-8")
    return tmp_path / name


@LINUX_BASH
def test_same_bootstrap_scripts_in_two_releases_share_one_mount(tmp_path: Path) -> None:
    _release(tmp_path, "first")
    _release(tmp_path, "second")
    _release(tmp_path, "changed", roles="#!/bin/sh\necho changed\n")
    result = _run_init_copy(
        tmp_path,
        r"""
postgres_init_copy "$fixture/first"
postgres_init_copy "$fixture/second"
postgres_init_copy "$fixture/changed"
""",
    )
    assert result.returncode == 0, result.stderr
    first, second, changed = result.stdout.splitlines()
    assert first == second != changed
    copy = Path(first)
    assert copy.parent == tmp_path / "application" / "postgres-init"
    assert (copy / "001-roles.sh").read_text() == "#!/bin/sh\necho roles\n"
    assert oct(copy.stat().st_mode & 0o777) == "0o755"
    assert oct((copy / "001-roles.sh").stat().st_mode & 0o777) == "0o644"
    assert len(list(copy.parent.iterdir())) == 2


@LINUX_BASH
def test_a_changed_copy_or_a_missing_source_is_refused(tmp_path: Path) -> None:
    _release(tmp_path, "first")
    (tmp_path / "no-scripts").mkdir()
    result = _run_init_copy(
        tmp_path,
        r"""
if postgres_init_copy "$fixture/no-scripts"; then exit 61; fi
copy="$(postgres_init_copy "$fixture/first")"
chmod u+w "$copy/001-roles.sh"; printf 'tampered\n' >> "$copy/001-roles.sh"
chmod 0644 "$copy/001-roles.sh"
if postgres_init_copy "$fixture/first"; then exit 62; fi
""",
    )
    assert result.returncode == 0, result.stderr


@LINUX_BASH
def test_a_bootstrap_tree_with_a_link_is_refused(tmp_path: Path) -> None:
    release = _release(tmp_path, "linked")
    (release / "postgres" / "init" / "elsewhere.sql").symlink_to("/etc/hostname")
    result = _run_init_copy(tmp_path, 'postgres_init_copy "$fixture/linked"\n')
    assert result.returncode != 0
    assert not (tmp_path / "application" / "postgres-init").exists()


def test_compose_mounts_the_installed_copy_and_falls_back_for_exec_only_tools() -> None:
    assert (
        "      - ${AC_POSTGRES_INIT_ROOT:-./postgres/init}:/docker-entrypoint-initdb.d:ro\n"
        in COMPOSE
    )
    assert "- ./postgres/init:/docker-entrypoint-initdb.d" not in COMPOSE
    # The installer exports the release's copy before any Compose call; compose_for
    # passes it through (it is not among the names compose_for unsets).
    export = INSTALLER.index('AC_POSTGRES_INIT_ROOT="$(postgres_init_copy "$release_dir")" || {')
    assert INSTALLER.index("\nexport AC_POSTGRES_INIT_ROOT\n") > export
    assert export < INSTALLER.index('\ncompose_for "$release_dir" config --quiet')
    assert "AC_POSTGRES_INIT_ROOT" not in function("compose_for")


def _docker() -> str:
    docker = shutil.which("docker")
    if docker is None or sys.platform == "win32":
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Linux CI with Docker is required for the PostgreSQL mount proof")
        pytest.skip("Linux Docker is required for the PostgreSQL mount proof")
    try:
        # The daemon must answer, not just the client: compose needs both.
        ready = all(
            subprocess.run(  # noqa: S603 - fixed read-only daemon and plugin probes
                [docker, *probe],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            ).returncode
            == 0
            for probe in (["info", "--format", "{{.ServerVersion}}"], ["compose", "version"])
        )
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    if not ready:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("CI requires Docker Compose for the PostgreSQL mount proof")
        pytest.skip("Docker Compose is unavailable")
    return docker


def test_compose_keeps_the_server_running_across_releases_with_one_mount(tmp_path: Path) -> None:
    docker = _docker()
    images = (ROOT / "infra/vps-foundation/config/release/foundation-images.env").read_text()
    image = re.search(r"^CADDY_IMAGE=(caddy@sha256:[0-9a-f]{64})$", images, re.MULTILINE)
    assert image
    # The real service's mount line, on a stand-in that only sleeps.
    mount = "${AC_POSTGRES_INIT_ROOT:-./postgres/init}:/docker-entrypoint-initdb.d:ro"
    assert mount in COMPOSE
    compose = (
        "services:\n  postgres:\n"
        f"    image: {image[1]}\n"
        '    entrypoint: ["sleep", "600"]\n'
        "    network_mode: none\n"
        f"    volumes:\n      - {mount}\n"
    )
    stable = tmp_path / "postgres-init" / ("d" * 64)
    stable.mkdir(parents=True)
    for release in ("first", "second"):
        (tmp_path / release / "postgres" / "init").mkdir(parents=True)
        (tmp_path / release / "compose.yaml").write_text(compose, encoding="utf-8")
    project = f"ac-init-mount-proof-{uuid.uuid4().hex[:12]}"

    def up(release: str, init_root: Path | None) -> str:
        environment = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
        environment.pop("AC_POSTGRES_INIT_ROOT", None)
        if init_root is not None:
            environment["AC_POSTGRES_INIT_ROOT"] = str(init_root)
        base = [docker, "compose", "--project-name", project, "--file"]
        command = [*base, str(tmp_path / release / "compose.yaml")]
        for arguments in (["up", "--detach", "postgres"], ["ps", "--quiet", "postgres"]):
            result = subprocess.run(  # noqa: S603 - pinned image, temporary compose files
                [*command, *arguments],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    try:
        first = up("first", stable)
        assert first
        # Same bootstrap content, next release: the server keeps running.
        assert up("second", stable) == first
        # The old release-relative mount changes with every release: recreated.
        assert up("second", None) != first
    finally:
        subprocess.run(  # noqa: S603 - removes only this test's project
            [
                docker,
                "compose",
                "--project-name",
                project,
                "--file",
                str(tmp_path / "second" / "compose.yaml"),
                "down",
                "--timeout",
                "1",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
