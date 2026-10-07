from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.infra.test_sales_xray_native_installer import FakeGroup, FakeSystemd, installer
from tests.unit.test_native_artifact_compatibility import MODULE as verifier
from tests.unit.test_native_artifact_compatibility import ROOT, Bundle, git

SCRIPT = ROOT / "infra/application/scripts/prepare-dev-sales-xray-native.py"
SPEC = importlib.util.spec_from_file_location("prepare_dev_sales_xray_native", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Systemd(FakeSystemd):
    def _run(self, argv):
        assert argv[:2] == ["/usr/bin/systemctl", "start"]
        self.events.append(("start", argv[-1]))
        self.active[argv[-1]] = True
        return ""


class Host:
    def __init__(self, paths, image):
        self.paths = paths
        self.image = image
        self.systemd = Systemd(paths.units)
        self.readiness_failure = False
        self.client_failure = False
        self.refresh = SimpleNamespace(
            Paths=lambda **values: SimpleNamespace(**values),
            command=None,
            check_native=self.check_native,
        )

    def check_native(self, paths, runner, target):
        # The production helper checks the real descriptor and Git-object inputs.
        from tests.infra.test_refresh_dev_sales_xray_backend import refresh

        def run(argv, **kwargs):
            import subprocess

            return subprocess.run(argv, capture_output=True, check=False)  # noqa: S603

        refresh.check_native(paths, run, target)

    def inspect(self):
        return {
            unit: {
                "active": "active" if self.systemd.is_active(unit) else "inactive",
                "enabled": "enabled" if self.systemd.is_enabled(unit) else "disabled",
                **({"pid": "222", "invocation": "unchanged"} if unit == MODULE.OUTBOX else {}),
            }
            for unit in (*MODULE.CLIENTS, MODULE.OUTBOX, MODULE.TIMER, MODULE.NATIVE)
        }

    def live_bindings(self, files, image, approval, states):
        if self.client_failure and image == self.image:
            raise MODULE.TransitionError("fake_live_binding_failure")
        assert MODULE.env_value(files["api_env"].raw, MODULE.IMAGE_KEY) == image
        assert MODULE.decoded(files["service"].raw)["native_image_ref"] == image
        assert MODULE.decoded(files["template"].raw)["native_image_ref"] == image
        assert MODULE.env_value(files["api_env"].raw, "AC_SALES_XRAY_APPROVAL_SHA256") == approval

    def readiness(self, release):
        if self.readiness_failure:
            self.readiness_failure = False
            raise MODULE.TransitionError("fake_readiness_failure")


class Fixture:
    def __init__(self, root, monkeypatch):
        self.root = root
        bundle = self.bundle = Bundle(root)
        for name in (*MODULE.CODE, "render-sales-xray-native.py"):
            path = bundle.repo / "infra/application/scripts" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / "infra/application/scripts" / name).read_bytes())
        git(bundle.repo, "add", ".")
        git(bundle.repo, "commit", "-qm", "Fictional installed native predecessor")
        self.previous = git(bundle.repo, "rev-parse", "HEAD")
        (bundle.repo / "ui.txt").write_text("native-source unrelated file")
        git(bundle.repo, "add", ".")
        git(bundle.repo, "commit", "-qm", "Fictional retained ordinary native")
        bundle.source = git(bundle.repo, "rev-parse", "HEAD")
        (bundle.repo / "ui.txt").write_text("staging core unrelated file")
        git(bundle.repo, "add", ".")
        git(bundle.repo, "commit", "-qm", "Fictional installed core")
        bundle.target = git(bundle.repo, "rev-parse", "HEAD")
        (bundle.repo / "ui.txt").write_text("released controller unrelated file")
        git(bundle.repo, "add", ".")
        git(bundle.repo, "commit", "-qm", "Fictional released operator")
        self.source = git(bundle.repo, "rev-parse", "HEAD")
        bundle.native["source_commit"] = bundle.source
        bundle.native["context_tree_id"] = git(bundle.repo, "rev-parse", bundle.source + "^{tree}")
        bundle.run.update(head_sha=bundle.source, event="push", head_branch="main", run_attempt=1)
        bundle.artifact["name"] = "ac-sales-xray-native-" + bundle.source
        bundle.artifact["workflow_run"]["head_sha"] = bundle.source
        bundle.refresh()
        application = root / "application"
        self.paths = MODULE.Paths(
            application=application,
            development=root / "development",
            units=root / "units",
            mirror=bundle.repo / ".git",
            backend=bundle.repo,
            studio=bundle.repo,
            release_lock=root / "release.lock",
            owner_uid=os.getuid(),
            owner_gid=os.getgid(),
            trusted_root=root,
        )
        for path in (
            self.paths.development,
            self.paths.units,
            application / "operator-inputs/development/aut-1083",
            application / "deployments/development",
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.write(self.paths.release_lock, b"existing release lock", 0o640)
        self.write(application / ".deployment.lock", b"existing deployment lock", 0o640)
        # N has NO installed core directory. Its bytes still have released provenance.
        for source in (self.previous, bundle.target, self.source):
            release = application / "releases" / source
            sums = []
            self.write(release / "RELEASE-COMMIT", (source + "\n").encode())
            for name in (*MODULE.CODE, "render-sales-xray-native.py"):
                raw = (ROOT / "infra/application/scripts" / name).read_bytes()
                self.write(release / "scripts" / name, raw)
                sums.append(f"{MODULE.sha(raw)}  ./scripts/{name}\n")
            self.write(release / "RELEASE-FILES.sha256", "".join(sums).encode())
        (application / "current-staging").symlink_to(application / "releases" / bundle.target)
        (application / "current-production").symlink_to(application / "releases" / self.previous)
        new_manifest = self.artifact(bundle.source, bundle.native)
        previous_manifest = json.loads(json.dumps(bundle.native))
        previous_manifest["source_commit"] = self.previous
        previous_manifest["image"] = {
            "identity_type": "oci_transport_manifest",
            "expected_runtime_ref": "sha256:" + "c" * 64,
            "image_id": "sha256:" + "d" * 64,
        }
        previous_manifest["transport"].update(
            manifest_digest="sha256:" + "c" * 64, config_digest="sha256:" + "d" * 64
        )
        self.previous_manifest = self.artifact(self.previous, previous_manifest)
        self.old_image = previous_manifest["image"]["expected_runtime_ref"]
        renderer = application / "releases" / self.previous / "scripts/render-sales-xray-native.py"
        binding = installer.NativeBinding(self.previous, self.old_image, "sha256:" + "d" * 64)
        previous_descriptor, _ = installer._rendered_descriptor(
            renderer=renderer,
            renderer_python=Path("/usr/bin/python3"),
            environment="development",
            canonical_paths=False,
            binding=binding,
        )
        self.write(self.paths.descriptor, MODULE.encoded(previous_descriptor), 0o640)
        self.host = Host(self.paths, bundle.native["image"]["expected_runtime_ref"])
        for unit, raw in previous_descriptor["units"].items():
            self.write(self.paths.units / unit, raw.encode())
            self.host.systemd.active[unit] = self.host.systemd.enabled[unit] = True
        for unit in (*MODULE.CLIENTS, MODULE.OUTBOX):
            self.host.systemd.active[unit] = True
            self.host.systemd.enabled[unit] = unit != MODULE.OUTBOX
        self.write(bundle.repo / ".ac-release-id", (self.previous + "\n").encode())
        self.write(
            self.paths.development / "approval.json",
            b'{"approved":"unchanged fictional scopes"}',
            0o600,
        )
        approval = MODULE.sha((self.paths.development / "approval.json").read_bytes())
        service = {
            "schema_version": "ac.sales_xray.worker_service/1",
            "environment": "development",
            "release_id": self.previous,
            "native_image_ref": self.old_image,
            "native_socket_path": "/run/ac-sales-xray/development/native.sock",
            "sales_xray_approval_sha256": approval,
            "providers": [{"provider_id": "fictional", "scope": "preserve"}],
            "storage": "preserve",
            "identity": "preserve",
        }
        for name in ("service.json", "service.operator-template.json"):
            self.write(self.paths.development / name, MODULE.encoded(service), 0o600)
        self.write(
            self.paths.development / "api.env",
            f"AC_ENVIRONMENT=development\n{MODULE.IMAGE_KEY}={self.old_image}\nAC_SALES_XRAY_APPROVAL_SHA256={approval}\nPROTECTED_FICTIONAL_SETTING=keep-exact-bytes\n".encode(),
            0o600,
        )
        self.write(
            self.paths.targets()["worker_dropin"],
            MODULE.worker_dropin(MODULE.sha(MODULE.encoded(service))),
        )
        self.write(
            self.paths.units / (MODULE.API + ".d/release.conf"),
            b"[Service]\n# untouched release binding\n",
        )
        for unit in (
            MODULE.API,
            MODULE.WORKER,
            MODULE.OUTBOX,
            "ac-dev-sales-xray-refresh.service",
            MODULE.TIMER,
        ):
            self.write(self.paths.units / unit, b"unchanged fictional unit bytes\n")
        self.write(self.paths.development / "outbox.env", b"unchanged fictional outbox\n", 0o600)
        self.write(
            application / "operator-inputs/development/aut-1083/candidate.json",
            b"unchanged fictional protected candidate\n",
            0o600,
        )
        self.previous_receipt = application / "deployments/development/previous-install.json"
        self.write(
            self.previous_receipt,
            MODULE.encoded(
                {
                    "status": "installed",
                    "environment": "development",
                    "helper_source_sha": self.previous,
                    "native_units_sha256": MODULE.sha(self.paths.descriptor.read_bytes()),
                    "native_image_ref": self.old_image,
                    "native_image_config_id": "sha256:" + "d" * 64,
                }
            ),
            0o640,
        )
        self.args = SimpleNamespace(
            source_sha=self.source,
            target_core=bundle.target,
            native_reuse_proof=bundle.proof_path,
            native_reuse_proof_sha256=MODULE.sha(bundle.proof_path.read_bytes()),
            native_artifact_sha256=MODULE.sha(new_manifest.read_bytes()),
            previous_native_units_sha256=MODULE.sha(self.paths.descriptor.read_bytes()),
            previous_manifest=self.previous_manifest,
            previous_manifest_sha256=MODULE.sha(self.previous_manifest.read_bytes()),
            previous_receipt=self.previous_receipt,
            previous_receipt_sha256=MODULE.sha(self.previous_receipt.read_bytes()),
        )
        monkeypatch.setattr(
            installer,
            "SubprocessDocker",
            lambda binding: SimpleNamespace(inspect_identity=lambda: binding.image_ref),
        )
        monkeypatch.setattr(installer, "SubprocessGroup", FakeGroup)
        monkeypatch.setattr(installer, "NATIVE_READINESS_TIMEOUT_SECONDS", 0)
        self.receipt = application / "deployments/development/new-install.json"
        for path in root.rglob("*"):
            if not path.is_symlink():
                path.chmod(stat_mode(path) & ~0o022)

    def write(self, path, raw, mode=0o644):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(mode)

    def artifact(self, source, manifest):
        path = self.paths.application / "artifacts" / ("sales-xray-native-" + source)
        self.write(path / "native-image.json", MODULE.encoded(manifest), 0o640)
        self.write(
            path / "native-helper.tar.gz", self.bundle.payload["native-helper.tar.gz"], 0o640
        )
        with tarfile.open(path / "native-helper.tar.gz", "r:gz") as archive:
            for member in archive.getmembers():
                stream = archive.extractfile(member)
                assert stream
                self.write(path / "helper" / member.name, stream.read(), 0o640)
        # Candidate manifest bytes must exactly match the retained ZIP.
        if source == self.bundle.source:
            (path / "native-image.json").write_bytes(self.bundle.manifest.read_bytes())
        return path / "native-image.json"

    def prepare(self):
        return MODULE.prepare(self.paths, self.args, installer, verifier, self.host, root=False)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): (
                path.read_bytes(),
                stat_mode(path),
                path.stat().st_uid,
                path.stat().st_gid,
            )
            for path in self.root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

    def apply(self, prepared):
        return MODULE.apply(self.paths, *prepared, installer, self.host, self.receipt)


