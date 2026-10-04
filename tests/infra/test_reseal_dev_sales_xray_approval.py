"""Root commands are simulated; all credentials are fictional private fixtures."""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.service_config import load_service_config

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infra/application/scripts/reseal-dev-sales-xray-approval.py"
)
SPEC = importlib.util.spec_from_file_location("dev_reseal", SCRIPT)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)
SECRET = "fictional-test-secret-do-not-print"  # noqa: S105 - fictional redaction sentinel
EMAIL = "fictional-tester@example.invalid"


def put(path, raw, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_bytes(raw)
    path.chmod(mode)


def tree(root):
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mode)
        for path in root.rglob("*")
        if path.is_file()
    }


class Host:
    def __init__(self, paths, pins):
        self.paths = paths
        self.pins = pins
        self.states = dict.fromkeys((*tool.UNITS, tool.refresh.OUTBOX_UNIT), "active")
        self.calls = []
        self.loaded = {name: path.read_bytes() for name, path in paths.targets().items()}
        self.fail_once = None
        self.timer = "inactive"
        self.enabled = "disabled"
        self.runtime_hold = "true"
        self.health_release = pins.release

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        result, code = b"", 0
        if self.fail_once == argv[:3]:
            self.fail_once = None
            return subprocess.CompletedProcess(argv, 19, SECRET.encode(), SECRET.encode())
        if argv[0] == "git" and "rev-parse" in argv:
            result = self.pins.release.encode()
        elif argv[0] == "curl":
            result = json.dumps({"release_id": self.health_release}).encode()
        elif argv[:2] == ["systemctl", "is-active"]:
            state = self.timer if argv[2] == tool.TIMER else self.states.get(argv[2], "inactive")
            code = 0 if state == "active" else 3
            result = state.encode()
        elif argv[:2] == ["systemctl", "is-enabled"]:
            code = 1 if self.enabled == "disabled" else 0
            result = self.enabled.encode()
        elif argv[:2] == ["systemctl", "show"]:
            unit, prop = argv[2], argv[3].split("=", 1)[1]
            if prop in ("User", "Group"):
                result = b"10001"
            elif prop == "WorkingDirectory":
                result = str(self.paths.backend).encode()
            elif prop == "EnvironmentFiles":
                name = "api" if unit == tool.refresh.API_UNIT else "outbox"
                result = f"{self.paths.development / (name + '.env')} (ignore_errors=no)".encode()
            elif prop == "Environment":
                if unit == tool.refresh.API_UNIT:
                    result = f"AC_RELEASE_ID={self.pins.release}".encode()
                elif unit == tool.refresh.WORKER_UNIT:
                    digest = tool.manifest_pin(self.loaded["worker_dropin"])
                    result = f"{tool.WORKER_KEY}={digest}".encode()
            elif prop == "LoadCredential":
                result = (
                    f"approval.json:{self.paths.development / 'approval.json'} "
                    f"service.json:{self.paths.development / 'service.json'}"
                ).encode()
        elif argv[:2] == ["systemctl", "stop"]:
            self.states[argv[2]] = "inactive"
        elif argv[:2] == ["systemctl", "restart"]:
            # Only adopt installed credentials at a restart, as systemd does.
            self.states[argv[2]] = "active"
            self.loaded = {name: path.read_bytes() for name, path in self.paths.targets().items()}
        elif argv[:2] == ["systemctl", "daemon-reload"]:
            self.loaded["worker_dropin"] = self.paths.worker_dropin.read_bytes()
        elif argv[0] == "systemd-run":
            assert "User=10001" in argv and "Group=10001" in argv
            assert "PrivateNetwork=yes" in argv and "StandardError=null" in argv
            assert f"LoadCredential=candidate.json:{self.paths.candidate}" in argv
            assert not any("EnvironmentFile=" in arg for arg in argv)
            assert SECRET not in " ".join(argv) and EMAIL not in " ".join(argv)
        return subprocess.CompletedProcess(argv, code, result, SECRET.encode())

    def process_environment(self, _commands, unit):
        return 111, {
            tool.HOLD_KEY: self.runtime_hold,
            "AC_ENVIRONMENT": "development",
            tool.APPROVAL_KEY: tool.sha(self.loaded["approval"]),
        }

    def adopted(self, _paths, _commands, files, states):
        for unit in tool.UNITS:
            if states[unit] == "active":
                assert self.loaded["approval"] == files["approval"].raw
                if unit == tool.refresh.WORKER_UNIT:
                    assert self.loaded["service"] == files["service"].raw


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    dev = tmp_path / "etc/development"
    app = tmp_path / "application"
    paths = tool.Paths(
        development=dev,
        backend=tmp_path / "backend",
        application=app,
        worker_dropin=tmp_path / "systemd/worker/manifest.conf",
        api_dropin=tmp_path / "systemd/api/release.conf",
        candidate=app / "operator-inputs/aut-1083/approval-candidate-canonical.json",
        history=app / "operator-inputs/aut-1083/reseal-history",
        native=app / "operator-inputs/native.json",
        owner_uid=os.getuid(),
        trusted_root=tmp_path,
    )
    approval = {
        "schema": "ac.sales-xray.hosted-approval/1",
        "environment": "development",
        "provider_control_tenant_id": "10000000-0000-4000-8000-000000000001",
        "deployment_ref": "ref:deployment/fictional",
        "issued_at_epoch": 1,
        "expires_at_epoch": 4102444800,
        "budget_scope_id": "20000000-0000-4000-8000-000000000001",
        "budget_authorization_ref": "ref:approval/fictional",
        "budget_owner_id": "30000000-0000-4000-8000-000000000001",
        "intake_authorization_ref": "ref:intake/fictional",
        "intake_retention_ref": "ref:retention/fictional",
        "retention_days": 7,
        "max_stored_source_bytes": 1000,
        "allowances": [],
        "stages": [],
        "internal_tester_accounts": [
            {
                "id": "40000000-0000-4000-8000-000000000001",
                "email": "existing-fictional@example.invalid",
                "authorization_ref": "ref:approval/existing",
                "scopes": ["account_minutes"],
                "reason": "Approved internal tester exemption",
            }
        ],
    }
    before = load_hosted_approval_bundle(approval).to_json()
    approval["internal_tester_accounts"].append(
        {key: value for key, value in tool.MASKED_DIFF.items() if key != "path"}
    )
    approval["internal_tester_accounts"][-1]["email"] = EMAIL
    candidate = load_hosted_approval_bundle(approval).to_json()
    pins = tool.Pins(tool.sha(before), tool.sha(candidate), "b" * 40)
    service = {
        "schema_version": "ac.sales_xray.worker_service/1",
        "environment": "development",
        "release_id": pins.release,
        "operations_tenant_id": approval["provider_control_tenant_id"],
        "sales_xray_approval_path": "/fictional/development/credentials/approval.json",
        "sales_xray_approval_sha256": pins.before,
        "sales_xray_storage_root": "/fictional/development/recordings",
        "sales_xray_scratch_root": "/fictional/development/scratch",
        "database_url_file": "/fictional/development/credentials/database-url",
        "native_socket_path": "/fictional/development/native.sock",
        "native_image_ref": "sha256:" + "a" * 64,
        "providers": [
            {
                "credential_ref": "ref:credential/fictional",
                "provider_id": "gemini",
                "executable": "/opt/infisical",
                "project_ref": "fictional",
                "environment_ref": "development",
                "secret_path_ref": "/fictional",
                "token_file_ref": "/fictional/development/token",
            }
        ],
    }
    raw_service = (json.dumps(service, indent=2) + "\n").encode()
    template = {**service, "release_id": "a" * 40}
    put(dev / "approval.json", before)
    put(paths.candidate, candidate)
    put(dev / "service.json", raw_service)
    put(dev / "service.operator-template.json", tool.encoded(template))
    put(
        dev / "api.env",
        (
            "# preserve comment\nAC_ENVIRONMENT=development\n"
            f'{tool.HOLD_KEY}=true\n{tool.APPROVAL_KEY}="{pins.before}"\n'
            f'AC_INTERNAL_API_HOST=api.example.invalid\nAC_TEST_SECRET="{SECRET}"\nAC_EMPTY=\n'
        ).encode(),
    )
    put(
        dev / "outbox.env",
        f"AC_ENVIRONMENT=development\n{tool.HOLD_KEY}=true\nAC_TEST_SECRET={SECRET}\n".encode(),
    )
    put(paths.backend / ".ac-release-id", (pins.release + "\n").encode(), 0o644)
    put(paths.api_dropin, f"[Service]\nEnvironment=AC_RELEASE_ID={pins.release}\n".encode(), 0o644)
    put(
        paths.worker_dropin,
        f"[Service]\nEnvironment={tool.WORKER_KEY}={tool.sha(raw_service)}\n".encode(),
        0o644,
    )
    put(paths.native, tool.encoded({"environment": "development", "helper_source_sha": "a" * 40}))
    put(app / ".deployment.lock", b"lock", 0o640)
    for directory in tmp_path.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o700)
    host = Host(paths, pins)
    monkeypatch.setattr(tool.refresh, "runtime_identity", lambda: None)
    monkeypatch.setattr(tool, "process_environment", host.process_environment)
    monkeypatch.setattr(tool, "adopted_credentials", host.adopted)
    monkeypatch.setattr(tool.refresh, "HEALTH_WAIT_SECONDS", 0)
    return paths, pins, host


