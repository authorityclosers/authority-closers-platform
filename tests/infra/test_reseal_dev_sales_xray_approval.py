"""Root commands are simulated; all credentials are fictional private fixtures."""

from __future__ import annotations

import fcntl
import grp
import importlib.util
import json
import os
import runpy
import stat
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import pytest

from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.service_config import load_service_config

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "infra/application/scripts/reseal-dev-sales-xray-approval.py"
)
SCRIPT = Path(os.environ.get("AC_RESEAL_REVIEWED_SCRIPT", str(SCRIPT)))
SPEC = importlib.util.spec_from_file_location("dev_reseal", SCRIPT)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)
REAL_RUNTIME_IDENTITY = tool.refresh.runtime_identity
SECRET = "fictional-test-secret-do-not-print"  # noqa: S105 - fictional redaction sentinel
EMAIL = "fictional-tester@example.invalid"
LATER_RELEASE = "0e7b7fa6b99c2f2e46e4df02e012f1fe68f09c20"
TEMPLATE_RELEASE = "1e784afa128f8d4629aeece5179486d423c0ec52"
SYSTEMD_255_SENTINEL = b"LoadCredential=[unprintable]\n"
UID10001_SOURCE_DENIAL = """import json, os, sys
assert (os.geteuid(), os.getegid()) == (10001, 10001)
assert not set(os.getgroups()) - {10001}
for source in json.loads(sys.argv[1]):
    try:
        with open(source, "rb"):
            pass
    except (PermissionError, FileNotFoundError):
        continue
    raise SystemExit("installed_source_unexpectedly_readable")
"""
# Test-only in-memory pin substitution after the unchanged code/hash bootstrap.
# No source bytes or validator/helper functions are changed in this harness.
FICTIONAL_CONTRACT_BOOTSTRAP = """import runpy, sys
bootstrap = sys.argv.pop(1)
original_run = runpy.run_path
def fictional_contract(path, *, run_name):
    assert run_name == "__main__"
    namespace = original_run(path, run_name="fictional_reseal_contract")
    assert namespace["APPROVAL_BEFORE"] == (
        "07ca6c4ea9587ff81b7bd97a891eb81f1195179ca4eb3ff8fa03205267225881")
    assert sys.argv[1] == "--validate-credentials"
    validate = namespace["validate_credentials"]
    validate.__globals__["APPROVAL_BEFORE"] = sys.argv[3]
    validate(sys.argv[2:])
runpy.run_path = fictional_contract
exec(bootstrap)
"""


def fictional_contract_command(argv, fixture_backend, backend):
    """Expose the verified interpreter; keep marker/credentials fictional and private."""
    actual = argv.copy()
    position = actual.index("--") + 1
    assert actual[position] == str(fixture_backend / ".venv/bin/python")
    actual[position] = str(backend / ".venv/bin/python")
    for property_name in ("WorkingDirectory", "BindReadOnlyPaths"):
        index = actual.index(f"{property_name}={fixture_backend}")
        actual[index] = f"{property_name}={backend}"
    index = actual.index(tool.CODE_BOOTSTRAP)
    actual[index : index + 1] = [FICTIONAL_CONTRACT_BOOTSTRAP, tool.CODE_BOOTSTRAP]
    return actual


UNIT_OBJECTS = {
    tool.refresh.API_UNIT: "/org/freedesktop/systemd1/unit/ac_2ddev_2dapi_2eservice",
    tool.refresh.WORKER_UNIT: (
        "/org/freedesktop/systemd1/unit/ac_2ddev_2dsales_2dxray_2dworker_2eservice"
    ),
}
# Captured typed mappings contain source paths only, never credential values.
SYSTEMD_255_CREDENTIALS = {
    tool.refresh.API_UNIT: {
        "type": "a(ss)",
        "data": [["approval.json", "/etc/authority-closers/development/approval.json"]],
    },
    tool.refresh.WORKER_UNIT: {
        "type": "a(ss)",
        "data": [
            ["service.json", "/etc/authority-closers/development/service.json"],
            ["approval.json", "/etc/authority-closers/development/approval.json"],
        ],
    },
}


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
        self.git_release = pins.release
        self.api_release = pins.release
        self.bus_replies = {}
        for unit, response in SYSTEMD_255_CREDENTIALS.items():
            self.bus_replies[unit, "GetUnit"] = tool.encoded(
                {"type": "o", "data": [UNIT_OBJECTS[unit]]}
            )
            self.bus_replies[unit, "LoadCredential"] = tool.encoded(
                {
                    "type": response["type"],
                    "data": [
                        [
                            name,
                            source.replace(
                                "/etc/authority-closers/development", str(paths.development)
                            ),
                        ]
                        for name, source in response["data"]
                    ],
                }
            )

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        result, code = b"", 0
        if self.fail_once == argv[:3]:
            self.fail_once = None
            return subprocess.CompletedProcess(argv, 19, SECRET.encode(), SECRET.encode())
        if argv[0] == "busctl":
            assert argv[:4] == ["busctl", "--system", "--json=short", "--no-pager"]
            assert argv[5] == "org.freedesktop.systemd1"
            if argv[4] == "call":
                assert argv[6:10] == [
                    "/org/freedesktop/systemd1",
                    "org.freedesktop.systemd1.Manager",
                    "GetUnit",
                    "s",
                ]
                assert len(argv) == 11
                unit, stage = argv[10], "GetUnit"
            else:
                assert argv[4] == "get-property" and len(argv) == 9
                assert argv[7:] == ["org.freedesktop.systemd1.Service", "LoadCredential"]
                unit = next(unit for unit, path in UNIT_OBJECTS.items() if path == argv[6])
                stage = "LoadCredential"
            result = self.bus_replies[unit, stage]
            if isinstance(result, Exception):
                raise result
            if isinstance(result, int):
                code, result = result, SECRET.encode()
        elif argv[0] == "git" and "rev-parse" in argv:
            result = self.git_release.encode()
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
                    result = f"AC_RELEASE_ID={self.api_release}".encode()
                elif unit == tool.refresh.WORKER_UNIT:
                    digest = tool.manifest_pin(self.loaded["worker_dropin"])
                    result = f"{tool.WORKER_KEY}={digest}".encode()
            elif prop == "LoadCredential":
                result = SYSTEMD_255_SENTINEL
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
            assert argv[argv.index("--validate-credentials") + 1] == self.pins.release
            assert not any("/opt/ac-dev-approval-reseal" in arg for arg in argv)
            manifest = json.loads(argv[argv.index(tool.CODE_BOOTSTRAP) + 1])
            for name in (tool.CODE_NAME, *tool.HELPER_SHA256):
                source = Path(tool.__file__).with_name(name)
                assert f"LoadCredential={name}:{source}" in argv
                assert manifest[name] == tool.sha(source.read_bytes())
            assert all(prop in argv for prop in tool.refresh.SANDBOX_PROPERTIES)
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
        "allowances": [
            {
                "id": "50000000-0000-4000-8000-000000000001",
                "tenant_id": "10000000-0000-4000-8000-000000000001",
                "person_id": "40000000-0000-4000-8000-000000000001",
                "seconds": 180,
                "authorization_ref": "ref:allowance/fictional",
                "granted_by": "30000000-0000-4000-8000-000000000001",
                "reason": "Approved internal testing allowance",
                "max_recordings": 1,
                "max_source_bytes": 1000,
                "max_stored_source_bytes": 1000,
            }
        ],
        "stages": [
            {
                "id": "60000000-0000-4000-8000-000000000001",
                "tenant_id": "10000000-0000-4000-8000-000000000001",
                "person_id": "40000000-0000-4000-8000-000000000001",
                "source_sha256": "a" * 64,
                "configuration_sha256": "b" * 64,
                "stage": "C2",
                "provider_id": "gemini",
                "model_id": "fictional-model",
                "recipe_revision": "fictional-v1",
                "permission_ref": "ref:permission/fictional",
                "retention_ref": "ref:retention/fictional",
                "professional_gate_ref": "ref:professional/fictional",
                "pricing_ref": "ref:pricing/fictional",
                "provider_terms_ref": "ref:terms/fictional",
                "privacy_ref": "ref:privacy/fictional",
                "credential_ref": "ref:credential/fictional",
                "free_allowance_ref": "ref:allowance/fictional",
                "no_paid_overage_ref": "ref:billing/no-overage",
                "privacy_revision": "fictional-v1",
                "privacy_notice": "Fictional runtime test only.",
                "expires_at_epoch": 4102444800,
                "max_requests": 1,
                "zero_cost_basis": "verified_free_allowance",
                "price_evidence_sha256": "c" * 64,
                "max_cost_paise": 0,
                "max_source_duration_ms": 180000,
                "max_input_bytes": 1000,
                "max_completion_tokens": 0,
            }
        ],
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
    pins = tool.Pins(tool.sha(before), tool.sha(candidate), LATER_RELEASE)
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
    template = {**service, "release_id": TEMPLATE_RELEASE}
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
    scripts = tmp_path / "released/scripts"
    for name in (tool.CODE_NAME, *tool.HELPER_SHA256):
        put(scripts / name, SCRIPT.with_name(name).read_bytes(), 0o750)
    scripts.parent.chmod(0o700)
    scripts.chmod(0o750)
    monkeypatch.setattr(tool, "__file__", str(scripts / tool.CODE_NAME))
    host = Host(paths, pins)
    monkeypatch.setattr(tool.refresh, "runtime_identity", lambda: None)
    monkeypatch.setattr(tool, "process_environment", host.process_environment)
    monkeypatch.setattr(tool, "adopted_credentials", host.adopted)
    monkeypatch.setattr(tool.refresh, "HEALTH_WAIT_SECONDS", 0)
    return paths, pins, host


