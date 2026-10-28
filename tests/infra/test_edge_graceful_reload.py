"""Graceful edge switches (docs/ops/ZERO-DOWNTIME-RELEASES.md, S1).

The installer's own functions run against a fictional host: Docker, compose and
curl are shell stubs that record calls. The last test starts the pinned Caddy
image (Linux CI) and switches a route with `caddy reload` on the admin socket.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPLICATION = ROOT / "infra" / "application"
FOUNDATION = ROOT / "infra" / "vps-foundation" / "compose" / "foundation"
INSTALLER = (APPLICATION / "scripts" / "install-application-release.sh").read_text()
RELEASE_CADDYFILE = (APPLICATION / "edge" / "Caddyfile").read_text(encoding="utf-8")
EDGE_OVERRIDE = (APPLICATION / "edge" / "compose.edge.yaml").read_text(encoding="utf-8")
FOUNDATION_CADDYFILE = (FOUNDATION / "Caddyfile").read_text(encoding="utf-8")
FOUNDATION_COMPOSE = (FOUNDATION / "compose.yaml").read_text(encoding="utf-8")
SOCKET_TMPFS = "/run/caddy:rw,noexec,nosuid,nodev,size=1m,uid=1000,gid=1000,mode=0700"


def function(name: str) -> str:
    return name + "() {" + INSTALLER.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def test_release_caddyfile_is_the_foundation_caddyfile_with_a_private_admin_socket() -> None:
    # A full foundation install and an application release give the same router.
    release_bytes = (APPLICATION / "edge" / "Caddyfile").read_bytes()
    assert release_bytes == (FOUNDATION / "Caddyfile").read_bytes()
    global_options = RELEASE_CADDYFILE.split("\n{\n", 1)[1].split("\n}\n", 1)[0]
    assert global_options.count("\tadmin ") == 1
    assert "\tadmin unix//run/caddy/admin.sock\n" in global_options
    assert "admin off" not in RELEASE_CADDYFILE
    assert re.search(r"admin\s+(localhost|127\.|0\.0\.0\.0|:\d)", RELEASE_CADDYFILE) is None
    assert "\tpersist_config off\n" in global_options
    assert FOUNDATION_CADDYFILE == RELEASE_CADDYFILE


def test_override_swaps_only_the_caddyfile_and_adds_the_socket_directory() -> None:
    assert EDGE_OVERRIDE.count("\n  edge-router:\n") == 1
    services = EDGE_OVERRIDE.split("services:\n", 1)[1]
    assert re.findall(r"^  ([a-z-]+):$", services, re.MULTILINE) == ["edge-router"]
    assert "${AC_EDGE_CADDYFILE:?" in EDGE_OVERRIDE
    assert "}:/etc/caddy/Caddyfile:ro\n" in EDGE_OVERRIDE
    assert f"      - {SOCKET_TMPFS}\n" in EDGE_OVERRIDE
    for absent in ("ports:", "image:", "networks:", "cap_add", "user:", "privileged"):
        assert absent not in EDGE_OVERRIDE
    # Compose drops the duplicate only when both entries are identical.
    assert f"      - {SOCKET_TMPFS}\n" in FOUNDATION_COMPOSE


def test_release_archive_must_carry_the_edge_files() -> None:
    verifier = (APPLICATION / "scripts" / "verify-release-archive.py").read_text()
    assert '"infra/application/edge/Caddyfile",' in verifier
    assert '"infra/application/edge/compose.edge.yaml",' in verifier


def _run_reconcile(
    tmp_path: Path,
    *,
    mounted: str,
    socket: bool,
    release_caddyfile: bool = True,
    after_recreate: str | None = None,
    reload_status: int = 0,
    routes_mount: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    events = tmp_path / "events"
    state = tmp_path / "mounted"
    state.write_text(mounted)
    names = (
        "edge_compose",
        "edge_router_has_admin_socket",
        "edge_router_runs_release_caddyfile",
        "reconcile_edge_router",
    )
    script = "set -euo pipefail\n" + "\n".join(function(name) for name in names)
    script += r"""
