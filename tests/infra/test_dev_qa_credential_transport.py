"""Dev QA credential broker and browser launcher contracts, with fictional sentinels only.

No sudo, Infisical, browser or network: the broker's root route, the edge and the
deployed receipt are faked. The live sentinel run is recorded in the PR evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


broker = load("dev_qa_credential", "infra/application/scripts/dev-qa-credential.py")
launcher = load("qa_admin_browser", "infra/application/development/qa-admin-browser.py")

MERGE = "1daeb17431a83a1330e9ec5f2362c29d3bb39c30"
REVISION = "ee819d0f5b18779c05b5661b06e76f27cabb2ca1"
SENTINEL = b"ac-qa-sentinel-0123456789abcdef0123456789abcdef"
FICTIONAL = b"Fictional-QA-pass_word!1"


def test_identity_tables_agree_and_are_fictional_dev_references():
    assert broker.IDENTITIES.keys() == launcher.IDENTITIES.keys()
    for name, ref in broker.IDENTITIES.items():
        mirror = launcher.IDENTITIES[name]
        assert (ref.email, ref.folder, ref.secret) == (mirror.email, mirror.folder, mirror.secret)
        assert ref.email.endswith("@example.test")
        assert ref.secret.startswith("AC_DEV_FIXTURE_PASSWORD_")
    assert broker.INFISICAL_ENVIRONMENT == "dev"
    assert launcher.IDENTITIES["billing-staff"].required_merges == (MERGE,)
    assert broker.LAUNCHER.endswith("/qa-admin-browser.py")


# Broker ----------------------------------------------------------------------


def test_inner_emits_only_the_named_value_to_a_pipe():
    env = {
        "PATH": "/usr/bin:/bin",
        "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF": FICTIONAL.decode(),
        "INFISICAL_TOKEN": "fictional-token-sentinel",
        "AC_DATABASE_URL": "postgresql://fictional",
    }
    script = str(ROOT / "infra/application/scripts/dev-qa-credential.py")
    argv = [sys.executable, "-I", script, "--inner", "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF"]
    result = subprocess.run(argv, env=env, capture_output=True, check=False)  # noqa: S603
    assert (result.returncode, result.stdout, result.stderr) == (0, FICTIONAL, b"")
    for name in ("INFISICAL_TOKEN", "AC_DATABASE_URL"):
        refused = subprocess.run(  # noqa: S603 - fixed test argv
            argv[:-1] + [name], env=env, capture_output=True, check=False
        )
        assert (refused.returncode, refused.stdout) == (2, b"")


def test_inner_refuses_a_terminal_or_file(tmp_path):
    script = str(ROOT / "infra/application/scripts/dev-qa-credential.py")
    target = tmp_path / "out"
    with target.open("wb") as handle:
        code = subprocess.call(  # noqa: S603 - fixed test argv
            [sys.executable, "-I", script, "--inner", "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF"],
            env={"AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF": FICTIONAL.decode()},
            stdout=handle,
        )
    assert code == 2 and target.read_bytes() == b""


def test_fetch_uses_existing_root_route_without_value_in_argv():
    seen = {}

    def runner(argv, **kwargs):
        seen.update(argv=argv, env=kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, FICTIONAL, None)

    value = broker.fetch(broker.IDENTITIES["billing-staff"], runner)
    assert bytes(value) == FICTIONAL
    assert seen["argv"][:2] == ["/usr/local/sbin/ac-infisical-run", "--"]
    assert seen["argv"][-2:] == ["--inner", "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF"]
    assert seen["env"]["AC_INFISICAL_ENVIRONMENT"] == "dev"
    assert seen["env"]["AC_INFISICAL_PATH"] == "/sales-xray/dev-fixture-accounts"
    assert not any(k.startswith("INFISICAL") for k in seen["env"])


@pytest.mark.parametrize(
    ("code", "stdout", "error"),
    [
        (3, b"", "secret_unavailable"),
        (0, b"INF Injecting 5 secrets\n" + FICTIONAL, "secret_invalid"),
        (0, b"short", "secret_invalid"),
        (0, SENTINEL, "secret_invalid"),
    ],
)
def test_fetch_fails_closed(code, stdout, error):
    runner = lambda argv, **_: subprocess.CompletedProcess(argv, code, stdout, None)  # noqa: E731
    with pytest.raises(broker.BrokerError) as raised:
        broker.fetch(broker.IDENTITIES["billing-staff"], runner)
    assert raised.value.code == error


def broker_main(monkeypatch, argv, *, euid=0, sudo_uid="1002", pipe=True, launcher_ok=True):
    monkeypatch.setattr(broker.os, "geteuid", lambda: euid)
    monkeypatch.setenv("SUDO_UID", sudo_uid)
    monkeypatch.setattr(broker, "stdout_is_pipe", lambda fd=1: pipe)
    monkeypatch.setattr(broker, "called_by_launcher", lambda pid: launcher_ok)
    written: list[bytes] = []
    monkeypatch.setattr(broker, "emit", lambda value: written.append(bytes(value)))
    runner = lambda a, **_: subprocess.CompletedProcess(a, 0, FICTIONAL, None)  # noqa: E731
    return broker.main(argv, runner=runner), written


@pytest.mark.parametrize(
    ("kwargs", "argv", "error"),
    [
        ({"euid": 1002}, ["billing-staff"], "root_required"),
        ({"sudo_uid": "0"}, ["billing-staff"], "non_root_caller_required"),
        ({"pipe": False}, ["billing-staff"], "stdout_must_be_pipe"),
        ({"launcher_ok": False}, ["billing-staff"], "launcher_required"),
        ({}, ["owner"], "identity_not_allowed"),
        ({}, ["billing-staff", "member"], "identity_not_allowed"),
    ],
)
def test_broker_refuses_outside_scope(monkeypatch, capsys, kwargs, argv, error):
    code, written = broker_main(monkeypatch, argv, **kwargs)
    assert (code, written) == (1, [])
    assert capsys.readouterr().err.strip() == f"ac-dev-qa-credential: refused: {error}"


def test_broker_sentinel_and_credential_go_only_to_the_pipe(monkeypatch, capsys):
    code, written = broker_main(monkeypatch, ["billing-staff", "--sentinel"])
    assert code == 0 and written[0].startswith(b"ac-qa-sentinel-") and len(written[0]) == 47
    code, written = broker_main(monkeypatch, ["billing-staff"])
    assert (code, written) == (0, [FICTIONAL])
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_called_by_launcher_walks_process_ancestry(tmp_path):
    def proc(pid, ppid, argv):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\n")
        (tmp_path / str(pid) / "cmdline").write_bytes(b"\0".join(argv) + b"\0")

    proc(30, 20, [b"sudo", b"-n", b"/usr/local/sbin/ac-dev-qa-credential"])
    proc(20, 10, [b"/usr/bin/python3", broker.LAUNCHER.encode(), b"--identity"])
    proc(40, 1, [b"/bin/bash"])
    assert broker.called_by_launcher(30, tmp_path) is True
    assert broker.called_by_launcher(40, tmp_path) is False


# Launcher --------------------------------------------------------------------


def edge(routes):
    return lambda path, port=launcher.EDGE_PORT: routes.get((path, port), (0, b""))


READY = {
    ("/login", 3017): (200, b""),
    ("/v1/me", 3017): (401, b""),
    ("/health/ready", 8100): (200, b'{"status":"ready","release_id":"local-unreleased"}'),
}
RECEIPT = {"host": launcher.HOST, "revision": REVISION, "contains": [MERGE]}


@pytest.fixture
def nonroot(monkeypatch):
    monkeypatch.setattr(launcher.os, "geteuid", lambda: 1002)


def test_preflight_passes_with_pinned_source_and_live_edge(nonroot):
    pin = launcher.preflight("billing-staff", launcher.ORIGIN, receipt=RECEIPT, edge=edge(READY))
    assert pin == {
        "identity": "billing-staff",
        "origin": launcher.ORIGIN,
        "admin_revision": REVISION,
    }


@pytest.mark.parametrize(
    ("identity", "origin", "receipt", "routes", "error"),
    [
        ("owner", launcher.ORIGIN, RECEIPT, READY, "identity_not_allowed"),
        (
            "billing-staff",
            "https://admin.authorityclosers.com",
            RECEIPT,
            READY,
            "origin_not_allowed",
        ),
        (
            "billing-staff",
            "https://admin-staging.authorityclosers.com",
            RECEIPT,
            READY,
            "origin_not_allowed",
        ),
        (
            "billing-staff",
            "http://admin-dev.authorityclosers.com",
            RECEIPT,
            READY,
            "origin_not_allowed",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            {**RECEIPT, "host": "admin.authorityclosers.com"},
            READY,
            "deployed_receipt_wrong_host",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            {**RECEIPT, "contains": []},
            READY,
            "deployed_source_missing_merge",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            {**RECEIPT, "revision": "main"},
            READY,
            "deployed_revision_invalid",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            RECEIPT,
            {**READY, ("/login", 3017): (502, b"")},
            "admin_dev_login_unavailable",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            RECEIPT,
            {**READY, ("/v1/me", 3017): (200, b"")},
            "admin_dev_api_route_unavailable",
        ),
        (
            "billing-staff",
            launcher.ORIGIN,
            RECEIPT,
            {**READY, ("/health/ready", 8100): (200, b'{"status":"held"}')},
            "admin_dev_api_not_ready",
        ),
    ],
)
def test_preflight_refuses_outside_scope(nonroot, identity, origin, receipt, routes, error):
    with pytest.raises(launcher.Refused) as raised:
        launcher.preflight(identity, origin, receipt=receipt, edge=edge(routes))
    assert raised.value.code == error


def test_preflight_refuses_root(monkeypatch):
    monkeypatch.setattr(launcher.os, "geteuid", lambda: 0)
    with pytest.raises(launcher.Refused) as raised:
        launcher.preflight("billing-staff", launcher.ORIGIN, receipt=RECEIPT, edge=edge(READY))
    assert raised.value.code == "run_as_non_root"


@pytest.mark.skipif(os.geteuid() == 0, reason="ownership check needs a non-root writer")
def test_receipt_must_be_root_owned(tmp_path):
    receipt = tmp_path / "deployed.json"
    receipt.write_text(json.dumps(RECEIPT))
    with pytest.raises(launcher.Refused) as raised:
        launcher.read_receipt(receipt)
    assert raised.value.code == "deployed_receipt_not_root"
    with pytest.raises(launcher.Refused) as raised:
        launcher.read_receipt(tmp_path / "missing.json")
    assert raised.value.code == "deployed_receipt_unreadable"


def fake_broker(tmp_path, body: str) -> list[str]:
    script = tmp_path / "broker.py"
    script.write_text("import sys, os\n" + body)
    return [sys.executable, str(script)]


def test_broker_secret_reads_pipe_into_memory(tmp_path):
    prefix = fake_broker(
        tmp_path, f"os.write(1, {SENTINEL!r}) if '--sentinel' in sys.argv else None"
    )
    value = launcher.broker_secret("billing-staff", sentinel=True, argv_prefix=prefix)
    assert isinstance(value, bytearray) and bytes(value) == SENTINEL


def test_broker_refusal_is_reported_by_code_only(tmp_path):
    prefix = fake_broker(
        tmp_path,
        "print('ac-dev-qa-credential: refused: launcher_required', file=sys.stderr)\nsys.exit(1)",
    )
    with pytest.raises(launcher.Refused) as raised:
        launcher.broker_secret("billing-staff", sentinel=False, argv_prefix=prefix)
    assert raised.value.code == "broker_launcher_required"


def test_json_string_escapes_without_str_copy():
    assert bytes(launcher.json_string(bytearray(b'a"b\\c'))) == b'"a\\"b\\\\c"'
    with pytest.raises(launcher.Refused):
        launcher.json_string(bytearray(b"line\nbreak"))


def test_leak_locations_find_profile_and_output_copies(tmp_path):
    profile = tmp_path / "profile"
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Preferences").write_text("{}")
    assert launcher.leak_locations(SENTINEL, [], profile, ['{"phase": "x"}']) == []
    (profile / "Default" / "Login Data").write_bytes(b"xx" + SENTINEL + b"yy")
    assert launcher.leak_locations(SENTINEL, [], profile, []) == ["profile_file"]
    printed = [json.dumps({"leak": SENTINEL.decode()})]
    assert launcher.leak_locations(SENTINEL, [], tmp_path / "none", printed) == ["launcher"]


def test_browser_argv_maps_only_admin_dev_and_pins_the_bridge_key():
    argv = launcher.chrome_argv("/chrome", Path("/p"), 43210, "SPKI=")
    rules = [a for a in argv if a.startswith("--host-resolver-rules=")]
    assert rules == ["--host-resolver-rules=MAP admin-dev.authorityclosers.com 127.0.0.1:43210"]
    assert "--ignore-certificate-errors-spki-list=SPKI=" in argv
    assert "--ignore-certificate-errors" not in argv
    assert "--remote-debugging-pipe" in argv and argv[-1] == "about:blank"