def run(fixture, apply=False):
    paths, pins, host = fixture
    return tool.reseal(paths, pins=pins, runner=host, uid=0, apply=apply)


@pytest.mark.parametrize("unit", tool.UNITS)
def test_captured_systemd_255_typed_mapping_without_protected_reads(fixture, unit):
    _, _, host = fixture
    host.bus_replies[unit, "LoadCredential"] = tool.encoded(SYSTEMD_255_CREDENTIALS[unit])
    assert tool.Commands(host).credential_sources(unit) == dict(
        SYSTEMD_255_CREDENTIALS[unit]["data"]
    )
    assert len(host.calls) == 2 and all(call[0] == "busctl" for call in host.calls)


@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("apply", [False, True])
def test_systemd_255_sentinel_does_not_block_typed_preflight(fixture, rollback, apply):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    host.calls.clear()
    result = (
        tool.rollback(paths, run_id, runner=host, pins=pins, uid=0, apply=apply)
        if rollback
        else run(fixture, apply=apply)
    )
    assert result["apply"] is apply
    for unit in tool.UNITS:
        assert any(call[0] == "busctl" and call[-1] == unit for call in host.calls)
        assert any(
            call[0] == "busctl" and call[6] == UNIT_OBJECTS[unit] and call[-1] == "LoadCredential"
            for call in host.calls
        )
    assert not any(
        call[:2] == ["systemctl", "show"] and call[3] == "--property=LoadCredential"
        for call in host.calls
    )


@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("unit", tool.UNITS)
@pytest.mark.parametrize(
    "bad",
    [
        "missing-approval",
        "wrong-approval",
        "duplicate",
        "wrong-signature",
        "wrong-envelope",
        "extra-envelope-key",
        "duplicate-json-key",
        "missing-data",
        "mapping-instead-of-array",
        "wrong-entry-type",
        "wrong-entry-length",
        "non-string-id",
        "non-string-path",
        "invalid-id",
        "relative-path",
        "path-traversal",
        "nul-path",
        "sentinel",
        "invalid-json",
        "invalid-utf8",
        "non-finite-json",
    ],
)
def test_typed_credential_refusal_has_zero_writes_or_service_changes(
    fixture, monkeypatch, rollback, apply, unit, bad
):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    value = tool.decoded(host.bus_replies[unit, "LoadCredential"])
    approval = next(entry for entry in value["data"] if entry[0] == "approval.json")
    if bad == "missing-approval":
        value["data"].remove(approval)
    elif bad == "wrong-approval":
        approval[1] = "/fictional/wrong/approval.json"
    elif bad == "duplicate":
        value["data"].append(approval.copy())
    elif bad == "wrong-signature":
        value["type"] = "a{ss}"
    elif bad == "wrong-envelope":
        value = value["data"]
    elif bad == "extra-envelope-key":
        value["extra"] = SECRET
    elif bad == "missing-data":
        del value["data"]
    elif bad == "mapping-instead-of-array":
        value["data"] = dict(value["data"])
    elif bad == "wrong-entry-type":
        value["data"] = [dict(value["data"])]
    elif bad == "wrong-entry-length":
        approval.append("unexpected")
    elif bad == "non-string-id":
        approval[0] = 123
    elif bad == "non-string-path":
        approval[1] = None
    elif bad == "invalid-id":
        approval[0] = "../approval.json"
    elif bad == "relative-path":
        approval[1] = "approval.json"
    elif bad == "path-traversal":
        approval[1] = str(paths.development / "../development/approval.json")
    elif bad == "nul-path":
        approval[1] += "\0"
    raw = tool.encoded(value)
    if bad == "duplicate-json-key":
        raw = raw.replace(b'{"data":', b'{"type":"a(ss)","data":', 1)
    elif bad == "sentinel":
        raw = SYSTEMD_255_SENTINEL
    elif bad == "invalid-json":
        raw = (SECRET + EMAIL).encode()
    elif bad == "invalid-utf8":
        raw = b"\xff"
    elif bad == "non-finite-json":
        raw = b'{"type":"a(ss)","data":[NaN]}'
    host.bus_replies[unit, "LoadCredential"] = raw
    assert_credential_preflight_refusal(fixture, monkeypatch, run_id, apply)


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("bad", ["missing-service", "wrong-service"])
def test_worker_service_source_is_required(fixture, monkeypatch, rollback, apply, bad):
    paths, _, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    value = tool.decoded(host.bus_replies[tool.refresh.WORKER_UNIT, "LoadCredential"])
    service = next(entry for entry in value["data"] if entry[0] == "service.json")
    if bad == "missing-service":
        value["data"].remove(service)
    else:
        service[1] = str(paths.development / "service.operator-template.json")
    host.bus_replies[tool.refresh.WORKER_UNIT, "LoadCredential"] = tool.encoded(value)
    assert_credential_preflight_refusal(fixture, monkeypatch, run_id, apply)


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("unit", tool.UNITS)
@pytest.mark.parametrize("stage", ["GetUnit", "LoadCredential"])
@pytest.mark.parametrize("failure", ["command-failed", "unavailable"])
def test_dbus_failures_refuse_without_output_leaks_or_mutations(
    fixture, monkeypatch, rollback, apply, unit, stage, failure
):
    _, _, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    host.bus_replies[unit, stage] = 19 if failure == "command-failed" else OSError(SECRET)
    code = "command_failed" if failure == "command-failed" else "command_unavailable"
    assert_credential_preflight_refusal(fixture, monkeypatch, run_id, apply, code)


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize(
    "response",
    [
        {"type": "s", "data": [UNIT_OBJECTS[tool.refresh.API_UNIT]]},
        {"type": "o", "data": UNIT_OBJECTS[tool.refresh.API_UNIT]},
        {"type": "o", "data": []},
        {"type": "o", "data": [None]},
        {"type": "o", "data": ["/org/freedesktop/systemd1"]},
        {"type": "o", "data": ["/org/freedesktop/systemd1/unit/invalid/path"]},
        {"type": "o", "data": [UNIT_OBJECTS[tool.refresh.API_UNIT]] * 2},
    ],
)
def test_invalid_getunit_reply_refuses_before_property_read(
    fixture, monkeypatch, rollback, apply, response
):
    _, _, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    host.bus_replies[tool.refresh.API_UNIT, "GetUnit"] = tool.encoded(response)
    assert_credential_preflight_refusal(fixture, monkeypatch, run_id, apply)
    assert not any(call[0] == "busctl" and call[4] == "get-property" for call in host.calls)