def stat_mode(path):
    return path.stat().st_mode & 0o7777


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    return Fixture(tmp_path, monkeypatch)


def test_dry_run_without_native_core_is_invariant_and_verifies_real_bundle(fixture):
    before = fixture.snapshot()
    states = fixture.host.inspect()
    plan, previous, candidate, units = fixture.prepare()
    assert fixture.snapshot() == before
    assert fixture.host.inspect() == states
    assert len(plan["compatibility"]["inputs"]) == 14
    assert not (fixture.paths.application / "releases" / fixture.bundle.source).exists()
    assert plan["renderer_sha256"] == MODULE.RENDERER_HASH
    assert plan["target_core"] == fixture.bundle.target
    assert candidate["descriptor"].raw != previous["descriptor"].raw
    assert not any(
        event[0] in {"stop", "start", "enable_now", "daemon_reload"}
        for event in fixture.host.systemd.events
    )


def test_success_publishes_matching_units_clients_descriptor_and_earns_unchanged_guard(fixture):
    prepared = fixture.prepare()
    plan, before, after, units = prepared
    result = fixture.apply(prepared)
    assert result["status"] == "installed" and result["native_guard"] == "PASS"
    assert MODULE.protected(fixture.paths) == plan["protected"]
    assert fixture.host.inspect() == plan["states"]
    for name, value in after.items():
        assert MODULE.read(fixture.paths.targets()[name], fixture.paths) == value
    for name, text in units.items():
        assert (fixture.paths.units / name).read_bytes() == text.encode()
    events = fixture.host.systemd.events
    assert events.index(("stop", MODULE.WORKER)) < events.index(("stop", MODULE.NATIVE))
    assert events.index(("stop", MODULE.API)) < events.index(("stop", MODULE.NATIVE))
    assert events.index(("enable_now", MODULE.NATIVE)) < events.index(("start", MODULE.API))
    assert not any(
        event[1] in {MODULE.OUTBOX, MODULE.TIMER} and event[0] in {"stop", "start", "enable_now"}
        for event in events
    )
    backup = Path(result["rollback_backup"])
    assert stat_mode(backup) == 0o700
    for name, value in before.items():
        assert (backup / name).read_bytes() == value.raw
        assert stat_mode(backup / name) == 0o600


