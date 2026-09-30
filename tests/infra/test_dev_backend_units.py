"""Static deployment boundary and inert systemd verification; never start services."""

import ast
import os
import re
import shlex
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "infra/application/development"
BACKEND = "/srv/authority-closers/development/backend"
DATA = "/srv/authority-closers/sales-xray/development"
SOCKET = "/run/ac-sales-xray/development"
SECRETS = "/etc/authority-closers/development"
UNITS = ("ac-dev-api.service", "ac-dev-sales-xray-worker.service")
ADR = ROOT / "docs/adr/0037-dev-sales-xray-backend-identity.md"
# Explicit inventory from the installer, release engine and HOSTED_ACTIVATION.
HIDDEN = (
    "/srv/authority-closers/application",
    "/srv/authority-closers/releases",
    "/srv/authority-closers/current",
    "/srv/authority-closers/release-store",
    *(
        f"/srv/authority-closers/{area}/{environment}"
        for area in (
            "state/application",
            "backups/application",
            "volumes/media-video",
            "sales-xray",
        )
        for environment in ("staging", "production")
    ),
    "/srv/authority-closers/volumes/media-safety-socket",
    "/etc/authority-closers/sales-xray/staging",
    "/etc/authority-closers/sales-xray/production",
    "/etc/authority-closers/secrets",
    "/run/ac-sales-xray/staging",
    "/run/ac-sales-xray/production",
    "/etc/ac-release",
    "/var/lib/ac-release",
    "/var/log/ac-release",
    "/run/ac-release.lock",
    "/run/docker.sock",
    "/run/containerd",
    "/var/lib/docker",
    "/var/lib/containerd",
)


def parse_unit(name):
    """Retain repeated directives instead of silently dropping earlier mounts."""
    result = defaultdict(list)
    section = None
    for line in (DIRECTORY / name).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line[1:-1]
            continue
        key, value = line.split("=", 1)
        result[section, key].append(value)
    return result


def words(unit, key):
    return [word for value in unit["Service", key] for word in shlex.split(value)]


@pytest.mark.parametrize("name", UNITS)
def test_identity_sandbox_and_resource_contract(name):
    unit = parse_unit(name)
    worker = name == UNITS[1]
    required = {
        "User": "10001",
        "Group": "10001",
        "WorkingDirectory": BACKEND,
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "PrivateDevices": "yes",
        "NoNewPrivileges": "yes",
        "CapabilityBoundingSet": "",
        "RestrictAddressFamilies": "AF_UNIX AF_INET AF_INET6",
        "UMask": "0077",
        "MemoryMax": "768M",
        "CPUQuota": "100%",
        "TasksMax": "64" if worker else "128",
        "Nice": "10",
        "IOSchedulingClass": "idle",
        "SystemCallFilter": "~@debug process_vm_readv process_vm_writev",
    }
    for key, value in required.items():
        assert unit["Service", key] == [value]
    assert ("Service", "PrivateTmp") not in unit
    text = (DIRECTORY / name).read_text()
    assert all(value not in text for value in ("/home/", "uv run", "--reload"))
    # Unit mount assertions; these paths never create host temporary files.
    assert set(words(unit, "TemporaryFileSystem")) == {
        "/tmp:size=64M,mode=0700,uid=10001,gid=10001,noexec,nosuid,nodev",  # noqa: S108
        "/var/tmp:ro",  # noqa: S108
        "/srv/authority-closers:ro",
        "/run/ac-sales-xray:ro",
        "/etc/authority-closers:ro",
    }
    assert words(unit, "BindPaths") == [DATA]
    expected = {BACKEND, SOCKET}
    if worker:
        expected |= {
            f"{BACKEND}/.ac-release-id:/app/.ac-release-id",
            "/usr/local/bin/infisical:/opt/infisical",
            *(
                f"{SECRETS}/identities/{p}:/run/ac-sales-xray/identities/{p}"
                for p in ("elevenlabs", "gemini")
            ),
        }
    assert set(words(unit, "BindReadOnlyPaths")) == expected
    assert not words(unit, "ReadWritePaths")
    assert not words(unit, "AmbientCapabilities")
    assert "/proc" in words(unit, "InaccessiblePaths")


