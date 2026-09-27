from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "infra" / "application" / "scripts" / "install-sales-xray-native.py"
RENDERER = ROOT / "infra" / "application" / "scripts" / "render-sales-xray-native.py"

spec = importlib.util.spec_from_file_location("install_sales_xray_native", SCRIPT)
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def _render_descriptor(path: Path, environment: str = "staging") -> tuple[Path, str]:
    helper_sha = installer.HELPER_SOURCE_SHA
    helper_root = installer._helper_root()
    completed = subprocess.run(  # noqa: S603 - test invokes the checked-in renderer.
        [
            sys.executable,
            str(RENDERER),
            "--environment",
            environment,
            "--helper-source-sha",
            helper_sha,
            "--helper-root",
            helper_root,
            "--python-executable",
            "/usr/bin/python3",
            "--native-image-ref",
            installer.NATIVE_IMAGE_REF,
            "--supervisor-source",
            installer._supervisor_source(),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = completed.stdout.encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


class FakeSystemd:
    def __init__(
        self,
        unit_root: Path,
        *,
        fail_service_start: bool = False,
        fail_service_stop: bool = False,
        socket_failures: int = 0,
        socket_always_missing: bool = False,
    ) -> None:
        self.unit_root = unit_root
        self.fail_service_start = fail_service_start
        self.fail_service_stop = fail_service_stop
        self.socket_failures = socket_failures
        self.socket_always_missing = socket_always_missing
        self.active: dict[str, bool] = {}
        self.enabled: dict[str, bool] = {}
        self.events: list[tuple[str, Any]] = []

    def verify(self, paths: tuple[Path, ...]) -> None:
        self.events.append(("verify", tuple(path.name for path in paths)))

    def daemon_reload(self) -> None:
        self.events.append(("daemon_reload", None))

    def enable_now(self, unit: str) -> None:
        self.events.append(("enable_now", unit))
        if unit.endswith(".service") and self.fail_service_start:
            raise installer.InstallerError("fake_service_start_failed")
        self.active[unit] = True
        self.enabled[unit] = True

    def enable(self, unit: str) -> None:
        self.events.append(("enable", unit))
        self.enabled[unit] = True

    def disable(self, unit: str) -> None:
        self.events.append(("disable", unit))
        self.enabled[unit] = False

    def stop(self, unit: str) -> None:
        self.events.append(("stop", unit))
        if not self.fail_service_stop:
            self.active[unit] = False

    def is_active(self, unit: str) -> bool:
        return self.active.get(unit, False)

    def is_enabled(self, unit: str) -> bool:
        return self.enabled.get(unit, False)

    def fragment_path(self, unit: str) -> str:
        return str(installer._unit_path(self.unit_root, unit))

    def mount_readback(self, mount_path: Path) -> dict[str, Any]:
        return {"target": str(mount_path), "fstype": "tmpfs", "options": ["size=64m"]}

    def socket_readback(self, socket_path: Path) -> dict[str, Any]:
        if self.socket_always_missing or self.socket_failures:
            if self.socket_failures:
                self.socket_failures -= 1
            raise installer.InstallerError("native_socket_readback_failed")
        return {"path": str(socket_path), "mode": 0o660, "uid": 0, "gid": 10001}


class FakeDocker:
    def inspect_identity(self) -> str:
        return installer.NATIVE_IMAGE_REF


class WrongDocker:
    def inspect_identity(self) -> str:
        return "sha256:" + "f" * 64


class ConfigDocker:
    def inspect_identity(self) -> str:
        return installer.NATIVE_IMAGE_CONFIG_ID


class FakeGroup:
    def __init__(self, *, status: str = "present", created: bool = False) -> None:
        self.status = status
        self.created = created
        self.calls: list[bool] = []

    def ensure(self, *, dry_run: bool) -> dict[str, Any]:
        self.calls.append(dry_run)
        return {
            "name": installer.NATIVE_GROUP_NAME,
            "gid": installer.NATIVE_GROUP_GID,
            "members": [],
            "status": self.status,
            "created": self.created,
        }


class StaticGroup(installer.SubprocessGroup):
    def __init__(self, responses: dict[str, str | None]) -> None:
        self.responses = responses

    def _query(self, key: str) -> str | None:
        return self.responses.get(key)


def _install_args(tmp_path: Path, descriptor: Path, digest: str) -> dict[str, Any]:
    unit_root = tmp_path / "systemd"
    unit_root.mkdir(exist_ok=True)
    app_root = tmp_path / "application"
    app_root.mkdir(exist_ok=True)
    receipt_parent = app_root / "deployments" / "staging"
    receipt_parent.mkdir(parents=True, exist_ok=True)
    return {
        "environment": "staging",
        "native_units": descriptor,
        "native_units_sha256": digest,
        "renderer": RENDERER,
        "renderer_python": Path(sys.executable),
        "native_image_config_id": installer.NATIVE_IMAGE_CONFIG_ID,
        "receipt": receipt_parent / "native-unit-install.json",
        "application_root": app_root,
        "unit_root": unit_root,
        "start": True,
        "require_root": False,
        "canonical_paths": False,
        "docker": FakeDocker(),
        "group": FakeGroup(),
    }


def _new_artifact(tmp_path: Path) -> tuple[Path, str, Any]:
    binding = installer.NativeBinding("a" * 40, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    root = tmp_path / "artifact"
    root.mkdir()
    files = [
        "packages/python/ac_platform/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/__init__.py",
        "packages/python/ac_platform/conversation_intelligence/native_runtime.py",
        "packages/python/ac_platform/conversation_intelligence/signals.py",
        "scripts/native_runtime_helper.py",
        "scripts/test_hosted_native_linux.py",
    ]
    archive = root / "native-helper.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in files:
            raw = b"# verified helper fixture\n"
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            bundle.addfile(member, io.BytesIO(raw))
            target = root / "helper" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    metadata = {
        "schema": "ac.sales-xray.native-image/1",
        "source_commit": binding.helper_source_sha,
        "dockerfile": "infra/conversation-worker/Dockerfile",
        "target": "runtime",
        "platform": {"os": "linux", "architecture": "amd64"},
        "doctor": {"ffmpeg": True, "ffprobe": True, "provider_calls": False},
        "image": {
            "expected_runtime_ref": binding.image_ref,
            "image_id": binding.image_config_id,
            "identity_type": "oci_transport_manifest",
        },
        "transport": {
            "manifest_digest": binding.image_ref,
            "config_digest": binding.image_config_id,
        },
        "helper_source": {
            "entrypoint": "scripts/native_runtime_helper.py",
            "pythonpath": "packages/python",
            "files": files,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        },
    }
    path = root / "native-image.json"
    path.write_text(json.dumps(metadata))
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), binding


def _upgrade_args(tmp_path: Path) -> tuple[dict[str, Any], Any, dict[str, str]]:
    old, old_digest = _render_descriptor(tmp_path / "previous-units.json")
    manifest, manifest_digest, binding = _new_artifact(tmp_path)
    payload = installer._rendered_descriptor(
        renderer=RENDERER,
        renderer_python=Path(sys.executable),
        environment="staging",
        canonical_paths=False,
        binding=binding,
    )
    descriptor = tmp_path / "new-units.json"
    descriptor.write_text(json.dumps(payload))
    args = _install_args(tmp_path, descriptor, hashlib.sha256(descriptor.read_bytes()).hexdigest())
    args.update(
        native_artifact_manifest=manifest,
        native_artifact_sha256=manifest_digest,
        native_image_config_id=binding.image_config_id,
        previous_native_units=old,
        previous_native_units_sha256=old_digest,
    )
    args["docker"] = type("NewDocker", (), {"inspect_identity": lambda self: binding.image_ref})()
    old_units = json.loads(old.read_text())["units"]
    for name, content in old_units.items():
        installer._unit_path(args["unit_root"], name).write_bytes(content.encode())
    return args, binding, old_units


def test_upgrade_uses_verified_artifact_and_drains_running_old_helper(tmp_path: Path) -> None:
    args, binding, old_units = _upgrade_args(tmp_path)
    fake = FakeSystemd(args["unit_root"])
    fake.active = dict.fromkeys(old_units, True)
    result = installer.install(**args, systemd=fake)
    service = installer._service_unit("staging")
    assert result["helper_source_sha"] == binding.helper_source_sha
    assert result["native_image_ref"] == binding.image_ref
    assert fake.events.index(("stop", service)) < fake.events.index(("daemon_reload", None))
    assert fake.events.index(("stop", service)) < fake.events.index(("enable_now", service))
    backup = Path(result["rollback_backup"])
    assert installer._unit_path(backup, service).read_bytes() == old_units[service].encode()
    assert binding.helper_source_sha in installer._unit_path(args["unit_root"], service).read_text()


def test_previous_release_renderer_path_is_not_rechecked_as_candidate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prior descriptor may be verified with the candidate renderer executable.

    The renderer output still binds its supervisor source to the prior helper
    identity. Requiring the executable path itself to equal that retired path
    would make every canonical upgrade fail before any unit mutation.
    """

    binding = installer.NativeBinding(
        "b" * 40,
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
    )
    renderer = Path("/candidate/release/scripts/render-sales-xray-native.py")
    descriptor: dict[str, Any] = {}
    monkeypatch.setattr(installer, "_rendered_descriptor", lambda **_: descriptor)
    monkeypatch.setattr(installer, "_ensure_existing_parents", lambda *_, **__: None)
    monkeypatch.setattr(installer, "_ensure_owner", lambda *_, **__: None)

    installer._validate_renderer_binding(
        descriptor,
        renderer=renderer,
        renderer_python=Path("/usr/bin/python3"),
        environment="staging",
        canonical_paths=True,
        binding=binding,
        enforce_path_binding=False,
    )

    with pytest.raises(installer.InstallerError, match="renderer_path_not_release_bound"):
        installer._validate_renderer_binding(
            descriptor,
            renderer=renderer,
            renderer_python=Path("/usr/bin/python3"),
            environment="staging",
            canonical_paths=True,
            binding=binding,
        )


@pytest.mark.parametrize(
    "defect",
    ["manifest_hash", "helper_bytes", "archive_bytes", "wrong_image", "prior_drift", "prior_hash"],
)
def test_upgrade_rejects_unverified_bindings_before_mutation(tmp_path: Path, defect: str) -> None:
    args, _, old_units = _upgrade_args(tmp_path)
    if defect == "manifest_hash":
        args["native_artifact_sha256"] = "0" * 64
    elif defect == "helper_bytes":
        (
            args["native_artifact_manifest"].parent / "helper/scripts/native_runtime_helper.py"
        ).write_text("changed")
    elif defect == "archive_bytes":
        (args["native_artifact_manifest"].parent / "native-helper.tar.gz").write_bytes(b"changed")
    elif defect == "wrong_image":
        args["docker"] = WrongDocker()
    elif defect == "prior_drift":
        installer._unit_path(args["unit_root"], installer._service_unit("staging")).write_text(
            "foreign"
        )
    else:
        args["previous_native_units_sha256"] = "0" * 64
    before = {
        name: installer._unit_path(args["unit_root"], name).read_bytes() for name in old_units
    }
    fake = FakeSystemd(args["unit_root"])
    with pytest.raises(installer.InstallerError):
        installer.install(**args, systemd=fake)
    assert not fake.events
    assert not args["receipt"].exists()
    assert {
        name: installer._unit_path(args["unit_root"], name).read_bytes() for name in old_units
    } == before


def test_upgrade_failure_restores_the_previous_helper(tmp_path: Path) -> None:
    args, _, old_units = _upgrade_args(tmp_path)
    service = installer._service_unit("staging")

    class FailNewHelperOnce(FakeSystemd):
        failed = False

        def enable_now(self, unit: str) -> None:
            if unit == service and not self.failed:
                self.failed = True
                raise installer.InstallerError("new_helper_failed")
            super().enable_now(unit)

    fake = FailNewHelperOnce(args["unit_root"])
    fake.active = dict.fromkeys(old_units, True)
    fake.enabled = dict.fromkeys(old_units, True)
    with pytest.raises(installer.InstallerError, match="new_helper_failed"):
        installer.install(**args, systemd=fake)
    assert {
        name: installer._unit_path(args["unit_root"], name).read_bytes() for name in old_units
    } == {name: raw.encode() for name, raw in old_units.items()}
    assert fake.active[service]
    assert json.loads(args["receipt"].read_text())["rollback"] == "completed"


def test_upgrade_rejects_a_helper_that_did_not_stop_before_publish(tmp_path: Path) -> None:
    args, _, old_units = _upgrade_args(tmp_path)
    service = installer._service_unit("staging")
    fake = FakeSystemd(args["unit_root"], fail_service_stop=True)
    fake.active = dict.fromkeys(old_units, True)
    fake.enabled = dict.fromkeys(old_units, True)

    with pytest.raises(installer.InstallerError, match="native_service_stop_failed"):
        installer.install(**args, systemd=fake)

    assert ("stop", service) in fake.events
    # The only service start is rollback's restoration; the candidate was
    # never published or started while the old helper remained active.
    assert fake.events.count(("enable_now", service)) == 1
    assert {
        name: installer._unit_path(args["unit_root"], name).read_bytes() for name in old_units
    } == {name: raw.encode() for name, raw in old_units.items()}
    assert fake.active[service]
    assert json.loads(args["receipt"].read_text())["rollback"] == "completed"


def test_artifact_manifest_rejects_malformed_nested_helper_shape(tmp_path: Path) -> None:
    args, _, _ = _upgrade_args(tmp_path)
    manifest = args["native_artifact_manifest"]
    payload = json.loads(manifest.read_text())
    payload["helper_source"] = ["not-a-mapping"]
    manifest.write_text(json.dumps(payload))
    args["native_artifact_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()

    with pytest.raises(installer.InstallerError, match="native_artifact_binding_invalid"):
        installer.install(**args, systemd=FakeSystemd(args["unit_root"]))


def test_descriptor_must_match_source_renderer_and_image_identity(tmp_path: Path) -> None:
    assert installer.NATIVE_IMAGE_CONFIG_ID == (
        "sha256:75e3b01d100534ce667a97822ab34216b09553f820b60c2f66a223b72b481866"
    )
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    payload = json.loads(descriptor.read_text())
    payload["native_image_ref"] = "sha256:" + "0" * 64
    mutated = json.dumps(payload).encode()
    descriptor.write_bytes(mutated)
    with pytest.raises(installer.InstallerError, match="native_units_image_mismatch"):
        installer.install(
            **_install_args(tmp_path, descriptor, hashlib.sha256(mutated).hexdigest())
        )

    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    with pytest.raises(installer.InstallerError, match="native_image_config_mismatch"):
        installer.install(
            **{
                **_install_args(tmp_path, descriptor, digest),
                "native_image_config_id": "sha256:" + "0" * 64,
            }
        )


def test_dry_run_verifies_staged_bytes_without_installing_or_receipting(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    fake = FakeSystemd(arguments["unit_root"])
    result = installer.install(**arguments, dry_run=True, systemd=fake)

    assert result["status"] == "dry_run"
    assert list(arguments["unit_root"].iterdir()) == []
    assert not arguments["receipt"].exists()
    assert [event[0] for event in fake.events] == ["verify"]


def test_dry_run_reports_missing_native_group_without_mutation(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    group = FakeGroup(status="missing")
    arguments["group"] = group

    result = installer.install(
        **arguments,
        dry_run=True,
        systemd=FakeSystemd(arguments["unit_root"]),
    )

    assert result["native_group_name"] == "ac-sales-xray-native"
    assert result["native_group_gid"] == 10001
    assert result["native_group_status"] == "missing"
    assert result["native_group_created"] is False
    assert result["runtime_mutation"] is False
    assert group.calls == [True]
    assert not arguments["receipt"].exists()
    assert list(arguments["unit_root"].iterdir()) == []


class RejectingGroup:
    def ensure(self, *, dry_run: bool) -> dict[str, Any]:
        raise installer.InstallerError("native_group_gid_collision")


def test_native_group_collision_is_rejected_before_unit_mutation(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    arguments["group"] = RejectingGroup()

    with pytest.raises(installer.InstallerError, match="native_group_gid_collision"):
        installer.install(**arguments, systemd=FakeSystemd(arguments["unit_root"]))

    receipt = json.loads(arguments["receipt"].read_text())
    assert receipt["status"] == "failed"
    assert receipt["runtime_mutation"] is False
    assert list(arguments["unit_root"].iterdir()) == []


def test_native_group_inspection_rejects_gid_collision_and_members() -> None:
    with pytest.raises(installer.InstallerError, match="native_group_gid_collision"):
        StaticGroup({str(installer.NATIVE_GROUP_GID): "other:x:10001:"}).inspect()

    occupied = "ac-sales-xray-native:x:10001:human-user"
    with pytest.raises(installer.InstallerError, match="native_group_members_not_empty"):
        StaticGroup(
            {
                installer.NATIVE_GROUP_NAME: occupied,
                str(installer.NATIVE_GROUP_GID): occupied,
            }
        ).inspect()


def test_native_group_creation_uses_fixed_operator_and_dry_run_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CreatingGroup(installer.SubprocessGroup):
        created = False

        def _query(self, key: str) -> str | None:
            if not self.created:
                return None
            return f"{installer.NATIVE_GROUP_NAME}:x:{installer.NATIVE_GROUP_GID}:"

    group = CreatingGroup()
    assert group.ensure(dry_run=True)["status"] == "missing"

    commands: list[list[str]] = []

    def fake_run(arguments: list[str], **_: Any) -> Any:
        commands.append(arguments)
        group.created = True
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    result = group.ensure(dry_run=False)

    assert result["status"] == "created"
    assert result["created"] is True
    assert commands == [
        [
            "/usr/sbin/groupadd",
            "--system",
            "--gid",
            "10001",
            "ac-sales-xray-native",
        ]
    ]


def test_getent_exit_two_is_absent_group(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_: Any, **__: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 2, "", "")

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    assert installer.SubprocessGroup()._query("10001") is None


def test_docker_identity_must_match_verified_manifest_or_config(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    with pytest.raises(installer.InstallerError, match="docker_identity_mismatch"):
        installer.install(**{**arguments, "docker": WrongDocker()})
    assert not arguments["receipt"].exists()

    result = installer.install(
        **{**arguments, "docker": ConfigDocker()},
        dry_run=True,
        systemd=FakeSystemd(arguments["unit_root"]),
    )
    assert result["docker_identity"] == installer.NATIVE_IMAGE_CONFIG_ID
    assert result["docker_identity_binding"] == "verified_config"


def test_receipt_is_rechecked_after_shared_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    original_lock = installer.DeploymentLock

    class RacingLock:
        def __init__(self, path: Path, *, require_root: bool) -> None:
            self.inner = original_lock(path, require_root=require_root)

        def __enter__(self) -> Any:
            entered = self.inner.__enter__()
            arguments["receipt"].write_bytes(b"another operator won the receipt name")
            return entered

        def __exit__(self, *args: object) -> None:
            self.inner.__exit__(*args)

    monkeypatch.setattr(installer, "DeploymentLock", RacingLock)
    with pytest.raises(installer.InstallerError, match="receipt_already_exists"):
        installer.install(**arguments, systemd=FakeSystemd(arguments["unit_root"]))

    assert arguments["receipt"].read_bytes() == b"another operator won the receipt name"
    assert list(arguments["unit_root"].iterdir()) == []


def test_install_starts_mount_before_helper_and_preserves_prior_bytes(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    fake = FakeSystemd(arguments["unit_root"])
    names = (installer._mount_unit("staging"), installer._service_unit("staging"))
    units = json.loads(descriptor.read_text())["units"]
    old = {name: units[name].encode() for name in names}
    for name, raw in old.items():
        installer._unit_path(arguments["unit_root"], name).write_bytes(raw)

    result = installer.install(**arguments, systemd=fake)

    assert result["status"] == "installed"
    assert result["runtime_mutation"] is True
    assert result["docker_identity"] == installer.NATIVE_IMAGE_REF
    assert [event[1] for event in fake.events if event[0] == "enable_now"] == list(names)
    assert installer._unit_path(arguments["unit_root"], names[0]).read_text().startswith("[Unit]")
    assert installer._unit_path(arguments["unit_root"], names[1]).read_text().startswith("[Unit]")
    backup = Path(result["rollback_backup"])
    assert installer._unit_path(backup, names[0]).read_bytes() == old[names[0]]
    assert installer._unit_path(backup, names[1]).read_bytes() == old[names[1]]
    receipt = json.loads(arguments["receipt"].read_text())
    assert receipt["status"] == "installed"
    assert receipt["readback"]["active"][names[0]] is True
    assert receipt["readback"]["active"][names[1]] is True
    assert receipt["readback"]["socket"]["mode"] == 0o660


def test_created_native_group_is_recorded_truthfully(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    arguments["group"] = FakeGroup(status="created", created=True)
    fake = FakeSystemd(arguments["unit_root"])
    names = (installer._mount_unit("staging"), installer._service_unit("staging"))
    units = json.loads(descriptor.read_text())["units"]
    for name in names:
        installer._unit_path(arguments["unit_root"], name).write_bytes(units[name].encode())

    result = installer.install(**arguments, systemd=fake)

    receipt = json.loads(arguments["receipt"].read_text())
    assert result["native_group_status"] == "created"
    assert result["native_group_created"] is True
    assert receipt["native_group_created"] is True
    assert receipt["runtime_mutation"] is True


def test_failed_start_restores_prior_bytes_and_records_rollback(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    fake = FakeSystemd(arguments["unit_root"], fail_service_start=True)
    names = (installer._mount_unit("staging"), installer._service_unit("staging"))
    units = json.loads(descriptor.read_text())["units"]
    old = {name: units[name].encode() for name in names}
    for name, raw in old.items():
        installer._unit_path(arguments["unit_root"], name).write_bytes(raw)

    with pytest.raises(installer.InstallerError, match="fake_service_start_failed"):
        installer.install(**arguments, systemd=fake)

    assert {
        installer._unit_path(arguments["unit_root"], name).read_bytes() for name in names
    } == set(old.values())
    receipt = json.loads(arguments["receipt"].read_text())
    assert receipt["status"] == "failed"
    assert receipt["runtime_mutation"] is True
    assert receipt["rollback"] == "completed"


def test_socket_readback_waits_for_transient_native_socket(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    fake = FakeSystemd(arguments["unit_root"], socket_failures=2)
    names = (installer._mount_unit("staging"), installer._service_unit("staging"))
    units = json.loads(descriptor.read_text())["units"]
    for name in names:
        installer._unit_path(arguments["unit_root"], name).write_bytes(units[name].encode())

    result = installer.install(**arguments, systemd=fake)

    assert result["status"] == "installed"
    assert fake.socket_failures == 0


def test_permanent_socket_readback_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installer, "NATIVE_READINESS_TIMEOUT_SECONDS", 0.01)
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    fake = FakeSystemd(arguments["unit_root"], socket_always_missing=True)
    names = (installer._mount_unit("staging"), installer._service_unit("staging"))
    units = json.loads(descriptor.read_text())["units"]
    for name in names:
        installer._unit_path(arguments["unit_root"], name).write_bytes(units[name].encode())

    with pytest.raises(installer.InstallerError, match="native_socket_readback_failed"):
        installer.install(**arguments, systemd=fake)

    receipt = json.loads(arguments["receipt"].read_text())
    assert receipt["rollback"] == "completed"
    assert receipt["runtime_mutation"] is True


def test_existing_unit_drift_is_rejected_before_backup_or_mutation(tmp_path: Path) -> None:
    descriptor, digest = _render_descriptor(tmp_path / "native-units.json")
    arguments = _install_args(tmp_path, descriptor, digest)
    name = installer._service_unit("staging")
    installer._unit_path(arguments["unit_root"], name).write_bytes(b"unreviewed prior unit")

    with pytest.raises(installer.InstallerError, match="native_unit_existing_drift"):
        installer.install(**arguments, systemd=FakeSystemd(arguments["unit_root"]))

    assert (
        installer._unit_path(arguments["unit_root"], name).read_bytes() == b"unreviewed prior unit"
    )
    assert not arguments["receipt"].exists()


def test_deployment_lock_uses_exclusive_flock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events: list[tuple[int, int]] = []

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_UN = 2

        @staticmethod
        def flock(fd: int, operation: int) -> None:
            events.append((fd, operation))

    monkeypatch.setattr(installer, "fcntl", FakeFcntl)
    with installer.DeploymentLock(tmp_path / "application.lock", require_root=False):
        assert len(events) == 1
        assert events[0][1] == FakeFcntl.LOCK_EX
    assert events[1][1] == FakeFcntl.LOCK_UN