@pytest.mark.parametrize(
    "target",
    [
        "native_stop",
        "native_start",
        "client_readback",
        "readiness",
        "guard",
        "reload",
        "publish_native",
        "publish_api_env",
        "publish_service",
        "publish_template",
        "publish_worker_dropin",
        "publish_descriptor",
        "receipt",
    ],
)
def test_each_failure_restores_exact_descriptor_clients_units_and_states(
    fixture, monkeypatch, target
):
    prepared = fixture.prepare()
    plan, before, after, units = prepared
    old_units = {name: MODULE.read(fixture.paths.units / name, fixture.paths) for name in units}
    if target == "native_stop":
        original = fixture.host.systemd.stop

        def fail_stop(unit):
            if unit != MODULE.NATIVE:
                original(unit)

        monkeypatch.setattr(fixture.host.systemd, "stop", fail_stop)
    elif target == "native_start":
        original = fixture.host.systemd.enable_now
        once = [True]

        def fail_start(unit):
            if unit == MODULE.NATIVE and once.pop() if once else False:
                raise installer.InstallerError("fictional_start_failed")
            original(unit)

        monkeypatch.setattr(fixture.host.systemd, "enable_now", fail_start)
    elif target == "client_readback":
        fixture.host.client_failure = True
    elif target == "readiness":
        fixture.host.readiness_failure = True
    elif target == "guard":
        monkeypatch.setattr(
            fixture.host.refresh,
            "check_native",
            lambda *args: MODULE.require(False, "fictional_guard_failure"),
        )
    elif target == "reload":
        once = [True]
        original = fixture.host.systemd.daemon_reload

        def reload():
            if once:
                once.pop()
                raise installer.InstallerError("fictional_reload_failed")
            original()

        monkeypatch.setattr(fixture.host.systemd, "daemon_reload", reload)
    else:
        original = MODULE.replace
        selected = (
            fixture.receipt
            if target == "receipt"
            else (fixture.paths.units / next(name for name in units if name.endswith(".service")))
            if target == "publish_native"
            else fixture.paths.targets()[target.removeprefix("publish_")]
        )
        once = [True]

        def fail_replace(path, value):
            if path == selected and once:
                once.pop()
                raise OSError("fictional_publish_failed")
            original(path, value)

        monkeypatch.setattr(MODULE, "replace", fail_replace)
    with pytest.raises(MODULE.TransitionError) as error:
        fixture.apply(prepared)
    assert error.value.report["rollback"] == "completed"
    assert fixture.host.inspect() == plan["states"]
    assert MODULE.protected(fixture.paths) == plan["protected"]
    for name, value in before.items():
        assert MODULE.read(fixture.paths.targets()[name], fixture.paths) == value
    for name, value in old_units.items():
        assert MODULE.read(fixture.paths.units / name, fixture.paths) == value
    if target == "native_stop":
        assert not any(event[0] == "daemon_reload" for event in fixture.host.systemd.events)


