from __future__ import annotations

import importlib.util
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "xray_startup_recovery", ROOT / "infra/application/scripts/recover-sales-xray-startup.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def failed_container(service="api", environment="production"):
    return {
        "id": ("a" if service == "api" else "b") * 64,
        "name": f"/ac-application-{environment}-{service}-1",
        "project": f"ac-application-{environment}",
        "service": service,
        "status": "exited",
        "exit_code": 127,
        "oom": False,
        "restart_policy": "unless-stopped",
        "error": (
            "failed to create task for container: failed to create shim task: "
            "OCI runtime create failed: runc create failed: unable to start container process: "
            "error during container init: failed to fulfil mount request: "
            f"open /run/ac-sales-xray/{environment}: no such file or directory"
        ),
    }


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_real_boot_error_recovers_only_existing_ids_after_socket_ready(monkeypatch, environment):
    records = {s: failed_container(s, environment) for s in MODULE.SERVICES}
    started = []
    monkeypatch.setattr(MODULE, "socket_ready", lambda env: env == environment)

    def inspect(identifier):
        row = next(r for r in records.values() if identifier in (r["id"], r["name"][1:]))
        return dict(row)

    def start(identifier):
        row = next(r for r in records.values() if r["id"] == identifier)
        started.append(identifier)
        row.update(status="running", error="", exit_code=0)

    result = MODULE.recover(environment, inspect=inspect, start=start)
    assert started == ["a" * 64, "b" * 64]
    assert [r["result"] for r in result["results"]] == ["started_existing_container"] * 2


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "running"},
        {"status": "created"},
        {"exit_code": 0, "error": ""},  # intentional stop
        {"exit_code": 1},
        {"exit_code": 137, "oom": True},
        {"restart_policy": "no"},
        {"error": "exec: python: executable file not found"},
        {"error": "open /run/ac-sales-xray/production: no such file or directory"},
        {"error": failed_container(environment="staging")["error"]},
        {"error": failed_container()["error"] + "; unrelated later failure"},
    ],
)
def test_intentional_stops_and_other_failures_never_restart(monkeypatch, changes):
    monkeypatch.setattr(MODULE, "socket_ready", lambda _: True)
    records = {s: {**failed_container(s), **changes} for s in MODULE.SERVICES}
    start = Mock()
    result = MODULE.recover(
        "production",
        inspect=lambda name: next(r for r in records.values() if r["name"][1:] == name),
        start=start,
    )
    assert all(r["result"] == "unchanged" for r in result["results"])
    start.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [{"project": "other"}, {"service": "worker"}, {"name": "/replacement"}, {"id": "bad"}],
)
def test_wrong_container_identity_is_refused(changes):
    with pytest.raises(MODULE.RecoveryError, match="container_identity_mismatch"):
        MODULE.recoverable({**failed_container(), **changes}, "production", "api")


def test_container_replacement_or_state_change_during_recheck_is_refused(monkeypatch):
    monkeypatch.setattr(MODULE, "socket_ready", lambda _: True)
    inspect = Mock(side_effect=[failed_container(), {**failed_container(), "status": "running"}])
    start = Mock()
    with pytest.raises(MODULE.RecoveryError, match="container_changed_before_start"):
        MODULE.recover("production", inspect=inspect, start=start)
    start.assert_not_called()


def test_socket_disappearance_does_not_start_consumer(monkeypatch):
    monkeypatch.setattr(MODULE, "socket_ready", Mock(side_effect=[True, False]))
    start = Mock()
    with pytest.raises(MODULE.RecoveryError, match="native_socket_changed_before_start"):
        MODULE.recover("production", inspect=lambda _: failed_container(), start=start)
    start.assert_not_called()


def test_unready_socket_times_out_before_docker(monkeypatch):
    monkeypatch.setattr(MODULE, "socket_ready", lambda _: False)
    monkeypatch.setattr(MODULE.time, "monotonic", Mock(side_effect=[0, 31]))
    inspect = Mock()
    with pytest.raises(MODULE.RecoveryError, match="native_socket_not_ready"):
        MODULE.recover("production", inspect=inspect)
    inspect.assert_not_called()


def test_start_without_running_readback_fails(monkeypatch):
    monkeypatch.setattr(MODULE, "socket_ready", lambda _: True)
    with pytest.raises(MODULE.RecoveryError, match="container_not_running_after_start"):
        MODULE.recover("production", inspect=lambda _: failed_container(), start=lambda _: None)


def test_readback_must_match_started_immutable_id(monkeypatch):
    monkeypatch.setattr(MODULE, "socket_ready", lambda _: True)
    inspect = Mock(
        side_effect=[
            failed_container(),
            failed_container(),
            {**failed_container(), "id": "c" * 64, "status": "running"},
        ]
    )
    with pytest.raises(MODULE.RecoveryError, match="container_not_running_after_start"):
        MODULE.recover("production", inspect=inspect, start=lambda _: None)


@pytest.mark.parametrize("unsafe", ["symlink", "writable", "wrong_group", "regular_file"])
def test_socket_metadata_refuses_unsafe_paths(monkeypatch, unsafe):
    def metadata(path):
        socket_path = path.name == "native.sock"
        root = path.name == "production"
        mode = stat.S_IFSOCK | 0o660 if socket_path else stat.S_IFDIR | (0o750 if root else 0o755)
        group = 10001 if socket_path or root else 0
        if root and unsafe == "symlink":
            mode = stat.S_IFLNK | 0o777
        if root and unsafe == "writable":
            mode |= 0o002
        if socket_path and unsafe == "wrong_group":
            group = 0
        if socket_path and unsafe == "regular_file":
            mode = stat.S_IFREG | 0o660
        return SimpleNamespace(st_mode=mode, st_uid=0, st_gid=group, st_nlink=1)

    monkeypatch.setattr(MODULE.Path, "lstat", metadata)
    with pytest.raises(MODULE.RecoveryError, match="native_(directory|socket)_untrusted"):
        MODULE.socket_ready("production")


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_companion_unit_orders_after_native_without_docker_dependency_cycle(environment):
    units = MODULE.render_unit(environment, "c" * 40)
    unit = units[f"ac-sales-xray-startup-{environment}.service"]
    assert f"After=docker.service ac-sales-xray-native-{environment}.service" in unit
    assert "Before=docker" not in unit
    assert f"/releases/{'c' * 40}/scripts/recover-sales-xray-startup.py" in unit
    assert "--recover" in unit and "Type=oneshot" in unit
    assert "EnvironmentFile=" not in unit
    assert "InaccessiblePaths=-/etc/authority-closers/secrets" in unit
    other = "production" if environment == "staging" else "staging"
    assert f"native-{other}.service" not in unit


@pytest.mark.parametrize("release", ["main", "a" * 39, "a" * 40 + "\nExecStart=bad"])
def test_renderer_rejects_unpinned_release(release):
    with pytest.raises(MODULE.RecoveryError, match="release_not_pinned"):
        MODULE.render_unit("production", release)