@pytest.mark.parametrize("name", UNITS)
@pytest.mark.parametrize("hidden", HIDDEN)
def test_every_foreign_data_credential_and_socket_root_is_hidden(name, hidden):
    unit = parse_unit(name)
    assert f"`{hidden}`" in ADR.read_text()
    masks = [p.split(":")[0] for p in words(unit, "TemporaryFileSystem")]
    masks += [p.removeprefix("-") for p in words(unit, "InaccessiblePaths")]
    assert any(Path(hidden).is_relative_to(mask) for mask in masks)
    for bind in words(unit, "BindPaths") + words(unit, "BindReadOnlyPaths"):
        source, *rest = bind.split(":")
        target = rest[0] if rest else source
        # Neither expose foreign source data nor reopen a masked target ancestor.
        for path in (source, target):
            assert not Path(path).is_relative_to(hidden)
            assert not Path(hidden).is_relative_to(path)


def test_worker_argv_environment_release_and_drain():
    unit = parse_unit(UNITS[1])
    argv = shlex.split(unit["Service", "ExecStart"][0])
    assert argv[:2] == ["/usr/bin/env", "-i"]
    end = argv.index(BACKEND + "/.venv/bin/python")
    environment = dict(item.split("=", 1) for item in argv[2:end])
    source = ROOT / "packages/python/ac_platform/conversation_intelligence/service.py"
    assignment = next(
        n
        for n in ast.parse(source.read_text()).body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_ALLOWED_ENV" for t in n.targets)
    )
    allowed = ast.literal_eval(assignment.value.args[0])
    assert set(environment) <= allowed
    assert environment["HOME"] == "/tmp"  # noqa: S108 - isolated by bounded tmpfs
    assert environment["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert argv[end:] == [
        BACKEND + "/.venv/bin/python",
        "-m",
        "ac_platform.conversation_intelligence.service",
        "--config",
        "%d/service.json",
        "--sha256",
        "${AC_DEV_WORKER_MANIFEST_SHA256}",
    ]
    assert not unit["Service", "EnvironmentFile"]
    assert unit["Service", "TimeoutStopSec"] == ["16min"]
    assert unit["Service", "KillMode"] == ["mixed"]


def test_api_argv_and_separate_credential_delivery():
    api, worker = (parse_unit(name) for name in UNITS)
    assert shlex.split(api["Service", "ExecStart"][0]) == [
        BACKEND + "/.venv/bin/python",
        "-m",
        "ac_platform.http",
        "--host",
        "127.0.0.1",
        "--port",
        "8100",
    ]
    assert api["Service", "EnvironmentFile"] == [SECRETS + "/api.env"]
    for unit, filenames in (
        (api, {"challenge-secret", "qa-password", "approval.json"}),
        (worker, {"database-url", "approval.json", "service.json"}),
    ):
        assert set(words(unit, "LoadCredential")) == {
            f"{name}:{SECRETS}/{name}" for name in filenames
        }
        assert not unit["Service", "SetCredential"]
    env = dict(word.split("=", 1) for word in words(api, "Environment"))
    assert env["AC_SALES_XRAY_CHALLENGE_SECRET_FILE"] == "%d/challenge-secret"  # noqa: S105 - path
    assert env["AC_SALES_XRAY_APPROVAL_PATH"] == "%d/approval.json"
    readme = (DIRECTORY / "README.md").read_text()
    assert "/etc/systemd/system/ac-dev-sales-xray-worker.service.d/manifest.conf" in readme
    assert "Environment=AC_DEV_WORKER_MANIFEST_SHA256=<64 hex digest>" in readme


def test_systemd_verify_exact_units_without_installing_or_starting(tmp_path):
    binary = shutil.which("systemd-analyze")
    if binary is None:
        pytest.skip("systemd-analyze is unavailable; static contract tests still run")
    # An inert root supplies only executable placeholders and prerequisite targets.
    # This avoids changing reviewed ExecStart bytes to accommodate CI host paths.
    units = tmp_path / "etc/systemd/system"
    units.mkdir(parents=True)
    for name in UNITS:
        shutil.copyfile(DIRECTORY / name, units / name)
    for target in ("sysinit", "basic", "network-online", "multi-user", "shutdown"):
        (units / f"{target}.target").write_text("[Unit]\nDescription=Verification fixture\n")
    for executable in (BACKEND + "/.venv/bin/python", "/usr/bin/env"):
        path = tmp_path / executable.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    result = subprocess.run(  # noqa: S603 - fixed verifier, inert fixture root
        [binary, "verify", f"--root={tmp_path}", *UNITS],
        capture_output=True,
        text=True,
        env={**os.environ, "SYSTEMD_LOG_LEVEL": "warning"},
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not re.search(r"Unknown|Failed|Invalid", result.stderr), result.stderr