def assert_credential_preflight_refusal(
    fixture, monkeypatch, run_id, apply, code="unit_credential_mismatch"
):
    paths, pins, host = fixture
    before, states, loaded = tree(paths.trusted_root), host.states.copy(), host.loaded.copy()
    host.calls.clear()

    def forbidden_write(*_args):
        pytest.fail("credential preflight must refuse before every write, including audit files")

    monkeypatch.setattr(tool, "write", forbidden_write)
    with pytest.raises(tool.ResealError, match=code) as error:
        if run_id:
            tool.rollback(paths, run_id, runner=host, pins=pins, uid=0, apply=apply)
        else:
            run(fixture, apply=apply)
    assert tree(paths.trusted_root) == before and host.states == states and host.loaded == loaded
    assert not any(
        call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed", "daemon-reload")
        for call in host.calls
    )
    assert not any(call[0] == "systemd-run" for call in host.calls)
    assert SECRET not in json.dumps(error.value.report) and EMAIL not in json.dumps(
        error.value.report
    )


def test_typed_sources_still_require_independent_adopted_credential_verification(
    fixture, monkeypatch
):
    paths, _, host = fixture
    before = tree(paths.trusted_root)

    def refuse_adopted(*_args):
        raise tool.ResealError("adopted_credential_mismatch")

    monkeypatch.setattr(tool, "adopted_credentials", refuse_adopted)
    with pytest.raises(tool.ResealError, match="adopted_credential_mismatch"):
        run(fixture, apply=True)
    assert tree(paths.trusted_root) == before
    assert not any(
        call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed", "daemon-reload")
        for call in host.calls
    )


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
    assert report["release"] == LATER_RELEASE
    plan = tool.decoded(paths.history.joinpath(report["run_id"], "plan.json").read_bytes())
    assert plan["release"] == LATER_RELEASE
    after, after_guards = tool.snapshot(paths)
    assert after_guards == guards
    assert tool.sha(after["approval"].raw) == pins.after
    assert tool.assignments(after["api_env"].raw)[tool.APPROVAL_KEY] == pins.after
    for name in ("template", "service"):
        old, new = tool.decoded(before[name].raw), tool.decoded(after[name].raw)
        new["sales_xray_approval_sha256"] = pins.before
        assert old == new
    assert tool.decoded(after["template"].raw)["release_id"] == TEMPLATE_RELEASE
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
    assert json.loads(events[0].read_bytes())["release"] == LATER_RELEASE
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
    assert result["release"] == LATER_RELEASE
    validation = [call for call in host.calls if call[0] == "systemd-run"][-1]
    directory = paths.history / report["run_id"]
    assert f"LoadCredential=current.json:{directory / 'approval.before'}" in validation
    assert f"LoadCredential=service.json:{directory / 'service.before'}" in validation
    assert f"LoadCredential=template.json:{directory / 'template.before'}" in validation
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


@pytest.mark.parametrize("rollback", [False, True])
@pytest.mark.parametrize("source", ["supplied", "marker", "git", "api", "service", "readiness"])
def test_release_disagreement_refuses_without_writes_or_service_changes(fixture, source, rollback):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if rollback else None
    if source == "supplied":
        pins = replace(pins, release=tool.SERVING_RELEASE)
    elif source == "marker":
        put(paths.backend / ".ac-release-id", (tool.SERVING_RELEASE + "\n").encode(), 0o644)
    elif source in ("git", "api"):
        setattr(host, source + "_release", tool.SERVING_RELEASE)
    elif source == "service":
        path = paths.targets()["service"]
        path.write_bytes(
            path.read_bytes().replace(LATER_RELEASE.encode(), tool.SERVING_RELEASE.encode())
        )
    else:
        host.health_release = tool.SERVING_RELEASE
    before = tree(paths.trusted_root)
    states = host.states.copy()
    host.calls.clear()
    with pytest.raises(tool.ResealError):
        if rollback:
            tool.rollback(paths, run_id, runner=host, pins=pins, uid=0, apply=True)
        else:
            tool.reseal(paths, runner=host, pins=pins, uid=0, apply=True)
    assert tree(paths.trusted_root) == before and host.states == states
    assert not any(
        call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed", "daemon-reload")
        for call in host.calls
    )


@pytest.mark.parametrize("apply", [False, True])
def test_rollback_runtime_contract_failure_refuses_without_writes(fixture, apply):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"]
    before = tree(paths.trusted_root)
    states = host.states.copy()
    host.fail_once = ["systemd-run", "--wait", "--collect"]
    with pytest.raises(tool.ResealError, match="command_failed"):
        tool.rollback(paths, run_id, runner=host, pins=pins, uid=0, apply=apply)
    assert tree(paths.trusted_root) == before and host.states == states


@pytest.mark.parametrize("field", ["approval_before_sha256", "approval_after_sha256"])
def test_rollback_plan_cannot_change_approval_authorization(fixture, field):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"]
    path = paths.history / run_id / "plan.json"
    plan = tool.decoded(path.read_bytes())
    plan[field] = "c" * 64
    path.write_bytes(tool.encoded(plan))
    before = tree(paths.trusted_root)
    host.calls.clear()
    with pytest.raises(tool.ResealError, match="rollback_plan_invalid"):
        tool.rollback(paths, run_id, runner=host, pins=pins, uid=0, apply=True)
    assert tree(paths.trusted_root) == before and host.calls == []