def run(fixture, apply=False):
    paths, pins, host = fixture
    return tool.reseal(paths, pins=pins, runner=host, uid=0, apply=apply)


def test_dry_run_has_no_writes_or_service_mutations(fixture):
    paths, _, host = fixture
    before = tree(paths.trusted_root)
    report = run(fixture)
    assert tree(paths.trusted_root) == before
    assert report["apply"] is False and report["noop"] is False
    assert not paths.history.exists()
    assert not any(
        call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed", "daemon-reload")
        for call in host.calls
    )
    assert any(call[0] == "systemd-run" for call in host.calls)


def test_apply_pins_agree_preserves_other_bytes_and_repeat_is_noop(fixture):
    paths, pins, host = fixture
    before, guards = tool.snapshot(paths)
    report = run(fixture, apply=True)
    after, after_guards = tool.snapshot(paths)
    assert after_guards == guards
    assert tool.sha(after["approval"].raw) == pins.after
    assert tool.assignments(after["api_env"].raw)[tool.APPROVAL_KEY] == pins.after
    for name in ("template", "service"):
        old, new = tool.decoded(before[name].raw), tool.decoded(after[name].raw)
        new["sales_xray_approval_sha256"] = pins.before
        assert old == new
    assert (
        after["api_env"].raw.replace(pins.after.encode(), pins.before.encode())
        == before["api_env"].raw
    )
    assert tool.manifest_pin(after["worker_dropin"].raw) == tool.sha(after["service"].raw)
    mutations = [
        call
        for call in host.calls
        if call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed")
    ]
    assert all(call[2] in tool.UNITS for call in mutations)
    assert [call[2] for call in mutations if call[1] == "restart"] == list(tool.UNITS)
    assert (
        paths.history.joinpath(report["run_id"], "approval.before").read_bytes()
        == before["approval"].raw
    )
    assert all(path.stat().st_mode & 0o077 == 0 for path in paths.history.rglob("*"))
    before_repeat = tree(paths.trusted_root)
    host.calls.clear()
    assert run(fixture, apply=True)["noop"] is True
    assert tree(paths.trusted_root) == before_repeat
    assert not any(call[0] == "systemctl" and call[1] == "restart" for call in host.calls)


