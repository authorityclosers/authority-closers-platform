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
INSTALLER_SPEC = importlib.util.spec_from_file_location(
    "xray_startup_recovery_installer",
    ROOT / "infra/application/scripts/install-sales-xray-startup-recovery.py",
)
assert INSTALLER_SPEC and INSTALLER_SPEC.loader
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
INSTALLER_SPEC.loader.exec_module(INSTALLER)


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


def edge_container(status="exited", environment="production", ip=MODULE.EDGE_IP):
    return {
        "id": "e" * 64,
        "name": MODULE.EDGE_NAME,
        "project": MODULE.EDGE_PROJECT,
        "service": MODULE.EDGE_SERVICE,
        "status": status,
        "exit_code": 1 if status == "exited" else 0,
        "error": "",
        "oom": False,
        "restart_policy": "unless-stopped",
        "networks": {MODULE.EDGE_NETWORK: {"IPAddress": ip}} if ip is not None else {},
    }


def collision_container(environment="production", status="running", ip=MODULE.EDGE_IP):
    project = f"ac-application-{environment}"
    return {
        "id": "c" * 64,
        "name": f"/{project}-{MODULE.REVIEWED_COLLISION_SERVICE}-1",
        "project": project,
        "service": MODULE.REVIEWED_COLLISION_SERVICE,
        "status": status,
        "exit_code": 0,
        "error": "",
        "oom": False,
        "restart_policy": "unless-stopped",
        "networks": {MODULE.EDGE_NETWORK: {"IPAddress": ip}} if ip is not None else {},
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


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_edge_unit_is_pinned_and_runs_before_consumer(environment):
    units = MODULE.render_edge_unit(environment, "d" * 40)
    unit = units[f"ac-sales-xray-edge-reconcile-{environment}.service"]
    assert "Requires=docker.service" in unit
    assert "After=docker.service network-online.target" in unit
    assert f"Before=ac-sales-xray-startup-{environment}.service" in unit
    assert f"/releases/{'d' * 40}/scripts/recover-sales-xray-startup.py" in unit
    assert "--reconcile-edge" in unit
    assert "EnvironmentFile=" not in unit
    assert "InaccessiblePaths=-/etc/authority-closers/secrets" in unit


def test_edge_unit_rejects_unpinned_release():
    with pytest.raises(MODULE.RecoveryError, match="release_not_pinned"):
        MODULE.render_edge_unit("production", "main")


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_edge_collision_recovery_binds_mutations_to_exact_ids(environment):
    rows = {
        MODULE.EDGE_NAME: edge_container(environment=environment),
        f"ac-application-{environment}-{MODULE.REVIEWED_COLLISION_SERVICE}-1": collision_container(
            environment
        ),
    }
    calls = []

    def inspect(identifier):
        row = next(
            r
            for r in rows.values()
            if identifier in (r["id"], r["name"].lstrip("/"))
            or (identifier == MODULE.EDGE_NAME and r["name"] == MODULE.EDGE_NAME)
        )
        return dict(row)

    def stop(identifier):
        calls.append(("stop", identifier))
        row = next(r for r in rows.values() if r["id"] == identifier)
        row.update(status="exited")
        row["networks"] = {}

    def start(identifier):
        calls.append(("start", identifier))
        row = next(r for r in rows.values() if r["id"] == identifier)
        row.update(status="running")
        if identifier == "e" * 64:
            row["networks"] = {MODULE.EDGE_NETWORK: {"IPAddress": MODULE.EDGE_IP}}
        else:
            row["networks"] = {MODULE.EDGE_NETWORK: {"IPAddress": "172.18.0.3"}}

    result = MODULE.reconcile_edge_collision(environment, inspect=inspect, stop=stop, start=start)
    assert result["result"] == "edge_started_after_reviewed_collision"
    assert calls == [("stop", "c" * 64), ("start", "e" * 64), ("start", "c" * 64)]


def test_edge_collision_unknown_occupant_refuses_without_mutation():
    edge = edge_container()
    unknown = collision_container()
    unknown["service"] = "api"
    stop = Mock()
    start = Mock()
    with pytest.raises(MODULE.RecoveryError, match="edge_collision_unknown_occupant"):
        MODULE.reconcile_edge_collision(
            "production",
            inspect=lambda identifier: dict(edge if identifier == MODULE.EDGE_NAME else unknown),
            stop=stop,
            start=start,
        )
    stop.assert_not_called()
    start.assert_not_called()


def test_edge_start_failure_restores_exact_reviewed_collision():
    rows = {
        MODULE.EDGE_NAME: edge_container(),
        "collision": collision_container(),
    }
    calls = []

    def inspect(identifier):
        if identifier in (MODULE.EDGE_NAME, "e" * 64):
            return dict(rows[MODULE.EDGE_NAME])
        return dict(rows["collision"])

    def stop(identifier):
        calls.append(("stop", identifier))
        if identifier == "c" * 64:
            rows["collision"].update(status="exited")
        else:
            rows[MODULE.EDGE_NAME].update(status="exited")

    def start(identifier):
        calls.append(("start", identifier))
        if identifier == "c" * 64:
            rows["collision"].update(status="running")
        else:
            raise MODULE.RecoveryError("container_start_failed")

    with pytest.raises(MODULE.RecoveryError, match="container_start_failed"):
        MODULE.reconcile_edge_collision("production", inspect=inspect, stop=stop, start=start)
    assert calls == [("stop", "c" * 64), ("start", "e" * 64), ("start", "c" * 64)]
    assert rows["collision"]["status"] == "running"


def test_running_edge_with_wrong_ip_refuses_without_touching_collision():
    edge = edge_container(status="running", ip="172.18.0.9")
    collision = collision_container()
    stop = Mock()
    start = Mock()
    with pytest.raises(MODULE.RecoveryError, match="edge_container_network_mismatch"):
        MODULE.reconcile_edge_collision(
            "production",
            inspect=lambda identifier: dict(edge if identifier == MODULE.EDGE_NAME else collision),
            stop=stop,
            start=start,
        )
    stop.assert_not_called()
    start.assert_not_called()


def test_descriptor_plan_validates_hash_and_keeps_install_side_effect_free(tmp_path):
    release = "f" * 40
    descriptor = MODULE.render_descriptor("staging", release)
    path = tmp_path / "descriptor.json"
    raw = __import__("json").dumps(descriptor, sort_keys=True).encode()
    path.write_bytes(raw)
    result = INSTALLER.install(
        path,
        environment="staging",
        release=release,
        descriptor_sha=INSTALLER.sha256(raw),
        unit_root=tmp_path / "units",
    )
    assert result["action"] == "plan"
    assert result["provider_calls"] == 0
    assert not (tmp_path / "units").exists()


def test_descriptor_install_is_atomic_and_activation_path_is_exact(tmp_path, monkeypatch):
    release = "a" * 40
    descriptor = MODULE.render_descriptor("production", release)
    path = tmp_path / "descriptor.json"
    raw = __import__("json").dumps(descriptor, sort_keys=True).encode()
    path.write_bytes(raw)
    unit_root = tmp_path / "units"
    unit_root.mkdir()
    calls = []

    def systemctl(argv):
        calls.append(argv)

    monkeypatch.setattr(INSTALLER.os, "geteuid", lambda: 0, raising=False)
    result = INSTALLER.install(
        path,
        environment="production",
        release=release,
        descriptor_sha=INSTALLER.sha256(raw),
        execute=True,
        activate=True,
        unit_root=unit_root,
        systemctl=systemctl,
    )
    assert result["action"] == "activate"
    assert calls == [
        ["daemon-reload"],
        ["enable", "--now", "ac-sales-xray-edge-reconcile-production.service"],
        ["enable", "--now", "ac-sales-xray-startup-production.service"],
    ]
    assert sorted(p.name for p in unit_root.iterdir()) == sorted(result["units"])


def test_installer_refuses_existing_unit_drift_without_overwrite(tmp_path, monkeypatch):
    release = "b" * 40
    descriptor = MODULE.render_descriptor("staging", release)
    path = tmp_path / "descriptor.json"
    raw = __import__("json").dumps(descriptor, sort_keys=True).encode()
    path.write_bytes(raw)
    unit_root = tmp_path / "units"
    unit_root.mkdir()
    target = unit_root / "ac-sales-xray-edge-reconcile-staging.service"
    target.write_text("operator-owned", encoding="utf-8")
    monkeypatch.setattr(INSTALLER.os, "geteuid", lambda: 0, raising=False)
    with pytest.raises(INSTALLER.InstallerError, match="unit_drift_requires_review"):
        INSTALLER.install(
            path,
            environment="staging",
            release=release,
            descriptor_sha=INSTALLER.sha256(raw),
            execute=True,
            unit_root=unit_root,
            systemctl=Mock(),
        )
    assert target.read_text(encoding="utf-8") == "operator-owned"