@pytest.mark.parametrize("release", [None, LATER_RELEASE])
@pytest.mark.parametrize(
    "mode",
    [[], ["--apply"], ["--rollback", "recorded-run"], ["--rollback", "recorded-run", "--apply"]],
)
def test_cli_routes_same_release_with_fixed_approval_pins(monkeypatch, capsys, release, mode):
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(tool, "reseal", capture)
    monkeypatch.setattr(tool, "rollback", capture)
    arguments = mode + (["--serving-release-id", release] if release else [])
    assert tool.main(arguments) == 0
    assert calls == [
        {"apply": "--apply" in mode, "pins": tool.Pins(release=release or tool.SERVING_RELEASE)}
    ]
    assert calls[0]["pins"].before == tool.APPROVAL_BEFORE
    assert calls[0]["pins"].after == tool.APPROVAL_AFTER
    capsys.readouterr()


@pytest.mark.parametrize(
    "release", ["", "main", "a" * 39, "a" * 41, "g" * 40, "/moving/current", LATER_RELEASE + "\n"]
)
@pytest.mark.parametrize("rollback", [False, True])
def test_malformed_release_rejected_before_protected_reads(monkeypatch, capsys, release, rollback):
    def unexpected_paths():
        pytest.fail("malformed input must fail before paths or protected operations")

    monkeypatch.setattr(tool, "Paths", unexpected_paths)
    arguments = ["--serving-release-id", release, "--apply"]
    if rollback:
        arguments += ["--rollback", "recorded-run"]
    assert tool.main(arguments) == 2
    output = capsys.readouterr()
    assert json.loads(output.err) == {"ok": False, "code": "serving_release_id_invalid"}


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


@pytest.fixture
def historical_runtime(fixture, monkeypatch):
    """Real hosted validators; only systemd delivery/host operations are simulated."""
    paths, pins, _ = fixture
    original = paths.targets()["approval"].read_bytes()
    before = (json.dumps(tool.decoded(original), sort_keys=True, indent=2) + "\n").encode()
    pins = replace(pins, before=tool.sha(before))
    put(paths.targets()["approval"], before)
    for name in ("api_env", "service", "template"):
        path = paths.targets()[name]
        put(path, path.read_bytes().replace(tool.sha(original).encode(), pins.before.encode()))
    put(
        paths.worker_dropin,
        f"[Service]\nEnvironment={tool.WORKER_KEY}=".encode()
        + tool.sha(paths.targets()["service"].read_bytes()).encode()
        + b"\n",
        0o644,
    )
    # Fictional digest substitutes for the fixed historical pin only in tests.
    monkeypatch.setattr(tool, "APPROVAL_BEFORE", pins.before)
    import ac_platform.conversation_intelligence.service_config as config

    original_read = config.read_private_file

    class ContractHost(Host):
        validated = []

        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if argv[0] == "systemd-run" and result.returncode == 0:
                mapping = {
                    prop.split("=", 1)[1].split(":", 1)[0]: Path(prop.split(":", 1)[1])
                    for prop in argv
                    if prop.startswith("LoadCredential=")
                }
                mapping[".ac-release-id"] = paths.backend / ".ac-release-id"
                with monkeypatch.context() as runtime:
                    runtime.setattr(os, "geteuid", lambda: 10001)
                    runtime.setattr(sys, "dont_write_bytecode", True)
                    runtime.setattr(
                        config,
                        "read_private_file",
                        lambda path, **kw: original_read(mapping[path.name], **kw),
                    )
                    arguments = argv[argv.index("--validate-credentials") + 1 :]
                    tool.validate_credentials(arguments)
                self.validated.append(tool.sha(mapping["current.json"].read_bytes()))
            return result

    host = ContractHost(paths, pins)
    monkeypatch.setattr(tool, "process_environment", host.process_environment)
    monkeypatch.setattr(tool, "adopted_credentials", host.adopted)
    return paths, pins, host


def test_formatted_baseline_full_validation_lifecycle_restores_exact_bytes(historical_runtime):
    paths, pins, host = historical_runtime
    original, guards = tool.snapshot(paths)
    raw = original["approval"].raw
    assert raw == (json.dumps(tool.decoded(raw), sort_keys=True, indent=2) + "\n").encode()
    assert load_hosted_approval_bundle(raw).to_json() != raw
    candidate = paths.candidate.read_bytes()
    assert load_hosted_approval_bundle(candidate).to_json() == candidate
    assert not candidate.endswith(b"\n")
    initial = tree(paths.trusted_root)
    history_before = paths.history.lstat() if paths.history.exists() else None
    run(historical_runtime)
    assert tree(paths.trusted_root) == initial
    assert (paths.history.lstat() if paths.history.exists() else None) == history_before
    report = run(historical_runtime, apply=True)
    assert paths.targets()["approval"].read_bytes() == candidate
    directory = paths.history / report["run_id"]
    for path in (paths.history, directory):
        info = path.lstat()
        assert (info.st_uid, stat.S_IMODE(info.st_mode)) == (paths.owner_uid, 0o700)
        assert not os.listxattr(path)
    for name, value in original.items():
        backup = directory / (name + ".before")
        assert backup.read_bytes() == value.raw
        assert (backup.stat().st_uid, stat.S_IMODE(backup.stat().st_mode)) == (
            paths.owner_uid,
            0o600,
        )
    plan = tool.decoded((directory / "plan.json").read_bytes())
    assert plan["before"] == {name: value.metadata() for name, value in original.items()}
    assert all(value["mode"] == 0o700 for value in plan["audit_directories"].values())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())
    assert run(historical_runtime, apply=True)["noop"]
    adopted = tree(paths.trusted_root)
    tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0)
    assert tree(paths.trusted_root) == adopted
    tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)
    assert tool.snapshot(paths) == (original, guards)
    assert host.validated == [pins.before] * 3 + [pins.after] * 2 + [pins.before] * 3
    assert paths.targets()["approval"].read_bytes() == raw
    history = tree(paths.history)
    assert tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=True)["noop"]
    assert tree(paths.history) == history


def setgid_history(paths, state):
    paths.history.parent.parent.chmod(0o2750)
    paths.history.parent.chmod(0o2700)
    if state != "fresh":
        paths.history.mkdir(mode=0o700)
        assert stat.S_IMODE(paths.history.stat().st_mode) == 0o2700
        if state == "audited":
            paths.history.chmod(0o700)
            put(paths.history / "prior-run/plan.json", b'{"fictional":"prior plan"}\n')
            put(paths.history / "prior-run/applied-prior.json", b'{"fictional":"prior event"}\n')
            put(paths.history / "prior-run/approval.before", b"fictional exact prior bytes\n")
    return tree(paths.history) if paths.history.exists() else {}


@pytest.mark.parametrize("state", ["fresh", "residue", "audited"])
def test_setgid_history_full_validation_lifecycle(historical_runtime, state):
    paths, _, _ = historical_runtime
    prior = setgid_history(paths, state)
    ancestors_before = {path: path.stat() for path in paths.history.parents}
    test_formatted_baseline_full_validation_lifecycle_restores_exact_bytes(historical_runtime)
    assert all(tree(paths.history)[name] == value for name, value in prior.items())
    for path, info in ancestors_before.items():
        current = path.stat()
        assert (current.st_mode, current.st_uid, current.st_gid) == (
            info.st_mode,
            info.st_uid,
            info.st_gid,
        )