@pytest.mark.parametrize(
    "change",
    [
        "budget_cap_paise",
        "allowances",
        "stages",
        "intake_retention_ref",
        "expires_at_epoch",
        "retention_days",
        "acquisition_policy",
        "paid_approval_ref",
        "stage_call_supplements",
        "organisation_acquisition_policies",
    ],
)
def test_policy_changes_fail_before_writes_even_with_resealed_candidate_pin(fixture, change):
    paths, pins, host = fixture
    value = tool.decoded(paths.candidate.read_bytes())
    value[change] = "unauthorized"
    raw = tool.encoded(value)
    paths.candidate.write_bytes(raw)
    altered = (paths, replace(pins, after=tool.sha(raw)), host)
    before = tree(paths.trusted_root)
    with pytest.raises(tool.ResealError, match="policy_change_unauthorized"):
        run(altered, apply=True)
    assert tree(paths.trusted_root) == before
    assert host.calls == []


@pytest.mark.parametrize("change", ["id", "authorization_ref", "reason", "scopes", "extra"])
def test_tester_scope_identity_and_reference_are_fixed(fixture, change):
    paths, pins, host = fixture
    value = tool.decoded(paths.candidate.read_bytes())
    value["internal_tester_accounts"][-1][change] = (
        ["analysis_count"] if change == "scopes" else "unauthorized"
    )
    raw = tool.encoded(value)
    paths.candidate.write_bytes(raw)
    before = tree(paths.trusted_root)
    with pytest.raises(tool.ResealError, match="tester_change_unauthorized"):
        run((paths, replace(pins, after=tool.sha(raw)), host), apply=True)
    assert tree(paths.trusted_root) == before


