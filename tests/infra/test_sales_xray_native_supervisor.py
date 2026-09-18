from __future__ import annotations

import errno
import importlib.util
import json
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/render-sales-xray-native.py"
SPEC = importlib.util.spec_from_file_location("sales_native_supervisor", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
HELPER_SHA = "a" * 40
RELEASE_SHA = "b" * 40
VALUES = {
    "environment": "staging",
    "helper_source_sha": HELPER_SHA,
    "helper_root": (
        f"/srv/authority-closers/application/artifacts/sales-xray-native-{HELPER_SHA}/helper"
    ),
    "python_executable": "/usr/bin/python3",
    "native_image_ref": "sha256:" + "c" * 64,
    "supervisor_source": (
        f"/srv/authority-closers/application/releases/{RELEASE_SHA}"
        "/scripts/render-sales-xray-native.py"
    ),
}


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_units_bind_frozen_sources_and_isolate_environment(environment: str) -> None:
    result = MODULE.render(**{**VALUES, "environment": environment})
    units = result["units"]
    mount_name = next(name for name in units if name.endswith(".mount"))
    service = units[f"ac-sales-xray-native-{environment}.service"]
    assert mount_name == (
        rf"srv-authority\x2dclosers-sales\x2dxray-{environment}"
        r"-scratch-native\x2doutput\x2dtmpfs.mount"
    )
    assert f"Requires=docker.service {mount_name}" in service
    assert "RuntimeDirectoryPreserve=yes" in service
    assert f"--prepare-socket {environment}" in service
    assert f"--image-ref {VALUES['native_image_ref']}" in service
    assert VALUES["helper_root"] in service
    assert VALUES["supervisor_source"] in service
    assert "TimeoutStopSec=800s" in service
    assert "KillMode=mixed" in service
    assert "RestrictAddressFamilies=AF_UNIX" in service
    assert "InaccessiblePaths=-/etc/authority-closers/secrets" in service
    assert "ExecStart=/usr/bin/env -i " in service
    assert "EnvironmentFile=" not in service
    assert "size=64m,mode=0700,uid=10001,gid=10001,nosuid,nodev,noexec" in units[mount_name]
    other = "production" if environment == "staging" else "staging"
    assert f"sales-xray/{other}" not in service
    assert result["installed"] is False and result["provider_calls"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment", "staging\nExecStart=/bin/false"),
        ("helper_source_sha", "main"),
        ("native_image_ref", "image:latest"),
        ("native_image_ref", "sha256:" + "c" * 63),
        ("helper_root", VALUES["helper_root"].replace(HELPER_SHA, RELEASE_SHA)),
        ("helper_root", VALUES["helper_root"] + "/../changed"),
        ("helper_root", VALUES["helper_root"] + "/%i"),
        ("helper_root", VALUES["helper_root"] + "\nExecStart=/bin/false"),
        ("helper_root", VALUES["helper_root"] + "//nested"),
        ("python_executable", "/tmp/python"),  # noqa: S108 -- deliberate rejected input
        ("python_executable", "/usr/bin/python3 --eval"),
        ("supervisor_source", VALUES["supervisor_source"].replace(RELEASE_SHA, "current")),
    ],
)
def test_render_refuses_unpinned_or_injectable_values(field: str, value: str) -> None:
    with pytest.raises(ValueError):
        MODULE.render(**{**VALUES, field: value})


def test_cli_renders_json_without_installing(tmp_path: Path) -> None:
    args = [sys.executable, str(SCRIPT)]
    for name, value in VALUES.items():
        args.extend(["--" + name.replace("_", "-"), value])
    result = subprocess.run(  # noqa: S603 -- fixed renderer with authored nonsecret references
        args, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == MODULE.render(**VALUES)
    assert not list(tmp_path.iterdir())


def _socket_fixture(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock]:
    monkeypatch.setattr(MODULE.sys, "platform", "linux")
    monkeypatch.setattr(MODULE.os, "getuid", lambda: 0, raising=False)
    monkeypatch.setattr(MODULE.socket, "AF_UNIX", 1, raising=False)
    parent = MagicMock()
    parent.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
    root = MagicMock()
    root.parents = [parent]
    root.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR | 0o750, st_uid=0, st_gid=10001)
    path = MagicMock()
    root.__truediv__.return_value = path
    path.lstat.return_value = SimpleNamespace(
        st_mode=stat.S_IFSOCK | 0o660,
        st_uid=0,
        st_gid=10001,
        st_nlink=1,
        st_dev=1,
        st_ino=9,
    )
    monkeypatch.setattr(MODULE, "Path", lambda _: root)
    peer = MagicMock(spec=socket.socket)
    context = MagicMock()
    context.__enter__.return_value = peer
    monkeypatch.setattr(MODULE.socket, "socket", lambda *_: context)
    return root, path, peer


def test_prestart_leaves_missing_socket_and_stable_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, path, peer = _socket_fixture(monkeypatch)
    path.lstat.side_effect = FileNotFoundError
    MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()
    root.rmdir.assert_not_called()
    peer.connect.assert_not_called()


def test_prestart_removes_only_connection_refused_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    root, path, peer = _socket_fixture(monkeypatch)
    peer.connect.side_effect = OSError(errno.ECONNREFUSED, "refused")
    MODULE.prepare_socket("staging")
    path.unlink.assert_called_once_with()
    root.rmdir.assert_not_called()


def test_prestart_refuses_live_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    _, path, _ = _socket_fixture(monkeypatch)
    with pytest.raises(ValueError, match="already_active"):
        MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()


@pytest.mark.parametrize("code", [errno.EACCES, errno.ENOENT, errno.ETIMEDOUT])
def test_prestart_refuses_ambiguous_socket_error(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _, path, peer = _socket_fixture(monkeypatch)
    peer.connect.side_effect = OSError(code, "ambiguous")
    with pytest.raises(ValueError, match="ambiguous"):
        MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()


def test_prestart_refuses_replaced_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    _, path, peer = _socket_fixture(monkeypatch)
    original = path.lstat.return_value
    replacement = SimpleNamespace(**{**vars(original), "st_ino": 10})
    path.lstat.side_effect = [original, replacement]
    peer.connect.side_effect = OSError(errno.ECONNREFUSED, "refused")
    with pytest.raises(ValueError, match="changed"):
        MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()


@pytest.mark.parametrize(
    "bad_info",
    [
        {"st_mode": stat.S_IFLNK | 0o777},
        {"st_mode": stat.S_IFREG | 0o660},
        {"st_uid": 10001},
        {"st_gid": 0},
        {"st_nlink": 2},
    ],
)
def test_prestart_refuses_foreign_node(
    monkeypatch: pytest.MonkeyPatch, bad_info: dict[str, int]
) -> None:
    _, path, peer = _socket_fixture(monkeypatch)
    path.lstat.return_value = SimpleNamespace(**{**vars(path.lstat.return_value), **bad_info})
    with pytest.raises(ValueError, match="existing_invalid"):
        MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()
    peer.connect.assert_not_called()


def test_prestart_refuses_writable_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    root, path, peer = _socket_fixture(monkeypatch)
    root.lstat.return_value.st_mode = stat.S_IFDIR | 0o770
    with pytest.raises(ValueError, match="parent_invalid"):
        MODULE.prepare_socket("staging")
    path.unlink.assert_not_called()
    peer.connect.assert_not_called()