@pytest.mark.parametrize(
    "target",
    [
        "renderer",
        "source_renderer",
        "proof",
        "archive",
        "manifest",
        "helper",
        "unit",
        "descriptor",
        "receipt",
        "api_image",
        "worker_image",
        "worker_pin",
        "ci_attempt",
        "ci_dispatch",
        "compatibility_mode",
    ],
)
def test_provenance_or_current_binding_mismatch_refuses_before_mutation(fixture, target):
    if target == "renderer":
        path = (
            fixture.paths.application
            / "releases"
            / fixture.bundle.target
            / "scripts/render-sales-xray-native.py"
        )
        path.write_bytes(path.read_bytes() + b"# drift\n")
    elif target == "source_renderer":
        path = fixture.bundle.repo / "infra/application/scripts/render-sales-xray-native.py"
        path.write_bytes(path.read_bytes() + b"# different committed source\n")
        git(fixture.bundle.repo, "add", ".")
        git(fixture.bundle.repo, "commit", "-qm", "Mismatched source renderer")
        fixture.args.target_core = git(fixture.bundle.repo, "rev-parse", "HEAD")
    elif target == "proof":
        fixture.bundle.proof_path.write_bytes(b"{}")
    elif target == "archive":
        fixture.bundle.archive.write_bytes(b"invalid archive")
    elif target == "manifest":
        manifest = (
            fixture.paths.application
            / "artifacts"
            / ("sales-xray-native-" + fixture.bundle.source)
            / "native-image.json"
        )
        manifest.write_bytes(b"{}")
    elif target == "helper":
        path = (
            fixture.paths.application
            / "artifacts"
            / ("sales-xray-native-" + fixture.bundle.source)
            / "helper/scripts/native_runtime_helper.py"
        )
        path.write_bytes(b"changed helper")
    elif target == "unit":
        (fixture.paths.units / MODULE.NATIVE).write_bytes(b"different installed bytes")
    elif target == "descriptor":
        fixture.paths.descriptor.write_bytes(b"{}")
    elif target == "receipt":
        fixture.previous_receipt.write_bytes(b"{}")
    elif target == "api_image":
        path = fixture.paths.development / "api.env"
        path.write_bytes(
            path.read_bytes().replace(fixture.old_image.encode(), b"sha256:" + b"e" * 64)
        )
    elif target == "worker_image":
        path = fixture.paths.development / "service.json"
        value = MODULE.decoded(path.read_bytes())
        value["native_image_ref"] = "sha256:" + "e" * 64
        path.write_bytes(MODULE.encoded(value))
    elif target == "worker_pin":
        fixture.paths.targets()["worker_dropin"].write_bytes(MODULE.worker_dropin("0" * 64))
    elif target in {"ci_attempt", "ci_dispatch"}:
        fixture.bundle.run["run_attempt" if target == "ci_attempt" else "event"] = (
            2 if target == "ci_attempt" else "workflow_dispatch"
        )
        fixture.bundle.refresh()
        fixture.args.native_reuse_proof_sha256 = MODULE.sha(fixture.bundle.proof_path.read_bytes())
    elif target == "compatibility_mode":
        git(fixture.bundle.repo, "update-index", "--chmod=+x", ".dockerignore")
        git(fixture.bundle.repo, "commit", "-qm", "Changed native mode")
        fixture.args.target_core = git(fixture.bundle.repo, "rev-parse", "HEAD")
    before = fixture.snapshot()
    events = list(fixture.host.systemd.events)
    with pytest.raises(
        (
            MODULE.TransitionError,
            verifier.NativeCompatibilityError,
            installer.InstallerError,
            OSError,
        )
    ):
        fixture.prepare()
    assert fixture.snapshot() == before
    assert fixture.host.systemd.events == events