@pytest.mark.parametrize("target", ["approval", "api_env", "service", "template", "worker_dropin"])
def test_stale_pins_fail_without_writes(fixture, target):
    paths, pins, _ = fixture
    path = paths.targets()[target]
    raw = path.read_bytes()
    path.write_bytes(
        raw.replace(pins.before.encode(), b"c" * 64) if target != "approval" else raw + b"\n"
    )
    if target == "worker_dropin":
        path.write_bytes(raw.replace(tool.manifest_pin(raw).encode(), b"c" * 64))
    before = tree(paths.trusted_root)
    with pytest.raises(tool.ResealError):
        run(fixture, apply=True)
    assert tree(paths.trusted_root) == before


@pytest.mark.parametrize(
    "control",
    ["api-file-hold", "outbox-file-hold", "runtime-hold", "timer-active", "timer-enabled"],
)
def test_holds_and_timer_fail_closed(fixture, control):
    paths, _, host = fixture
    if control.endswith("file-hold"):
        path = paths.development / ("api.env" if control.startswith("api") else "outbox.env")
        path.write_bytes(path.read_bytes().replace(b"HOLD=true", b"HOLD=false"))
    elif control == "runtime-hold":
        host.runtime_hold = "false"
    elif control == "timer-active":
        host.timer = "active"
    else:
        host.enabled = "enabled"
    before = tree(paths.trusted_root)
    with pytest.raises(tool.ResealError):
        run(fixture, apply=True)
    assert tree(paths.trusted_root) == before


@pytest.mark.parametrize("unit", tool.UNITS)
def test_restart_failure_restores_exact_bytes_and_prior_unit_states(fixture, unit):
    paths, _, host = fixture
    files, guards = tool.snapshot(paths)
    states = host.states.copy()
    host.fail_once = ["systemctl", "restart", unit]
    with pytest.raises(tool.ResealError, match="apply_failed_restored"):
        run(fixture, apply=True)
    assert tool.snapshot(paths) == (files, guards)
    assert host.states == states
    events = list(paths.history.glob("*/failed-restored-*.json"))
    assert len(events) == 1
    assert any(item["exit"] == 19 for item in json.loads(events[0].read_bytes())["command_exits"])
    assert SECRET not in events[0].read_text() and EMAIL not in events[0].read_text()


def test_health_failure_restores_and_keeps_inactive_unit_inactive(fixture, monkeypatch):
    paths, _, host = fixture
    host.states[tool.refresh.WORKER_UNIT] = "inactive"
    before = tool.snapshot(paths)
    states = host.states.copy()
    original = tool.healthy
    calls = 0

    def fail_new(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise tool.ResealError("health_release_mismatch")
        return original(*args)

    monkeypatch.setattr(tool, "healthy", fail_new)
    with pytest.raises(tool.ResealError, match="apply_failed_restored"):
        run(fixture, apply=True)
    assert tool.snapshot(paths) == before
    assert host.states == states


def test_partial_write_failure_restores_every_file(fixture, monkeypatch):
    paths, _, _ = fixture
    before = tool.snapshot(paths)
    original = tool.write
    once = True

    def fail_service(path, value):
        nonlocal once
        if once and path == paths.targets()["service"]:
            once = False
            raise OSError(SECRET)
        return original(path, value)

    monkeypatch.setattr(tool, "write", fail_service)
    with pytest.raises(tool.ResealError, match="apply_failed_restored"):
        run(fixture, apply=True)
    assert tool.snapshot(paths) == before


def test_explicit_rollback_is_dry_by_default_idempotent_and_guarded(fixture):
    paths, pins, host = fixture
    before = tool.snapshot(paths)
    report = run(fixture, apply=True)
    applied = tree(paths.trusted_root)
    result = tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0)
    assert result["apply"] is False and tree(paths.trusted_root) == applied
    tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)
    assert tool.snapshot(paths) == before
    rolled_back = tree(paths.trusted_root)
    assert (
        tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)["noop"]
        is True
    )
    assert tree(paths.trusted_root) == rolled_back
    paths.api_dropin.write_bytes(b"[Service]\n# changed elsewhere\n")
    with pytest.raises(tool.ResealError, match="rollback_guard_changed"):
        tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)


def test_rollback_recovers_interruption_before_daemon_reload(fixture):
    paths, pins, host = fixture
    before = tool.snapshot(paths)
    report = run(fixture, apply=True)
    directory = paths.history / report["run_id"]
    # Reproduce mixed files and a loaded manifest from the other recorded state.
    for name in ("service", "worker_dropin"):
        paths.targets()[name].write_bytes((directory / (name + ".before")).read_bytes())
    host.states[tool.refresh.API_UNIT] = "inactive"
    host.states[tool.refresh.WORKER_UNIT] = "inactive"
    tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)
    assert tool.snapshot(paths) == before
    assert all(value == "active" for value in host.states.values())