edge_admin_socket=/run/caddy/admin.sock
edge_caddyfile="$release_caddyfile"
edge_compose_override=/fixture/release/edge/compose.edge.yaml
foundation_image_env=/fixture/foundation/foundation-images.env
foundation_compose_file=/fixture/foundation/compose.yaml
edge_routes_root=/srv/authority-closers/application/edge-routes
event() { printf '%s\n' "$*" >> "$events"; }
curl() { event curl; }
docker() {
  case "$1" in
    inspect)
      if [[ "$*" == *'"/etc/caddy/Caddyfile"'* ]]; then
        printf '%s | false\n' "$(cat "$state")"
      else
        printf '%s | false\n' "$routes_mount"
      fi
      ;;
    exec)
      if [[ "$*" == "exec ac-edge-router test -S /run/caddy/admin.sock" ]]; then
        [[ "$socket" == 1 ]]
      else
        event "exec ${*:2}"
        return "$reload_status"
      fi
      ;;
    compose)
      event "compose AC_EDGE_CADDYFILE=${AC_EDGE_CADDYFILE:-} ${*:2}"
      if [[ -n "$after_recreate" ]]; then
        printf '%s' "$after_recreate" > "$state"
        socket=1
      fi
      ;;
    *) return 64 ;;
  esac
}
if ! reconcile_edge_router; then
  event failed
fi
"""
    release = "/srv/authority-closers/application/edge-config/" + "c" * 64 + "/Caddyfile"
    environment = {
        **os.environ,
        "events": str(events),
        "state": str(state),
        "socket": "1" if socket else "0",
        "release_caddyfile": release if release_caddyfile else "",
        "after_recreate": after_recreate or "",
        "reload_status": str(reload_status),
        "routes_mount": routes_mount or "/srv/authority-closers/application/edge-routes",
    }
    result = subprocess.run(  # noqa: S603 - installer functions with shell stubs only
        ["/bin/bash", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    recorded = events.read_text().splitlines() if events.exists() else []
    return result, recorded


RELEASE = "/srv/authority-closers/application/edge-config/" + "c" * 64 + "/Caddyfile"
FOUNDATION_MOUNT = (
    "/srv/authority-closers/releases/foundation-" + "f" * 40 + "/compose/foundation/Caddyfile"
)
RELOAD = (
    "exec ac-edge-router caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile "
    "--address unix//run/caddy/admin.sock"
)


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_a_router_on_the_release_caddyfile_switches_by_reload_only(tmp_path: Path) -> None:
    result, events = _run_reconcile(tmp_path, mounted=RELEASE, socket=True)
    assert result.returncode == 0, result.stderr
    assert events == [RELOAD, "curl"]


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_a_router_on_the_foundation_caddyfile_is_recreated_once_onto_the_release_one(
    tmp_path: Path,
) -> None:
    result, events = _run_reconcile(
        tmp_path, mounted=FOUNDATION_MOUNT, socket=False, after_recreate=RELEASE
    )
    assert result.returncode == 0, result.stderr
    assert events == [
        f"compose AC_EDGE_CADDYFILE={RELEASE} --env-file /fixture/foundation/foundation-images.env"
        " -f /fixture/foundation/compose.yaml -f /fixture/release/edge/compose.edge.yaml"
        " up --detach --no-deps --force-recreate --wait --wait-timeout 120 edge-router",
        "curl",
    ]
    # The next switch in the same release is a reload.
    (tmp_path / "next").mkdir()
    again, events = _run_reconcile(tmp_path / "next", mounted=RELEASE, socket=True)
    assert again.returncode == 0, again.stderr
    assert events == [RELOAD, "curl"]


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_a_recreate_that_does_not_reach_the_release_caddyfile_fails_closed(tmp_path: Path) -> None:
    result, events = _run_reconcile(
        tmp_path, mounted=FOUNDATION_MOUNT, socket=False, after_recreate=FOUNDATION_MOUNT
    )
    assert "Recreated edge router does not run the release Caddyfile" in result.stderr
    assert events[-1] == "failed"
    assert "curl" not in events


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_a_failed_reload_fails_even_where_errexit_is_suspended(tmp_path: Path) -> None:
    result, events = _run_reconcile(tmp_path, mounted=RELEASE, socket=True, reload_status=1)
    assert result.returncode == 0, result.stderr
    assert events == [RELOAD, "failed"]


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_an_unexpected_route_selector_mount_fails_after_the_switch(tmp_path: Path) -> None:
    result, events = _run_reconcile(
        tmp_path, mounted=RELEASE, socket=True, routes_mount="/elsewhere"
    )
    assert result.returncode == 0, result.stderr
    assert events == [RELOAD, "failed"]


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
@pytest.mark.parametrize("socket", [True, False])
def test_a_release_without_edge_files_keeps_the_legacy_router_behaviour(
    tmp_path: Path, socket: bool
) -> None:
    # Only a rollback target from before S1 lacks edge/: it reloads a router that
    # already has the socket, else recreates it from the foundation as before.
    result, events = _run_reconcile(
        tmp_path, mounted=RELEASE, socket=socket, release_caddyfile=False
    )
    assert result.returncode == 0, result.stderr
    if socket:
        assert events == [RELOAD, "curl"]
    else:
        assert events == [
            "compose AC_EDGE_CADDYFILE= --env-file /fixture/foundation/foundation-images.env"
            " -f /fixture/foundation/compose.yaml"
            " up --detach --no-deps --force-recreate --wait --wait-timeout 120 edge-router",
            "curl",
        ]


def _run_prepare(tmp_path: Path, source_text: str, *, tamper: bool = False):
    release = tmp_path / "release"
    (release / "edge").mkdir(parents=True)
    (release / "edge" / "Caddyfile").write_text(source_text, encoding="utf-8", newline="\n")
    (release / "edge" / "compose.edge.yaml").write_text(EDGE_OVERRIDE, encoding="utf-8")
    script = "set -euo pipefail\n" + function("prepare_edge_caddyfile")
    script += r"""