def test_native_client_renderer_preserves_all_non_native_values_and_environment_bytes(fixture):
    plan, before, after, units = fixture.prepare()
    for name in ("service", "template"):
        old, new = MODULE.decoded(before[name].raw), MODULE.decoded(after[name].raw)
        assert new == {**old, "native_image_ref": plan["compatibility"]["image_ref"]}
    assert after["api_env"].raw == before["api_env"].raw.replace(
        fixture.old_image.encode(), plan["compatibility"]["image_ref"].encode()
    )
    assert after["worker_dropin"].raw == MODULE.worker_dropin(MODULE.sha(after["service"].raw))


def test_root_identity_and_existing_lock_checks_refuse_without_creation(fixture, monkeypatch):
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 10001)
    with pytest.raises(MODULE.TransitionError, match="root_required"):
        MODULE.prepare(fixture.paths, fixture.args, installer, verifier, fixture.host)
    fixture.paths.release_lock.unlink()
    with pytest.raises(FileNotFoundError), MODULE.locks(fixture.paths):
        pass
    assert not fixture.paths.release_lock.exists()


def test_both_locks_are_exclusive_and_leave_bytes_unchanged(fixture):
    import fcntl

    before = fixture.snapshot()
    with MODULE.locks(fixture.paths):
        with pytest.raises(MODULE.TransitionError, match="busy"), MODULE.locks(fixture.paths):
            pass
        for path in (fixture.paths.release_lock, fixture.paths.application / ".deployment.lock"):
            with path.open("rb") as stream, pytest.raises(BlockingIOError):
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert fixture.snapshot() == before


def test_refresh_pin_remains_exact():
    assert (
        hashlib.sha256(
            (SCRIPT.parent / "refresh-dev-sales-xray-backend.py").read_bytes()
        ).hexdigest()
        == MODULE.REFRESH_HASH
    )