@pytest.mark.parametrize("parent_mode", [0o2700, 0o2750])
def test_private_run_directory_clears_actual_setgid_inheritance(fixture, parent_mode):
    paths, _, _ = fixture
    paths.history.mkdir(mode=0o700)
    paths.history.chmod(parent_mode)
    directory = paths.history / "fictional-run"
    tool.private_directory(directory, paths, create=True)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert directory.stat().st_gid == paths.history.stat().st_gid
    assert stat.S_IMODE(paths.history.stat().st_mode) == parent_mode


@pytest.mark.parametrize(
    "bad",
    [
        "symlink",
        "dangling",
        "file",
        "owner",
        "group",
        "other",
        "sticky",
        "setuid",
        "nonempty-file",
        "nonempty-directory",
        "xattr",
        "parent-mode",
        "gid",
    ],
)
def test_untrusted_history_refuses_apply_before_backups_or_service_changes(
    fixture, monkeypatch, bad
):
    paths, _, host = fixture
    setgid_history(paths, "residue")
    path = paths.history
    if bad in ("symlink", "dangling", "file"):
        path.rmdir()
        if bad == "file":
            put(path, b"fictional not a directory")
        else:
            target = path.with_name("fictional-target")
            if bad == "symlink":
                target.mkdir(mode=0o700)
            path.symlink_to(target)
    elif bad in ("owner", "gid"):
        # Root's bounded proof can test actual foreign ownership on fictional inputs.
        if os.geteuid() == 0:
            os.chown(
                path,
                paths.owner_uid + 1 if bad == "owner" else -1,
                path.stat().st_gid + 1 if bad == "gid" else -1,
            )
            path.chmod(0o2700)
        inode = path.stat().st_ino
        original_fstat = os.fstat

        def wrong_metadata(fd):
            info = original_fstat(fd)
            if info.st_ino == inode and os.geteuid() != 0:
                fields = list(info)
                fields[4 if bad == "owner" else 5] += 1
                return os.stat_result(fields)
            return info

        monkeypatch.setattr(os, "fstat", wrong_metadata)
    elif bad == "nonempty-file":
        put(path / "prior-event.json", b"fictional existing audit")
    elif bad == "nonempty-directory":
        (path / "prior-run").mkdir(mode=0o700)
    elif bad == "xattr":
        os.setxattr(path, "user.fictional-audit", b"fictional")
    elif bad == "parent-mode":
        path.parent.chmod(0o2750)
    else:
        path.chmod({"group": 0o2710, "other": 0o2701, "sticky": 0o3700, "setuid": 0o6700}[bad])
    before = tree(paths.trusted_root)
    metadata = path.lstat()
    with pytest.raises(tool.ResealError, match="history_untrusted"):
        run(fixture, apply=True)
    assert path.lstat() == metadata
    assert tree(paths.trusted_root) == before
    assert not any(
        call[0] == "systemctl" and call[1] in ("stop", "restart", "reset-failed", "daemon-reload")
        for call in host.calls
    )


@pytest.mark.parametrize("target", ["history", "run"])
@pytest.mark.parametrize("apply", [False, True])
def test_rollback_refuses_untrusted_audit_directory_without_normalization(fixture, target, apply):
    paths, pins, host = fixture
    report = run(fixture, apply=True)
    directory = paths.history if target == "history" else paths.history / report["run_id"]
    directory.chmod(0o2700)
    before = tree(paths.trusted_root)
    host.calls.clear()
    with pytest.raises(tool.ResealError, match="history_untrusted"):
        tool.rollback(paths, report["run_id"], runner=host, pins=pins, uid=0, apply=apply)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o2700
    assert tree(paths.trusted_root) == before
    assert not host.calls


@pytest.mark.parametrize(
    "bad", ["collision", "group", "xattr", "chmod-failed", "chmod-ineffective"]
)
def test_private_run_directory_refuses_bad_creation_without_touching_history(
    fixture, monkeypatch, bad
):
    paths, _, _ = fixture
    paths.history.mkdir(mode=0o700)
    paths.history.chmod(0o2700)
    directory = paths.history / "fictional-run"
    put(paths.history / "prior-event.json", b"fictional prior audit\n")
    if bad == "collision":
        directory.mkdir(mode=0o700)
    original_mkdir = Path.mkdir

    def bad_creation(path, *args, **kwargs):
        original_mkdir(path, *args, **kwargs)
        if path == directory:
            if bad == "group":
                path.chmod(0o2710)
            elif bad == "xattr":
                os.setxattr(path, "user.fictional-audit", b"fictional")

    monkeypatch.setattr(Path, "mkdir", bad_creation)
    if bad.startswith("chmod-"):

        def bad_chmod(fd, mode):
            assert mode == 0o700
            if bad == "chmod-failed":
                raise OSError("fictional failure")

        monkeypatch.setattr(os, "fchmod", bad_chmod)
    before = (paths.history / "prior-event.json").read_bytes()
    with pytest.raises(tool.ResealError, match="history_untrusted"):
        tool.private_directory(directory, paths, create=True)
    assert (paths.history / "prior-event.json").read_bytes() == before
    assert stat.S_IMODE(paths.history.stat().st_mode) == 0o2700