def test_lock_contention_refuses_before_commands(fixture):
    paths, _, host = fixture
    before = tree(paths.trusted_root)
    with (paths.application / ".deployment.lock").open("rb") as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(tool.ResealError, match="deployment_busy"):
            run(fixture, apply=True)
    assert tree(paths.trusted_root) == before
    assert host.calls == []


def test_non_root_and_runtime_validation_failure_write_nothing(fixture):
    paths, pins, host = fixture
    before = tree(paths.trusted_root)
    with pytest.raises(tool.ResealError, match="root_required"):
        tool.reseal(paths, pins=pins, runner=host, uid=1000, apply=True)
    host.fail_once = ["systemd-run", "--wait", "--collect"]
    with pytest.raises(tool.ResealError, match="command_failed") as error:
        run(fixture, apply=True)
    assert error.value.report["command_exits"][-1] == {
        "command": "uid10001_contract_validation",
        "exit": 19,
    }
    assert SECRET not in json.dumps(error.value.report) and EMAIL not in json.dumps(
        error.value.report
    )
    assert tree(paths.trusted_root) == before


def test_unreviewed_helper_cannot_execute(monkeypatch):
    name = "prepare-sales-xray-native-activation.py"
    monkeypatch.setitem(tool.HELPER_SHA256, name, "0" * 64)
    with pytest.raises(RuntimeError, match="reviewed_helper_digest_mismatch"):
        tool.sibling(name)


def test_confidentiality_of_report_and_cli_failure(fixture, monkeypatch, capsys):
    report = json.dumps(run(fixture))
    assert SECRET not in report and EMAIL not in report

    def fail(_paths, **_kwargs):
        raise OSError(SECRET + EMAIL)

    monkeypatch.setattr(tool, "reseal", fail)
    assert tool.main([]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.err and EMAIL not in output.err
    assert json.loads(output.err)["code"] == "reseal_failed"


@pytest.mark.parametrize("bad", ["symlink", "hardlink", "public", "wrong-owner", "parent-write"])
def test_untrusted_sources_rejected_before_commands(fixture, bad):
    paths, _, host = fixture
    path = paths.candidate
    if bad == "symlink":
        other = path.with_suffix(".other")
        path.rename(other)
        path.symlink_to(other)
    elif bad == "hardlink":
        os.link(path, path.with_suffix(".other"))
    elif bad == "public":
        path.chmod(0o644)
    elif bad == "wrong-owner":
        paths = replace(paths, owner_uid=paths.owner_uid + 1)
    else:
        path.parent.chmod(0o770)
    with pytest.raises(tool.ResealError):
        run((paths, fixture[1], host), apply=True)
    assert host.calls == []


def test_runtime_credentials_use_real_serving_contract_and_expiry(fixture, monkeypatch):
    paths, pins, _ = fixture
    import ac_platform.conversation_intelligence.service_config as config

    original_read = config.read_private_file
    mapping = {
        "current.json": paths.development / "approval.json",
        "candidate.json": paths.candidate,
        "service.json": paths.development / "service.json",
        "template.json": paths.development / "service.operator-template.json",
    }

    def read_credential(path, **kwargs):
        return original_read(mapping[path.name], **kwargs)

    configs = {
        name: load_service_config(path, tool.sha(path.read_bytes()))
        for name, path in mapping.items()
        if name in ("service.json", "template.json")
    }
    monkeypatch.setattr(config, "read_private_file", read_credential)
    monkeypatch.setattr(config, "load_service_config", lambda path, _digest: configs[path.name])
    monkeypatch.setattr(config, "verify_installed_release", lambda _config, _marker: None)
    monkeypatch.setattr(tool.os, "geteuid", lambda: 10001)
    files, _ = tool.snapshot(paths)
    arguments = [
        pins.release,
        pins.before,
        pins.after,
        tool.sha(files["service"].raw),
        tool.sha(files["template"].raw),
    ]
    tool.validate_credentials(arguments)
    value = tool.decoded(paths.candidate.read_bytes())
    value["expires_at_epoch"] = 2
    raw = load_hosted_approval_bundle(value).to_json()
    put(paths.candidate, raw)
    # Bypass the append comparison to isolate the real current-contract expiry gate.
    monkeypatch.setattr(tool, "permitted_diff", lambda *_: None)
    arguments[2] = tool.sha(raw)
    with pytest.raises(Exception, match="replacement approval is not current"):
        tool.validate_credentials(arguments)
