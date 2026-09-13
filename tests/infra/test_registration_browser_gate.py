"""Small process/HTTP/report fixtures; no Next build, Chromium or provider runs."""

from __future__ import annotations

import importlib.util
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "registration_browser_gate", ROOT / "scripts/verify-registration-browser.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def report_xml(names=None, outcome: str = "") -> str:
    names = sorted(gate.EXPECTED_CASES) if names is None else names
    return (
        '<testsuites><testsuite tests="3" errors="0" failures="0" skipped="0">'
        + "".join(f'<testcase name="{name}">{outcome}</testcase>' for name in names)
        + "</testsuite></testsuites>"
    )


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((gate.HOST, 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("outcome", ["<skipped/>", "<failure/>", "<error/>"])
def test_report_rejects_nonpassing_cases(tmp_path: Path, outcome: str) -> None:
    report = tmp_path / "report.xml"
    report.write_text(report_xml(outcome=outcome), encoding="utf-8")
    with pytest.raises(gate.GateError, match="three registration cases"):
        gate.verify_report(report)


@pytest.mark.parametrize("variant", ["missing", "malformed", "zero", "one-missing", "duplicate"])
def test_report_requires_exact_case_set(tmp_path: Path, variant: str) -> None:
    report = tmp_path / "report.xml"
    names = sorted(gate.EXPECTED_CASES)
    if variant == "malformed":
        report.write_text("not XML", encoding="utf-8")
    elif variant == "zero":
        report.write_text(report_xml([]), encoding="utf-8")
    elif variant == "one-missing":
        report.write_text(report_xml(names[:2]), encoding="utf-8")
    elif variant == "duplicate":
        report.write_text(report_xml([names[0], names[0], names[2]]), encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.verify_report(report)


def test_exact_report_is_accepted(tmp_path: Path) -> None:
    report = tmp_path / "report.xml"
    report.write_text(report_xml(), encoding="utf-8")
    gate.verify_report(report)


@pytest.mark.parametrize(
    "payload",
    ['<!DOCTYPE testsuites [<!ENTITY x "bad">]><testsuites/>', "x" * 1_000_001],
    ids=["entities", "oversized"],
)
def test_report_refuses_entities_and_oversized_input(tmp_path: Path, payload: str) -> None:
    report = tmp_path / "report.xml"
    report.write_text(payload, encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.verify_report(report)


def fixture_commands(tmp_path: Path, port: int, *, server_mode="ready", test_mode="pass"):
    server = tmp_path / "server-fixture.py"
    server.write_text(
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "from pathlib import Path\nimport os,sys\n"
        "Path('server.pid').write_text(str(os.getpid()))\n"
        "mode=sys.argv[2]\n"
        "if mode=='exit':sys.exit(7)\n"
        "class Handler(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  redirect=mode=='redirect' and self.path=='/register'\n"
        "  self.send_response(302 if redirect else 200)\n"
        "  if redirect:self.send_header('Location','/destination')\n"
        "  self.end_headers()\n"
        "  self.wfile.write(b'Create free account' if mode!='unready' else b'not ready')\n"
        " def log_message(self,*args):pass\n"
        "HTTPServer(('127.0.0.1',int(sys.argv[1])),Handler).serve_forever()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "pytest-fixture.py"
    tests.write_text(
        "from pathlib import Path\nimport os,sys,time\n"
        "Path('tests.pid').write_text(str(os.getpid()))\n"
        "mode=sys.argv[1]\n"
        "if mode=='timeout':time.sleep(30)\n"
        "if mode=='failure':sys.exit(1)\n"
        "if mode!='missing':Path('registration.xml').write_text(sys.argv[2],encoding='utf-8')\n",
        encoding="utf-8",
    )
    return (
        [sys.executable, str(server), str(port), server_mode],
        [sys.executable, str(tests), test_mode, report_xml()],
    )


def assert_listener_closed(port: int) -> None:
    # Observes only; never finds or terminates processes by port/PID.
    with pytest.raises(OSError), socket.create_connection((gate.HOST, port), timeout=0.3):
        pass


def test_owned_lifecycle_success(tmp_path: Path) -> None:
    port = free_port()
    server, tests = fixture_commands(tmp_path, port)
    gate.run_owned_gate(
        server,
        tests,
        cwd=tmp_path,
        env=gate.child_environment(),
        evidence=tmp_path,
        port=port,
        readiness_timeout=5,
        test_timeout=5,
    )
    assert (tmp_path / "server.pid").is_file()
    assert (tmp_path / "tests.pid").is_file()
    assert_listener_closed(port)


@pytest.mark.parametrize("server_mode", ["exit", "redirect", "unready"])
def test_readiness_failure_does_not_start_tests(tmp_path: Path, server_mode: str) -> None:
    port = free_port()
    server, tests = fixture_commands(tmp_path, port, server_mode=server_mode)
    with pytest.raises(gate.GateError, match="readiness|become ready"):
        gate.run_owned_gate(
            server,
            tests,
            cwd=tmp_path,
            env=gate.child_environment(),
            evidence=tmp_path,
            port=port,
            readiness_timeout=1,
            test_timeout=5,
        )
    assert not (tmp_path / "tests.pid").exists()
    assert_listener_closed(port)


@pytest.mark.parametrize("test_mode", ["failure", "missing", "timeout"])
def test_test_failure_or_timeout_cleans_server(tmp_path: Path, test_mode: str) -> None:
    port = free_port()
    server, tests = fixture_commands(tmp_path, port, test_mode=test_mode)
    with pytest.raises(gate.GateError):
        gate.run_owned_gate(
            server,
            tests,
            cwd=tmp_path,
            env=gate.child_environment(),
            evidence=tmp_path,
            port=port,
            readiness_timeout=5,
            test_timeout=1,
        )
    assert_listener_closed(port)


def test_occupied_port_is_preserved_without_starting_children(tmp_path: Path) -> None:
    with socket.socket() as unrelated:
        unrelated.bind((gate.HOST, 0))
        unrelated.listen()
        port = unrelated.getsockname()[1]
        server, tests = fixture_commands(tmp_path, port)
        with pytest.raises(gate.GateError, match="not free"):
            gate.run_owned_gate(
                server,
                tests,
                cwd=tmp_path,
                env=gate.child_environment(),
                evidence=tmp_path,
                port=port,
            )
        assert unrelated.getsockname()[1] == port
        assert not (tmp_path / "server.pid").exists()


def test_stale_report_is_rejected_before_launch(tmp_path: Path) -> None:
    (tmp_path / "registration.xml").write_text(report_xml(), encoding="utf-8")
    server, tests = fixture_commands(tmp_path, free_port())
    with pytest.raises(gate.GateError, match="stale"):
        gate.run_owned_gate(
            server,
            tests,
            cwd=tmp_path,
            env=gate.child_environment(),
            evidence=tmp_path,
        )
    assert not (tmp_path / "server.pid").exists()


def test_cleanup_failure_prevents_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = gate.OwnedProcess.close

    def close_then_fail(self):
        original(self)
        raise gate.GateError("synthetic cleanup failure")

    monkeypatch.setattr(gate.OwnedProcess, "close", close_then_fail)
    port = free_port()
    server, tests = fixture_commands(tmp_path, port)
    with pytest.raises(gate.GateError, match="cleanup failure"):
        gate.run_owned_gate(
            server,
            tests,
            cwd=tmp_path,
            env=gate.child_environment(),
            evidence=tmp_path,
            port=port,
            readiness_timeout=5,
            test_timeout=5,
        )
    assert_listener_closed(port)


def test_owned_process_removes_its_descendant(tmp_path: Path) -> None:
    port = free_port()
    server, _ = fixture_commands(tmp_path, port)
    parent = "import subprocess,sys,time; subprocess.Popen(sys.argv[1:]); time.sleep(30)"
    with (tmp_path / "tree.log").open("xb") as log:
        owned = gate.OwnedProcess(
            [sys.executable, "-c", parent, *server],
            cwd=tmp_path,
            env=gate.child_environment(),
            log=log,
        )
        try:
            gate.wait_ready(owned.process, port, 5)
        finally:
            owned.close()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            gate.require_listener_closed(port)
            break
        except gate.GateError:
            time.sleep(0.05)
    assert_listener_closed(port)


def test_child_environment_drops_credentials_and_test_selectors(monkeypatch) -> None:
    for key in (
        "AC_DATABASE_URL",
        "GOOGLE_CLIENT_SECRET",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "NODE_OPTIONS",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "AC_DEV_API_MODE",
    ):
        monkeypatch.setenv(key, "synthetic-untrusted-environment")
        assert key not in gate.child_environment()


def test_prepare_only_adds_normal_static_assets_without_repairing_dependencies(tmp_path: Path):
    web = tmp_path / "apps/learner-web"
    runtime = web / ".next/standalone/apps/learner-web"
    runtime.mkdir(parents=True)
    (runtime / "server.js").write_text("// fixture", encoding="utf-8")
    for path in (web / ".next/static/a.js", web / "public/theme-init.js"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unchanged fixture", encoding="utf-8")
    untouched = web / ".next/standalone/node_modules/fixture.txt"
    untouched.parent.mkdir(parents=True)
    untouched.write_text("leave this exact dependency alone", encoding="utf-8")
    assert gate.prepare_standalone(tmp_path) == runtime / "server.js"
    assert untouched.read_text(encoding="utf-8") == "leave this exact dependency alone"
    with pytest.raises(gate.GateError, match="fresh build"):
        gate.prepare_standalone(tmp_path)


@pytest.mark.parametrize("url", [None, "https://external.test", "http://127.0.0.1:3181/?x=1"])
def test_required_browser_cases_reject_missing_or_foreign_url(monkeypatch, url) -> None:
    from tests.e2e import test_google_registration_browser as browser_cases

    monkeypatch.setenv(gate.REQUIRED_FLAG, "1")
    if url is None:
        monkeypatch.delenv("AC_LEARNER_E2E_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("AC_LEARNER_E2E_BASE_URL", url)
    with pytest.raises(pytest.fail.Exception):
        browser_cases._browser_base_url()


def test_required_browser_cases_accept_only_the_gate_url(monkeypatch) -> None:
    from tests.e2e import test_google_registration_browser as browser_cases

    monkeypatch.setenv(gate.REQUIRED_FLAG, "1")
    monkeypatch.setenv("AC_LEARNER_E2E_BASE_URL", gate.BASE_URL)
    assert browser_cases._browser_base_url() == gate.BASE_URL


def test_required_missing_playwright_is_a_collection_failure() -> None:
    command = (
        "import importlib.abc,runpy,sys; "
        "Block=type('Block',(importlib.abc.MetaPathFinder,),"
        "{'find_spec':lambda self,name,*args: "
        "(_ for _ in ()).throw(ImportError('synthetic missing Playwright')) "
        "if name.startswith('playwright') else None}); "
        "sys.meta_path.insert(0,Block()); runpy.run_path(sys.argv[1])"
    )
    env = gate.child_environment()
    env[gate.REQUIRED_FLAG] = "1"
    result = subprocess.run(  # noqa: S603 - fixed import-only fixture, no browser
        [sys.executable, "-c", command, str(ROOT / gate.TEST_FILE)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "Playwright is required for the registration browser gate" in result.stderr


@pytest.mark.parametrize(
    ("url", "method", "expected"),
    [
        (gate.BASE_URL + "/_next/static/a.js", "GET", "continue"),
        (gate.BASE_URL + "/v1/auth/google/start?action=register", "GET", "intercept"),
        ("https://accounts.google.com/v1/auth/google/start", "GET", "block"),
        (gate.BASE_URL + "/v1/auth/password/register", "POST", "block"),
        (gate.BASE_URL + "/v1/auth/google/start", "OPTIONS", "block"),
    ],
)
def test_browser_transport_never_dispatches_provider_or_mutation(url, method, expected) -> None:
    from tests.e2e import test_google_registration_browser as browser_cases

    actions = []
    route = SimpleNamespace(
        request=SimpleNamespace(url=url, method=method),
        abort=lambda: actions.append("block"),
        continue_=lambda: actions.append("continue"),
        fulfill=lambda **kwargs: actions.append("intercept") if kwargs == {"status": 204} else None,
    )
    captured, blocked = [], []
    browser_cases._route_request(route, gate.BASE_URL, captured, blocked)
    assert actions == [expected]
    assert captured == ([url] if expected == "intercept" else [])
    assert bool(blocked) == (expected == "block")


def test_workflow_installs_browser_before_validation_and_runs_gate_after() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/application.yml").read_text("utf-8"))
    job = workflow["jobs"]["validate"]
    names = [step.get("name") for step in job["steps"]]
    install_name = "Install locked registration browser"
    gate_name = "Prove registration consent and server-rendered readiness"
    assert names.count(install_name) == names.count(gate_name) == 1
    assert names.index(install_name) < names.index("Validate application") < names.index(gate_name)
    install = job["steps"][names.index(install_name)]
    required = job["steps"][names.index(gate_name)]
    for step in (install, required):
        assert "if" not in step and not step.get("continue-on-error", False)
        assert step["timeout-minutes"] == 5
    assert shlex.split(install["run"]) == [
        "uv",
        "run",
        "--frozen",
        "python",
        "-m",
        "playwright",
        "install",
        "--with-deps",
        "chromium",
    ]
    assert required["env"] == {
        gate.REQUIRED_FLAG: "1",
        "AC_LEARNER_E2E_BASE_URL": gate.BASE_URL,
    }
    assert gate.REQUIRED_FLAG not in job.get("env", {})
    assert "AC_LEARNER_E2E_BASE_URL" not in job.get("env", {})
    assert shlex.split(required["run"]) == [
        "uv",
        "run",
        "--frozen",
        "python",
        "scripts/verify-registration-browser.py",
        "--evidence-dir",
        "${{ runner.temp }}/registration-browser-${{ github.sha }}",
    ]
