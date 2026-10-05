"""Dev QA credential broker and browser launcher contracts, with fictional sentinels only.

No sudo, Infisical, browser or network: the broker's root route, the edge and the
deployed receipt are faked. The live sentinel run is recorded in the PR evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from ac_platform.development import billing_qa_fixture

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
ORG_MERGE = "61e6b240cd16c35ca87c19518aefcba1f3d3d555"
ORGS = ("organisation-operator", "organisation-reader", "organisation-denied")
README = ROOT / "infra/application/development/README.md"
REVISION = "ee819d0f5b18779c05b5661b06e76f27cabb2ca1"
SENTINEL = b"ac-qa-sentinel-0123456789abcdef0123456789abcdef"
FICTIONAL = b"Fictional-QA-pass_word!1"


def test_identity_tables_agree_and_are_fictional_dev_references():
    assert broker.IDENTITIES.keys() == launcher.IDENTITIES.keys()
    for name, ref in broker.IDENTITIES.items():
        mirror = launcher.IDENTITIES[name]
        assert (ref.email, ref.folder, ref.secret) == (mirror.email, mirror.folder, mirror.secret)
        assert ref.email.endswith("@example.test")
        assert ref.secret.startswith("AC_DEV_")
    assert broker.INFISICAL_ENVIRONMENT == "dev"
    assert launcher.IDENTITIES["billing-staff"].required_merges == (MERGE,)
    assert broker.LAUNCHER.endswith("/qa-admin-browser.py")


def test_allowlist_is_exactly_billing_staff_and_the_three_organisation_identities():
    assert set(broker.IDENTITIES) == set(launcher.IDENTITIES) == {"billing-staff", *ORGS}
    assert {n: (i.email, i.secret) for n, i in broker.IDENTITIES.items() if n in ORGS} == {
        "organisation-operator": (
            "qa-org-operator-aut961@example.test",
            "AC_DEV_FIXTURE_PASSWORD_ORG_OPERATOR",
        ),
        "organisation-reader": (
            "qa-org-reader-aut961@example.test",
            "AC_DEV_FIXTURE_PASSWORD_ORG_READER",
        ),
        "organisation-denied": (
            "qa-org-denied-aut961@example.test",
            "AC_DEV_FIXTURE_PASSWORD_ORG_DENIED",
        ),
    }
    assert launcher.IDENTITIES["billing-staff"].access == launcher.AccessCheck(
        ("platform_billing_manage",), (), None
    )
    for name in ORGS:
        assert launcher.IDENTITIES[name].required_merges == (ORG_MERGE,)
    matrix = {n: launcher.IDENTITIES[n].access for n in ORGS}
    read, manage = "platform_tenants_read", "platform_organisations_manage"
    assert matrix["organisation-operator"] == launcher.AccessCheck((read, manage), (), "read")
    assert matrix["organisation-reader"] == launcher.AccessCheck((read,), (manage,), "read")
    assert matrix["organisation-denied"] == launcher.AccessCheck((), (read, manage), "denied")


def test_billing_transport_matches_the_released_fixture_contract():
    for table in (broker.IDENTITIES, launcher.IDENTITIES):
        staff = table["billing-staff"]
        assert staff.email == billing_qa_fixture.EMAILS["staff"]
        assert staff.secret == billing_qa_fixture.PASSWORD_VARIABLES["staff"]
        assert staff.folder == "/application"
        assert billing_qa_fixture.EMAILS["customer"] not in {i.email for i in table.values()}
        assert billing_qa_fixture.PASSWORD_VARIABLES["customer"] not in {
            i.secret for i in table.values()
        }


def readme_block(marker: str) -> str:
    blocks = re.findall(r"```sh\n(.*?)```", README.read_text(encoding="utf-8"), re.DOTALL)
    return next(b for b in blocks if marker in b)


def test_sudoers_rule_grants_exactly_the_allowlisted_broker_argv():
    rule = readme_block("/etc/sudoers.d/ac-dev-qa-credential.new")
    body = rule.split("<<'SUDO'\n", 1)[1].split("\nSUDO", 1)[0].replace("\\\n", " ")
    defaults, grant = body.splitlines()
    assert defaults == "Defaults!/usr/local/sbin/ac-dev-qa-credential !use_pty"
    head, _, commands = grant.partition(" NOPASSWD: ")
    assert head == "acdev ALL=(root)"
    granted = [c.strip() for c in commands.split(",")]
    expected = [
        f"/usr/local/sbin/ac-dev-qa-credential {name}{flag}"
        for name in broker.IDENTITIES
        for flag in ("", " --sentinel")
    ]
    assert granted == expected
    assert not any(c in grant for c in ("*", "ALL:", "!", "SETENV", "sh -c"))


def test_readme_publishes_one_invocation_per_identity_and_the_receipt_pin():
    invocations = readme_block("--identity organisation-operator").splitlines()
    for name in ORGS:
        assert f"/usr/local/libexec/ac-dev-qa/qa-admin-browser.py --identity {name}" in invocations
    pin = readme_block("--write-receipt")
    assert f"--require-ancestor {ORG_MERGE}" in pin and f"--require-ancestor {MERGE}" in pin


# Broker ----------------------------------------------------------------------


@pytest.mark.parametrize("identity", broker.IDENTITIES.values())
def test_inner_emits_only_the_named_value_to_a_pipe(identity):
    env = {
        "PATH": "/usr/bin:/bin",
        identity.secret: FICTIONAL.decode(),
        "INFISICAL_TOKEN": "fictional-token-sentinel",
        "AC_DATABASE_URL": "postgresql://fictional",
        "AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER": "fictional-customer-sentinel",
        "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF": "fictional-obsolete-sentinel",
        "AC_DEV_FIXTURE_PASSWORD_UNDECLARED": "fictional-undeclared-sentinel",
    }
    script = str(ROOT / "infra/application/scripts/dev-qa-credential.py")
    argv = [sys.executable, "-I", script, "--inner", identity.secret]
    result = subprocess.run(argv, env=env, capture_output=True, check=False)  # noqa: S603
    assert (result.returncode, result.stdout, result.stderr) == (0, FICTIONAL, b"")
    for name in (
        "INFISICAL_TOKEN",
        "AC_DATABASE_URL",
        "AC_DEV_BILLING_FIXTURE_PASSWORD_CUSTOMER",
        "AC_DEV_FIXTURE_PASSWORD_BILLING_STAFF",
        "AC_DEV_FIXTURE_PASSWORD_UNDECLARED",
    ):
        refused = subprocess.run(  # noqa: S603 - fixed test argv
            argv[:-1] + [name], env=env, capture_output=True, check=False
        )
        assert (refused.returncode, refused.stdout) == (2, b"")


def test_inner_refuses_a_terminal_or_file(tmp_path):
    script = str(ROOT / "infra/application/scripts/dev-qa-credential.py")
    target = tmp_path / "out"
    with target.open("wb") as handle:
        code = subprocess.call(  # noqa: S603 - fixed test argv
            [sys.executable, "-I", script, "--inner", "AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF"],
            env={"AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF": FICTIONAL.decode()},
            stdout=handle,
        )
    assert code == 2 and target.read_bytes() == b""


@pytest.mark.parametrize("name", ORGS)
def test_fetch_reads_only_the_organisation_secret_name_from_dev(name):
    seen = {}

    def runner(argv, **kwargs):
        seen.update(argv=argv, env=kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, FICTIONAL, None)

    broker.fetch(broker.IDENTITIES[name], runner)
    assert seen["argv"][-2:] == ["--inner", broker.IDENTITIES[name].secret]
    assert (seen["env"]["AC_INFISICAL_ENVIRONMENT"], seen["env"]["AC_INFISICAL_PATH"]) == (
        "dev",
        "/sales-xray/dev-fixture-accounts",
    )
    assert FICTIONAL.decode() not in " ".join(seen["argv"])


def test_fetch_uses_existing_root_route_without_value_in_argv():
    seen = {}

    def runner(argv, **kwargs):
        seen.update(argv=argv, env=kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, FICTIONAL, None)

    value = broker.fetch(broker.IDENTITIES["billing-staff"], runner)
    assert bytes(value) == FICTIONAL
    assert seen["argv"][:2] == ["/usr/local/sbin/ac-infisical-run", "--"]
    assert seen["argv"][-2:] == ["--inner", "AC_DEV_BILLING_FIXTURE_PASSWORD_STAFF"]
    assert seen["env"]["AC_INFISICAL_ENVIRONMENT"] == "dev"
    assert seen["env"]["AC_INFISICAL_PATH"] == "/application"
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
        ({}, ["organisation-owner"], "identity_not_allowed"),
        ({}, ["qa-org-operator-aut961@example.test"], "identity_not_allowed"),
        ({}, ["organisation-operator", "organisation-reader"], "identity_not_allowed"),
        ({"launcher_ok": False}, ["organisation-denied", "--sentinel"], "launcher_required"),
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


@pytest.mark.parametrize("name", ORGS)
def test_broker_serves_organisation_sentinel_and_credential_only_to_the_pipe(
    monkeypatch, capsys, name
):
    code, written = broker_main(monkeypatch, [name, "--sentinel"])
    assert code == 0 and written[0].startswith(b"ac-qa-sentinel-") and FICTIONAL not in written[0]
    assert broker_main(monkeypatch, [name]) == (0, [FICTIONAL])
    assert capsys.readouterr() == ("", "")


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
    ("/v1/me/platform-access", 3017): (401, b""),
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
            {**READY, ("/v1/me/platform-access", 3017): (404, b"")},
            "platform_access_route_absent",
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


# Organisation identities -----------------------------------------------------

ORG_READY = {**READY, ("/v1/platform/organisations", 3017): (401, b"")}
ORG_RECEIPT = {**RECEIPT, "contains": [MERGE, ORG_MERGE]}


@pytest.mark.parametrize("name", ORGS)
def test_organisation_preflight_needs_the_ui_merge_and_the_live_route(nonroot, name):
    pin = launcher.preflight(name, launcher.ORIGIN, receipt=ORG_RECEIPT, edge=edge(ORG_READY))
    assert pin["identity"] == name and pin["admin_revision"] == REVISION
    with pytest.raises(launcher.Refused) as raised:
        launcher.preflight(name, launcher.ORIGIN, receipt=RECEIPT, edge=edge(ORG_READY))
    assert raised.value.code == "deployed_source_missing_merge"
    absent = {**ORG_READY, ("/v1/platform/organisations", 3017): (404, b"")}
    with pytest.raises(launcher.Refused) as raised:
        launcher.preflight(name, launcher.ORIGIN, receipt=ORG_RECEIPT, edge=edge(absent))
    assert raised.value.code == "organisations_route_absent"
    for origin in (
        "https://admin.authorityclosers.com",
        "https://admin-staging.authorityclosers.com",
        "https://admin-dev.authorityclosers.com.evil.test",
        "http://127.0.0.1:3017",
    ):
        with pytest.raises(launcher.Refused) as raised:
            launcher.preflight(name, origin, receipt=ORG_RECEIPT, edge=edge(ORG_READY))
        assert raised.value.code == "origin_not_allowed"


def test_billing_staff_preflight_does_not_need_the_organisations_route(nonroot):
    launcher.preflight("billing-staff", launcher.ORIGIN, receipt=RECEIPT, edge=edge(READY))


PERSON = "0f6c7a52-3c55-4b0e-9a55-6d7e0c1d2e3f"
READ, MANAGE = "platform_tenants_read", "platform_organisations_manage"
LISTED = {"status": 200, "code": None, "listed": True}
DENIED = {"status": 403, "code": "authorization_denied", "listed": False}


def granted(*permissions, status=200):
    return {"status": status, "person_id": PERSON, "platform_permissions": list(permissions)}


@pytest.mark.parametrize(
    ("name", "permissions", "organisations"),
    [
        ("billing-staff", ("platform_billing_manage",), None),
        ("organisation-operator", (MANAGE, READ), LISTED),
        ("organisation-operator", (READ, MANAGE, "platform_catalog_read"), LISTED),
        ("organisation-reader", (READ,), LISTED),
        ("organisation-denied", (), DENIED),
        ("organisation-denied", ("platform_catalog_read",), DENIED),
    ],
)
def test_access_matrix_passes_and_prints_only_person_and_permission_names(
    name, permissions, organisations
):
    access = launcher.IDENTITIES[name].access
    result = launcher.check_access(access, granted(*permissions), organisations)
    assert result == {
        "person_id": PERSON,
        "platform_permissions": sorted(permissions),
        "organisations": access.organisations,
    }


@pytest.mark.parametrize(
    ("name", "access_result", "organisations", "error"),
    [
        ("billing-staff", granted(), None, "permission_matrix_mismatch"),
        ("billing-staff", granted(READ, MANAGE), None, "permission_matrix_mismatch"),
        ("billing-staff", {"status": 404}, None, "platform_access_route_absent"),
        ("billing-staff", {"status": 401}, None, "platform_access_unavailable"),
        ("organisation-operator", granted(READ), LISTED, "permission_matrix_mismatch"),
        ("organisation-operator", granted(MANAGE), LISTED, "permission_matrix_mismatch"),
        ("organisation-reader", granted(READ, MANAGE), LISTED, "permission_matrix_mismatch"),
        ("organisation-reader", granted(), LISTED, "permission_matrix_mismatch"),
        ("organisation-denied", granted(READ), DENIED, "permission_matrix_mismatch"),
        ("organisation-denied", granted(MANAGE), DENIED, "permission_matrix_mismatch"),
        ("organisation-operator", {"status": 404}, LISTED, "platform_access_route_absent"),
        ("organisation-reader", {"status": 401}, LISTED, "platform_access_unavailable"),
        ("organisation-reader", None, LISTED, "platform_access_unavailable"),
        (
            "organisation-reader",
            {**granted(READ), "person_id": "admin@example.test"},
            LISTED,
            "person_invalid",
        ),
        (
            "organisation-reader",
            {**granted(READ), "platform_permissions": "platform_tenants_read"},
            LISTED,
            "permissions_invalid",
        ),
        (
            "organisation-operator",
            granted(READ, MANAGE),
            {"status": 404},
            "organisations_route_absent",
        ),
        ("organisation-denied", granted(), {"status": 404}, "organisations_route_absent"),
        ("organisation-operator", granted(READ, MANAGE), DENIED, "organisations_read_refused"),
        (
            "organisation-reader",
            granted(READ),
            {"status": 200, "listed": False},
            "organisations_read_refused",
        ),
        ("organisation-denied", granted(), LISTED, "organisations_not_capability_denied"),
        (
            "organisation-denied",
            granted(),
            {"status": 403, "code": "admin_surface_required"},
            "organisations_not_capability_denied",
        ),
        (
            "organisation-denied",
            granted(),
            {"status": 401, "code": "authentication_required"},
            "organisations_not_capability_denied",
        ),
    ],
)
def test_access_matrix_refuses_any_difference(name, access_result, organisations, error):
    with pytest.raises(launcher.Refused) as raised:
        launcher.check_access(launcher.IDENTITIES[name].access, access_result, organisations)
    assert raised.value.code == error


def test_page_scripts_never_return_session_or_organisation_contents():
    assert "session_id" not in launcher.ACCESS_JS
    assert "person_id: j.person_id" in launcher.ACCESS_JS
    assert "platform_permissions: j.platform_permissions" in launcher.ACCESS_JS
    assert "j.organisations" not in launcher.ORGANISATIONS_JS.replace(
        "Array.isArray(j.organisations)", ""
    )
    for script in (launcher.ACCESS_JS, launcher.ORGANISATIONS_JS):
        assert "cookie" not in script.lower() and "token" not in script.lower()


def test_billing_verification_reads_the_normal_access_api_only():
    calls = []

    class Browser:
        def evaluate(self, script):
            calls.append(script)
            return granted("platform_billing_manage")

    result = launcher.verify_access(Browser(), launcher.IDENTITIES["billing-staff"].access)
    assert calls == [launcher.ACCESS_JS]
    assert result["platform_permissions"] == ["platform_billing_manage"]


@pytest.mark.parametrize("fails", [False, True])
def test_broker_zeroes_selected_buffer_after_emission_or_error(monkeypatch, fails):
    buffer = bytearray(FICTIONAL)
    monkeypatch.setattr(broker, "fetch", lambda identity, runner: buffer)

    def emit(value):
        if fails:
            raise OSError("fictional pipe failure")

    monkeypatch.setattr(broker, "emit", emit)
    monkeypatch.setattr(broker.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_UID", "1002")
    monkeypatch.setattr(broker, "stdout_is_pipe", lambda: True)
    monkeypatch.setattr(broker, "called_by_launcher", lambda pid: True)
    if fails:
        with pytest.raises(OSError):
            broker.main(["billing-staff"])
    else:
        assert broker.main(["billing-staff"]) == 0
    assert buffer == bytearray(len(FICTIONAL))