edge_admin_socket=/run/caddy/admin.sock
edge_caddyfile_source="$fixture/release/edge/Caddyfile"
edge_compose_override="$fixture/release/edge/compose.edge.yaml"
edge_config_root="$fixture/application/edge-config"
edge_caddyfile=''
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
prepare_edge_caddyfile
first="$edge_caddyfile"
if [[ "$tamper" == 1 ]]; then
  chmod u+w "$first"; printf 'tampered\n' >> "$first"; chmod 0444 "$first"
fi
edge_caddyfile=''
prepare_edge_caddyfile
printf '%s\n%s\n' "$first" "$edge_caddyfile"
"""
    return subprocess.run(  # noqa: S603 - installer function on temporary files only
        ["/bin/bash", "-c", script],
        env={**os.environ, "fixture": str(tmp_path), "tamper": "1" if tamper else "0"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_release_caddyfile_installs_once_at_its_content_address(tmp_path: Path) -> None:
    import hashlib

    result = _run_prepare(tmp_path, RELEASE_CADDYFILE)
    assert result.returncode == 0, result.stderr
    first, second = result.stdout.splitlines()
    digest = hashlib.sha256(RELEASE_CADDYFILE.encode()).hexdigest()
    expected = tmp_path / "application" / "edge-config" / digest / "Caddyfile"
    assert first == second == str(expected)
    assert expected.read_text(encoding="utf-8") == RELEASE_CADDYFILE
    assert oct(expected.stat().st_mode & 0o777) == "0o444"
    assert sorted(p.name for p in (tmp_path / "application" / "edge-config").iterdir()) == [digest]


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
def test_a_changed_copy_at_the_content_address_is_refused(tmp_path: Path) -> None:
    result = _run_prepare(tmp_path, RELEASE_CADDYFILE, tamper=True)
    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.skipif(sys.platform == "win32", reason="installer functions need Linux bash")
@pytest.mark.parametrize(
    "source_text",
    [
        RELEASE_CADDYFILE.replace("\tadmin unix//run/caddy/admin.sock\n", "\tadmin off\n"),
        RELEASE_CADDYFILE.replace("\timport /etc/caddy/application-routes/staging.caddy\n", ""),
    ],
)
def test_a_release_caddyfile_without_socket_or_routes_is_refused(
    tmp_path: Path, source_text: str
) -> None:
    result = _run_prepare(tmp_path, source_text)
    assert result.returncode != 0
    assert not (tmp_path / "application" / "edge-config").exists() or not any(
        (tmp_path / "application" / "edge-config").iterdir()
    )


def test_installer_switches_routes_through_the_reconciler_and_validates_the_release_caddyfile() -> (
    None
):
    validator = function("validate_edge_candidate")
    mount = '--volume "${edge_caddyfile:-$foundation_caddyfile}:/etc/caddy/Caddyfile:ro"'
    assert mount in validator
    assert f"--tmpfs {SOCKET_TMPFS}" in validator
    preparation = INSTALLER.index("prepare_edge_caddyfile || {")
    assert preparation < INSTALLER.index('validate_edge_candidate "$edge_hold_source"')
    assert preparation < INSTALLER.index("mutation_started=1\nactivate_edge_route")
    assert INSTALLER.index("edge_compose config --quiet") > preparation
    activate = function("activate_edge_route")
    restore = function("restore_edge_route")
    assert "reconcile_edge_router" in activate and "reconcile_edge_router" in restore


def _docker() -> str:
    docker = shutil.which("docker")
    if docker is None or sys.platform == "win32":
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("Linux CI with Docker is required for the graceful reload proof")
        pytest.skip("Linux Docker is required for the graceful reload proof")
    try:
        ready = (
            subprocess.run(  # noqa: S603 - fixed read-only daemon probe
                [docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    if not ready:
        if os.environ.get("CI", "").lower() == "true":
            pytest.fail("CI requires Docker for the graceful reload proof")
        pytest.skip("Docker daemon is unavailable")
    return docker


def _route(name: str) -> str:
    return (
        "\t@fixture host fixture.invalid\n"
        "\thandle @fixture {\n"
        f'\t\theader X-Authority-Closers-Route "{name}"\n'
        f'\t\trespond "{name}" 200\n'
        "\t}\n"
    )


def test_pinned_caddy_switches_routes_by_reload_on_the_admin_socket(tmp_path: Path) -> None:
    docker = _docker()
    images = (ROOT / "infra/vps-foundation/config/release/foundation-images.env").read_text()
    image = re.search(r"^CADDY_IMAGE=(caddy@sha256:[0-9a-f]{64})$", images, re.MULTILINE)
    assert image
    projections = tmp_path / "projections"
    selectors = tmp_path / "selectors"
    for release in ("a" * 40, "b" * 40):
        (projections / release).mkdir(parents=True)
        for environment in ("production", "staging"):
            (projections / release / f"{environment}.caddy").write_text(
                _route(f"{environment}-{release[0]}") if environment == "production" else "",
                encoding="utf-8",
                newline="\n",
            )
    selectors.mkdir()
    projection_root = "/srv/authority-closers/application/edge-route-releases"
    for environment in ("production", "staging"):
        (selectors / f"{environment}.caddy").symlink_to(
            f"{projection_root}/{'a' * 40}/{environment}.caddy"
        )
    caddyfile = tmp_path / "Caddyfile"
    caddyfile.write_text(RELEASE_CADDYFILE, encoding="utf-8", newline="\n")
    for path in (tmp_path, projections, selectors, *projections.rglob("*")):
        if not path.is_symlink():
            path.chmod(0o755 if path.is_dir() else 0o644)
    name = f"ac-edge-reload-proof-{uuid.uuid4().hex[:12]}"

    def run(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603 - pinned image, fixture files, no network
            [docker, *arguments], capture_output=True, text=True, check=False, timeout=120
        )
        if check:
            assert result.returncode == 0, result.stderr
        return result

    def served() -> str:
        result = run(
            "exec",
            name,
            "wget",
            "-qO-",
            "--header",
            "Host: fixture.invalid",
            "http://127.0.0.1:8080/",
        )
        return result.stdout

    run(
        "run",
        "--detach",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "NET_BIND_SERVICE",
        "--user",
        "1000:1000",
        "--tmpfs",
        "/config:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000",
        "--tmpfs",
        "/data:rw,noexec,nosuid,nodev,size=32m,uid=1000,gid=1000",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000",  # noqa: S108
        "--tmpfs",
        SOCKET_TMPFS,
        "--volume",
        f"{caddyfile}:/etc/caddy/Caddyfile:ro",
        "--volume",
        f"{selectors}:/etc/caddy/application-routes:ro",
        "--volume",
        f"{projections}:{projection_root}:ro",
        image[1],
    )
    try:
        deadline = time.monotonic() + 30
        while run("exec", name, "test", "-S", "/run/caddy/admin.sock", check=False).returncode:
            assert time.monotonic() < deadline, run("logs", name, check=False).stderr
            time.sleep(0.25)
        started = run("inspect", "--format", "{{.State.StartedAt}}", name).stdout
        assert served() == "production-a"
        socket = run("exec", name, "stat", "-c", "%u:%a", "/run/caddy/admin.sock").stdout
        assert socket.strip() in {"1000:200", "1000:600"}
        run(
            "exec",
            name,
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        selector = selectors / "production.caddy"
        selector.unlink()
        selector.symlink_to(f"{projection_root}/{'b' * 40}/production.caddy")
        run(
            "exec",
            name,
            "caddy",
            "reload",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
            "--address",
            "unix//run/caddy/admin.sock",
        )
        assert served() == "production-b"
        assert run("inspect", "--format", "{{.State.StartedAt}}", name).stdout == started
        assert run("inspect", "--format", "{{.RestartCount}}", name).stdout.strip() == "0"
    finally:
        run("rm", "--force", name, check=False)