def test_fictional_proof_harness_runs_reviewed_bootstrap_and_full_validator(
    historical_runtime, monkeypatch
):
    paths, pins, _ = historical_runtime
    import ac_platform.conversation_intelligence.service_config as config

    credentials = paths.trusted_root / "proof-credentials"
    for name in (tool.CODE_NAME, *tool.HELPER_SHA256):
        put(credentials / name, Path(tool.__file__).with_name(name).read_bytes(), 0o400)
    mapping = {
        "current.json": paths.targets()["approval"],
        "candidate.json": paths.candidate,
        "service.json": paths.targets()["service"],
        "template.json": paths.targets()["template"],
        ".ac-release-id": paths.backend / ".ac-release-id",
        **{name: credentials / name for name in (tool.CODE_NAME, *tool.HELPER_SHA256)},
    }
    original_read, original_run = config.read_private_file, runpy.run_path
    monkeypatch.setattr(
        config, "read_private_file", lambda path, **kw: original_read(mapping[path.name], **kw)
    )
    monkeypatch.setattr(
        runpy, "run_path", lambda path, **kw: original_run(mapping[Path(path).name], **kw)
    )
    monkeypatch.setattr(os, "geteuid", lambda: 10001)
    monkeypatch.setattr(os, "getegid", lambda: 10001)
    monkeypatch.setattr(os, "getgroups", lambda: [10001])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", f"/run/credentials/{tool.VALIDATION_UNIT}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "-c",
            tool.CODE_BOOTSTRAP,
            tool.encoded({tool.CODE_NAME: tool.CODE_SHA256, **tool.HELPER_SHA256}).decode(),
            "--validate-credentials",
            pins.release,
            pins.before,
            pins.after,
            tool.sha(mapping["service.json"].read_bytes()),
            tool.sha(mapping["template.json"].read_bytes()),
        ],
    )
    before = tree(paths.trusted_root)
    exec(FICTIONAL_CONTRACT_BOOTSTRAP, {})  # noqa: S102 - exact Root proof harness
    assert tree(paths.trusted_root) == before


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "bad",
    [
        "wrong-before",
        "unapproved-format",
        "wrong-candidate",
        "noncanonical-candidate",
        "policy",
        "allowance",
        "duplicate-baseline",
        "duplicate-candidate",
        "inactive-policy",
        "expired-provider",
        "synthetic-provider",
        "unbound-provider",
        "malformed-service-pin",
        "wrong-service-pin",
        "malformed-template-pin",
    ],
)
def test_full_validation_refuses_before_durable_writes(historical_runtime, monkeypatch, bad, apply):
    paths, pins, host = historical_runtime
    approval = paths.targets()["approval"]
    candidate = paths.candidate
    raw = candidate.read_bytes()
    value = tool.decoded(raw)
    if bad == "wrong-before":
        put(approval, approval.read_bytes() + b" ")
    elif bad == "unapproved-format":
        monkeypatch.setattr(tool, "APPROVAL_BEFORE", "0" * 64)
    elif bad in ("wrong-candidate", "noncanonical-candidate"):
        raw += b"\n"
    elif bad in ("policy", "allowance"):
        if bad == "policy":
            value["retention_days"] -= 1
        else:
            value["allowances"][0]["seconds"] += 1
        raw = load_hosted_approval_bundle(value).to_json()
    elif bad == "duplicate-candidate":
        raw = b'{"environment":"development",' + raw[1:]
    elif bad.startswith("duplicate-baseline") or bad in (
        "inactive-policy",
        "expired-provider",
        "synthetic-provider",
        "unbound-provider",
    ):
        # Re-pin fictional inputs to isolate strict parser/policy/service checks.
        baseline = tool.decoded(approval.read_bytes())
        for item in (baseline, value):
            if bad == "inactive-policy":
                item["issued_at_epoch"] = 4000000000
            elif bad == "expired-provider":
                item["stages"][0]["expires_at_epoch"] = 2
            elif bad == "synthetic-provider":
                item["stages"][0]["zero_cost_basis"] = "synthetic"
            elif bad == "unbound-provider":
                item["stages"][0]["credential_ref"] = "ref:credential/unconfigured"
        before = (json.dumps(baseline, sort_keys=True, indent=2) + "\n").encode()
        if bad == "duplicate-baseline":
            before = b'{"environment":"development",' + before[1:]
        previous = pins.before
        pins = replace(pins, before=tool.sha(before))
        monkeypatch.setattr(tool, "APPROVAL_BEFORE", pins.before)
        put(approval, before)
        for name in ("api_env", "service", "template"):
            path = paths.targets()[name]
            put(path, path.read_bytes().replace(previous.encode(), pins.before.encode()))
        raw = tool.encoded(value)
    elif "service-pin" in bad or bad == "malformed-template-pin":
        path = paths.targets()["template" if "template" in bad else "service"]
        put(
            path,
            path.read_bytes().replace(
                pins.before.encode(), b"malformed" if bad.startswith("malformed") else b"0" * 64
            ),
        )
    put(candidate, raw)
    if bad != "wrong-candidate":
        pins = replace(pins, after=tool.sha(raw))
    service = paths.targets()["service"].read_bytes()
    put(
        paths.worker_dropin,
        f"[Service]\nEnvironment={tool.WORKER_KEY}={tool.sha(service)}\n".encode(),
        0o644,
    )
    # Let identical malformed service/template reach the runtime service loader.
    if "service-pin" in bad:
        template = tool.decoded(service)
        template["release_id"] = TEMPLATE_RELEASE
        put(paths.targets()["template"], tool.encoded(template))
    host.pins = pins
    host.loaded = {name: path.read_bytes() for name, path in paths.targets().items()}
    before_tree, states = tree(paths.trusted_root), host.states.copy()

    def refuse_write(*_):
        pytest.fail("invalid contract must refuse before every durable write")

    monkeypatch.setattr(tool, "write", refuse_write)
    with pytest.raises(tool.ResealError):
        tool.reseal(paths, pins=pins, runner=host, uid=0, apply=apply)
    assert tree(paths.trusted_root) == before_tree and host.states == states
    assert not paths.history.exists()
    assert not any(
        call[:2]
        in (["systemctl", "stop"], ["systemctl", "restart"], ["systemctl", "daemon-reload"])
        for call in host.calls
    )


def test_runtime_credentials_use_real_serving_contract_and_expiry(fixture, monkeypatch):
    paths, pins, _ = fixture
    import ac_platform.conversation_intelligence.service_config as config

    original_read = config.read_private_file
    mapping = {
        "current.json": paths.development / "approval.json",
        "candidate.json": paths.candidate,
        "service.json": paths.development / "service.json",
        "template.json": paths.development / "service.operator-template.json",
        ".ac-release-id": paths.backend / ".ac-release-id",
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
    marker = mapping[".ac-release-id"]
    put(marker, (tool.SERVING_RELEASE + "\n").encode(), 0o644)
    with pytest.raises(ValueError, match="worker_release_mismatch"):
        tool.validate_credentials(arguments)
    put(marker, (pins.release + "\n").encode(), 0o644)
    value = tool.decoded(paths.candidate.read_bytes())
    value["expires_at_epoch"] = 2
    value["stages"][0]["expires_at_epoch"] = 2
    raw = load_hosted_approval_bundle(value).to_json()
    put(paths.candidate, raw)
    # Bypass the append comparison to isolate the real current-contract expiry gate.
    monkeypatch.setattr(tool, "permitted_diff", lambda *_: None)
    arguments[2] = tool.sha(raw)
    with pytest.raises(Exception, match="replacement approval is not current"):
        tool.validate_credentials(arguments)


@pytest.mark.parametrize("mode", ["dry-run", "apply", "rollback-dry-run", "rollback-apply"])
@pytest.mark.parametrize("name", [tool.CODE_NAME, *tool.HELPER_SHA256])
@pytest.mark.parametrize("bad", ["missing", "tampered", "symlink", "hardlink", "writable"])
def test_untrusted_code_refuses_before_backups_or_service_changes(
    fixture, monkeypatch, mode, name, bad
):
    paths, pins, host = fixture
    run_id = run(fixture, apply=True)["run_id"] if mode.startswith("rollback") else None
    source = Path(tool.__file__).with_name(name)
    if bad == "missing":
        source.unlink()
    elif bad == "tampered":
        source.write_bytes((SECRET + EMAIL).encode())
    elif bad == "symlink":
        other = source.with_suffix(".other")
        source.rename(other)
        source.symlink_to(other)
    elif bad == "hardlink":
        os.link(source, source.with_suffix(".other"))
    else:
        source.chmod(0o770)
    before = tree(paths.trusted_root)
    states = host.states.copy()
    host.calls.clear()

    def refuse_write(*_):
        pytest.fail("untrusted code must refuse before every durable write")

    monkeypatch.setattr(tool, "write", refuse_write)
    with pytest.raises(tool.ResealError):
        if run_id:
            tool.rollback(
                paths, run_id, runner=host, pins=pins, uid=0, apply=mode.endswith("apply")
            )
        else:
            run(fixture, apply=mode == "apply")
    assert tree(paths.trusted_root) == before and host.states == states
    assert not any(call[0] == "systemd-run" for call in host.calls)
    assert not any(
        call[:2]
        in (["systemctl", "stop"], ["systemctl", "restart"], ["systemctl", "daemon-reload"])
        for call in host.calls
    )


@pytest.mark.parametrize("bad", [None, "missing", "tampered", "public", "symlink", "empty"])
@pytest.mark.parametrize("name", [tool.CODE_NAME, *tool.HELPER_SHA256])
def test_bootstrap_checks_all_private_code_bytes_before_execution(fixture, monkeypatch, bad, name):
    paths, _, _ = fixture
    import ac_platform.conversation_intelligence.service_config as config

    credentials = paths.trusted_root / "runtime-credentials"
    manifest = {}
    for script in (tool.CODE_NAME, *tool.HELPER_SHA256):
        raw = Path(tool.__file__).with_name(script).read_bytes()
        put(credentials / script, raw, 0o400)
        manifest[script] = tool.sha(raw)
    target = credentials / name
    if bad == "missing":
        target.unlink()
    elif bad in ("tampered", "empty"):
        target.chmod(0o600)
        target.write_bytes((SECRET + EMAIL).encode() if bad == "tampered" else b"")
        target.chmod(0o400)
    elif bad == "public":
        target.chmod(0o444)
    elif bad == "symlink":
        other = target.with_suffix(".other")
        target.rename(other)
        target.symlink_to(other)
    original = config.read_private_file
    monkeypatch.setattr(
        config, "read_private_file", lambda path, **kw: original(credentials / path.name, **kw)
    )
    monkeypatch.setattr(os, "geteuid", lambda: 10001)
    monkeypatch.setattr(os, "getegid", lambda: 10001)
    monkeypatch.setattr(os, "getgroups", lambda: [10001])
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", f"/run/credentials/{tool.VALIDATION_UNIT}")
    monkeypatch.setattr(sys, "argv", ["-c", json.dumps(manifest), "--validate-credentials", "pin"])
    executed = []
    monkeypatch.setattr(runpy, "run_path", lambda path, **kw: executed.append((path, kw)))
    if bad:
        with pytest.raises((ValueError, SystemExit)) as error:
            exec(tool.CODE_BOOTSTRAP, {})  # noqa: S102 - exact reviewed bootstrap under test
        assert SECRET not in str(error.value) and EMAIL not in str(error.value)
        assert executed == []
    else:
        exec(tool.CODE_BOOTSTRAP, {})  # noqa: S102 - exact reviewed bootstrap under test
        assert executed == [
            (f"/run/credentials/{tool.VALIDATION_UNIT}/{tool.CODE_NAME}", {"run_name": "__main__"})
        ]
        assert sys.argv[1:] == ["--validate-credentials", "pin"]


def test_code_delivery_rechecks_apply_and_restoration(fixture):
    paths, pins, host = fixture
    report = run(fixture, apply=True)
    assert len([call for call in host.calls if call[0] == "systemd-run"]) == 3
    host.calls.clear()
    tool.rollback(paths, report["run_id"], pins=pins, runner=host, uid=0, apply=True)
    assert len([call for call in host.calls if call[0] == "systemd-run"]) == 2


@pytest.mark.parametrize("bad", ["uid", "gid", "groups", "directory", "manifest"])
def test_bootstrap_refuses_wrong_identity_or_delivery_context(monkeypatch, bad):
    monkeypatch.setattr(os, "geteuid", lambda: 0 if bad == "uid" else 10001)
    monkeypatch.setattr(os, "getegid", lambda: 1002 if bad == "gid" else 10001)
    monkeypatch.setattr(os, "getgroups", lambda: [10001, 1002] if bad == "groups" else [10001])
    monkeypatch.setenv(
        "CREDENTIALS_DIRECTORY",
        "/fictional/wrong-directory"
        if bad == "directory"
        else f"/run/credentials/{tool.VALIDATION_UNIT}",
    )
    monkeypatch.setattr(sys, "argv", ["-c", "{}", "--validate-credentials"])
    with pytest.raises(SystemExit, match="runtime_code_"):
        exec(tool.CODE_BOOTSTRAP, {})  # noqa: S102 - exact reviewed bootstrap under test


@pytest.fixture
def source_denial_identity(monkeypatch):
    sources = [f"/fictional/scripts/{name}" for name in (tool.CODE_NAME, *tool.HELPER_SHA256)]
    monkeypatch.setattr(os, "geteuid", lambda: 10001)
    monkeypatch.setattr(os, "getegid", lambda: 10001)
    monkeypatch.setattr(os, "getgroups", lambda: [10001])
    monkeypatch.setattr(sys, "argv", ["-c", json.dumps(sources)])
    return sources


@pytest.mark.parametrize("denial", [PermissionError, FileNotFoundError])
def test_source_denial_accepts_inaccessible_sources(source_denial_identity, denial):
    attempted = []

    def inaccessible(source, mode):
        assert mode == "rb"
        attempted.append(source)
        raise denial

    exec(UID10001_SOURCE_DENIAL, {"open": inaccessible})  # noqa: S102 - exact proof probe
    assert attempted == source_denial_identity


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("outcome", ["readable", NotADirectoryError, IsADirectoryError, OSError])
def test_source_denial_refuses_readable_sources_and_other_io_errors(
    source_denial_identity, index, outcome
):
    def open_source(source, mode):
        assert mode == "rb"
        if source != source_denial_identity[index]:
            raise PermissionError
        if outcome == "readable":
            return nullcontext()
        raise outcome

    expected = SystemExit if outcome == "readable" else outcome
    with pytest.raises(expected):
        exec(UID10001_SOURCE_DENIAL, {"open": open_source})  # noqa: S102 - exact proof probe


@pytest.mark.parametrize("bad", ["uid", "gid", "groups"])
def test_source_denial_refuses_wrong_identity(source_denial_identity, monkeypatch, bad):
    monkeypatch.setattr(os, "geteuid", lambda: 0 if bad == "uid" else 10001)
    monkeypatch.setattr(os, "getegid", lambda: 1002 if bad == "gid" else 10001)
    monkeypatch.setattr(os, "getgroups", lambda: [10001, 1002] if bad == "groups" else [10001])

    def unexpected_open(*_):
        pytest.fail("wrong identity must refuse before reading any source")

    with pytest.raises(AssertionError):
        exec(UID10001_SOURCE_DENIAL, {"open": unexpected_open})  # noqa: S102 - exact proof probe


@pytest.mark.skipif(
    os.environ.get("AC_RESEAL_RUNTIME_PROOF") != "1",
    reason="Root Operator runs the isolated fictional systemd proof explicitly",
)
def test_root_only_real_uid10001_code_delivery(fixture, monkeypatch):
    """Real systemd, real uid10001, fictional inputs; never call reseal/adoption."""
    assert os.geteuid() == 0
    paths, pins, _ = fixture
    backend = Path(os.environ["AC_RESEAL_PROOF_BACKEND"])
    assert backend.is_absolute() and (backend / ".venv/bin/python").is_file()
    release = (backend / ".ac-release-id").read_text().strip()
    pins = replace(pins, release=release)
    tool.validate_release(pins)
    paths = replace(paths, backend=backend)
    service = paths.targets()["service"]
    value = tool.decoded(service.read_bytes())
    value["release_id"] = release
    put(service, tool.encoded(value))
    scripts = Path(tool.__file__).parent
    reviewed_hashes = {tool.CODE_NAME: tool.CODE_SHA256, **tool.HELPER_SHA256}
    sources = [scripts / name for name in reviewed_hashes]
    group = grp.getgrnam("acops").gr_gid
    assert group != 10001
    for path in [scripts, *sources]:
        os.chown(path, 0, group)
        info = path.lstat()
        assert stat.S_ISDIR(info.st_mode) if path == scripts else stat.S_ISREG(info.st_mode)
        assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (
            0,
            group,
            0o750,
        )
    monkeypatch.setattr(tool.refresh, "runtime_identity", REAL_RUNTIME_IDENTITY)
    before = tree(paths.trusted_root)
    metadata = {path: path.stat() for path in scripts.iterdir()}
    assert set(metadata) == set(sources)
    assert {path.name: tool.sha(path.read_bytes()) for path in sources} == reviewed_hashes
    calls = []

    def isolated_only(argv, **kw):
        assert argv[0] == "systemd-run"
        calls.append(argv)
        return tool.refresh.command(argv, **kw)

    files, _ = tool.snapshot(replace(paths, backend=fixture[0].backend))
    tool.runtime_validation(paths, tool.Commands(isolated_only), pins, files)
    validation = calls[0]
    position = validation.index("--") + 1
    # Bind denial to existing, unchanged host sources before entering private /tmp.
    assert {path: path.lstat() for path in sources} == metadata
    probe = [
        *validation[:position],
        str(backend / ".venv/bin/python"),
        "-c",
        UID10001_SOURCE_DENIAL,
        json.dumps([str(path) for path in sources]),
    ]
    tool.Commands(isolated_only).run("uid10001_source_denial", probe, timeout=90)
    # Real delivery failures and tampered bytes must fail the same bootstrap.
    for bad in ("missing", "tampered"):
        target = paths.trusted_root / (bad + ".py")
        if bad == "tampered":
            put(target, (SECRET + EMAIL).encode())
        negative = validation.copy()
        index = negative.index(f"LoadCredential={tool.CODE_NAME}:{scripts / tool.CODE_NAME}")
        negative[index] = f"LoadCredential={tool.CODE_NAME}:{target}"
        with pytest.raises(tool.ResealError, match="command_failed"):
            tool.Commands(isolated_only).run("uid10001_bad_code", negative, timeout=90)
        if target.exists():
            target.unlink()
    assert tree(paths.trusted_root) == before
    assert {path: path.stat() for path in scripts.iterdir()} == metadata


def test_fictional_contract_runtime_mapping_preserves_sandbox_and_fixture_sources(fixture):
    paths, pins, host = fixture
    files, _ = tool.snapshot(paths)
    tool.runtime_validation(paths, tool.Commands(host), pins, files)
    original = next(argv for argv in host.calls if argv[0] == "systemd-run")
    saved = original.copy()
    backend = Path("/srv/authority-closers/development/backend")
    actual = fictional_contract_command(original, paths.backend, backend)
    assert original == saved
    assert actual[actual.index("--") + 1] == str(backend / ".venv/bin/python")
    assert f"WorkingDirectory={backend}" in actual
    assert f"BindReadOnlyPaths={backend}" in actual
    for prop in (*tool.refresh.SANDBOX_PROPERTIES, "PrivateNetwork=yes", "StandardError=null"):
        assert actual.count(prop) == original.count(prop) == 1
    assert f"BindReadOnlyPaths={paths.backend / '.ac-release-id'}:/app/.ac-release-id" in actual
    assert [arg for arg in actual if arg.startswith("LoadCredential=")] == [
        arg for arg in original if arg.startswith("LoadCredential=")
    ]
    index = actual.index(FICTIONAL_CONTRACT_BOOTSTRAP)
    assert actual[index + 1 :] == original[original.index(tool.CODE_BOOTSTRAP) :]


@pytest.mark.skipif(
    os.environ.get("AC_RESEAL_RUNTIME_PROOF") != "1",
    reason="Root Operator runs the fictional full-contract lifecycle explicitly",
)
@pytest.mark.parametrize("history_state", ["fresh", "residue", "audited"])
def test_root_only_real_uid10001_formatted_contract_lifecycle(
    historical_runtime, monkeypatch, history_state
):
    """Real isolated validation in every phase; all adoption targets/units fictional."""
    assert os.geteuid() == 0
    paths, pins, host = historical_runtime
    group = grp.getgrnam("acops").gr_gid
    for parent in (paths.history.parent.parent, paths.history.parent):
        os.chown(parent, 0, group)
    prior = setgid_history(paths, history_state)
    if paths.history.exists():
        assert paths.history.stat().st_gid == group
    backend = Path(os.environ["AC_RESEAL_PROOF_BACKEND"])
    assert backend.is_absolute() and (backend / ".venv/bin/python").is_file()
    release = (backend / ".ac-release-id").read_text().strip()
    pins = replace(pins, release=release)
    tool.validate_release(pins)
    for name in ("service", "api_env"):
        path = paths.targets()[name]
        put(path, path.read_bytes().replace(LATER_RELEASE.encode(), release.encode()))
    put(paths.backend / ".ac-release-id", (release + "\n").encode(), 0o644)
    put(paths.api_dropin, f"[Service]\nEnvironment=AC_RELEASE_ID={release}\n".encode(), 0o644)
    put(
        paths.worker_dropin,
        f"[Service]\nEnvironment={tool.WORKER_KEY}=".encode()
        + tool.sha(paths.targets()["service"].read_bytes()).encode()
        + b"\n",
        0o644,
    )
    host.pins = pins
    host.git_release = host.api_release = host.health_release = release
    host.loaded = {name: path.read_bytes() for name, path in paths.targets().items()}
    scripts = Path(tool.__file__).parent
    group = grp.getgrnam("acops").gr_gid
    assert group != 10001
    for path in [scripts, *scripts.iterdir()]:
        os.chown(path, 0, group)
        assert stat.S_IMODE(path.stat().st_mode) == 0o750
    metadata = {path: path.stat() for path in scripts.iterdir()}
    monkeypatch.setattr(tool.refresh, "runtime_identity", REAL_RUNTIME_IDENTITY)

    def isolated_contract(argv, **kw):
        result = Host.__call__(host, argv, **kw)
        if argv[0] != "systemd-run":
            return result
        actual = fictional_contract_command(argv, paths.backend, backend)
        result = tool.refresh.command(actual, **kw)
        if result.returncode == 0:
            current = next(
                arg.split(":", 1)[1]
                for arg in argv
                if arg.startswith("LoadCredential=current.json:")
            )
            host.validated.append(tool.sha(Path(current).read_bytes()))
        return result

    # Reuse the same full lifecycle/assertions with actual uid10001 validations.
    class RealHost:
        validated = host.validated

        def __call__(self, argv, **kw):
            return isolated_contract(argv, **kw)

    test_formatted_baseline_full_validation_lifecycle_restores_exact_bytes(
        (paths, pins, RealHost())
    )
    assert paths.history.stat().st_gid == group
    assert all(tree(paths.history)[name] == value for name, value in prior.items())
    assert {path: path.stat() for path in scripts.iterdir()} == metadata
