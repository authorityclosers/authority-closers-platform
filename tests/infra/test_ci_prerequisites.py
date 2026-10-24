"""Bounded CI prerequisite helper: fake apt/Playwright runners plus workflow guards."""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ci_prerequisites", ROOT / "scripts/ci/ci_prerequisites.py"
)
assert SPEC and SPEC.loader
prereq = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = prereq
SPEC.loader.exec_module(prereq)

BROWSER_LIBS = ["libnss3", "libgbm1", "fonts-liberation"]
DRY_RUN = (
    'sudo -- sh -c "apt-get update&& apt-get install -y --no-install-recommends '
    + " ".join(BROWSER_LIBS)
    + '"\n'
)


class FakeHost:
    """Answers each command from a table; records argv, limits and env."""

    def __init__(self, installed=(), failures=None, dry_run=DRY_RUN, probe_ok=True):
        self.installed = set(installed)
        self.failures = dict(failures or {})
        self.dry_run = dry_run
        self.probe_ok = probe_ok
        self.calls: list[tuple[list[str], float, dict | None]] = []
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}"

    def kind(self, argv: list[str]) -> str:
        if argv[0] == "dpkg-query":
            return "query"
        if argv[0] == "sudo":
            tool = argv[argv.index("DEBIAN_FRONTEND=noninteractive") + 1]
            if tool == "dpkg":
                return "repair"
            if "--download-only" in argv:
                return "apt-download"
            if "--no-download" in argv:
                return "offline-install"
            return "update" if "update" in argv else "install"
        if argv[1:3] == ["-m", "playwright"] or argv[:3] == ["pnpm", "exec", "playwright"]:
            return "dry-run" if "--dry-run" in argv else "download"
        if argv[1] in ("-c", "-e"):
            return "probe"
        return "version"

    def __call__(self, argv, seconds, env):
        argv = list(argv)
        self.calls.append((argv, seconds, env))
        kind = self.kind(argv)
        if kind == "query":
            ok = argv[-1] in self.installed
            return prereq.Result(0 if ok else 1, "installed" if ok else "")
        if kind == "dry-run":
            return prereq.Result(0, self.dry_run)
        if kind == "probe":
            return prereq.Result(
                0 if self.probe_ok else 1, "chromium 145.0" if self.probe_ok else ""
            )
        queue = self.failures.get(kind, [])
        outcome = queue.pop(0) if queue else "ok"
        if outcome == "timeout":
            self.now += seconds
            return prereq.Result(124, "Ign:1 mirror+file:/etc/apt/apt-mirrors.txt", timed_out=True)
        if outcome == "fail":
            self.now += 1
            return prereq.Result(100, "E: Unable to fetch some archives")
        self.now += 1
        if kind == "install":
            self.installed.update(argv[argv.index("--no-install-recommends") + 1 :])
        if kind == "apt-download":
            directory = Path(
                next(a.split("=", 1)[1] for a in argv if a.startswith("Dir::Cache::archives="))
            )
            for package in [*argv[argv.index("--download-only") + 1 :], "transitive-lib"]:
                (directory / f"{package}_1_amd64.deb").write_text(package)
        if kind == "offline-install":
            self.installed.update(Path(a).read_text() for a in argv if a.endswith(".deb"))
        return prereq.Result(0, "ffmpeg version 6.1" if kind == "version" else "")

    def of(self, kind: str) -> list[list[str]]:
        return [argv for argv, _, _ in self.calls if self.kind(argv) == kind]


def helper(host: FakeHost, deadline: float = prereq.DEADLINE_SECONDS):
    lines: list[str] = []
    tool = prereq.Prerequisites(
        runner=host,
        which=host.which,
        sleep=host.sleep,
        clock=host.clock,
        python="/venv/bin/python",
        deadline_seconds=deadline,
        log=lines.append,
    )
    return tool, lines


ALL_PACKAGES = {"ffmpeg", "e2fsprogs", "util-linux", *BROWSER_LIBS}


def test_present_prerequisites_skip_apt_and_still_prove_tools_and_browser() -> None:
    host = FakeHost(installed=ALL_PACKAGES)
    tool, lines = helper(host)
    tool.require(["codec", "filesystem", "browser"])
    assert host.of("update") == host.of("install") == []
    assert "apt: all 6 required packages already installed" in lines
    assert host.of("version") == [["ffmpeg", "-version"], ["ffprobe", "-version"]]
    assert host.of("download") == [["/venv/bin/python", "-m", "playwright", "install", "chromium"]]
    download_env = next(env for argv, _, env in host.calls if host.kind(argv) == "download")
    assert download_env == {"PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT": "30000"}
    assert len(host.of("probe")) == 1


def test_missing_packages_install_once_with_bounded_root_timeout() -> None:
    host = FakeHost(installed={"e2fsprogs", "util-linux", "libnss3"})
    tool, _ = helper(host)
    tool.require(["codec", "filesystem", "browser"])
    (update,) = host.of("update")
    (install,) = host.of("install")
    bounded = ["sudo", "--non-interactive", "timeout", "--kill-after=10s"]
    assert update[:4] == install[:4] == bounded
    assert update[4] == f"{prereq.UPDATE_SECONDS}s"
    assert install[4] == f"{prereq.INSTALL_SECONDS}s"
    for argv in (update, install):
        options = argv[argv.index("apt-get") + 1 :]
        assert "Acquire::http::Timeout=20" in options
        assert "Acquire::https::Timeout=20" in options
        assert "DPkg::Lock::Timeout=60" in options
    assert install[install.index("--no-install-recommends") + 1 :] == [
        "ffmpeg",
        "libgbm1",
        "fonts-liberation",
    ]
    assert host.of("repair") == []


def test_apt_stall_fails_closed_after_bounded_attempts_without_install() -> None:
    host = FakeHost(failures={"update": ["timeout"] * 3})
    tool, lines = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="apt-get update: failed after 3"):
        tool.require(["codec"])
    assert len(host.of("update")) == prereq.ATTEMPTS
    assert host.of("install") == host.of("version") == []
    assert host.sleeps == list(prereq.BACKOFF_SECONDS)
    assert any("attempt 3/3 timed out" in line for line in lines)
    assert any("apt-mirrors.txt" in line for line in lines)


def test_failed_install_repairs_dpkg_before_retrying() -> None:
    host = FakeHost(installed=ALL_PACKAGES - {"ffmpeg"}, failures={"install": ["timeout"]})
    tool, lines = helper(host)
    tool.require(["codec"])
    assert len(host.of("install")) == 2
    (repair,) = host.of("repair")
    assert repair[-3:] == ["dpkg", "--configure", "-a"]
    order = [host.kind(argv) for argv, _, _ in host.calls]
    assert order.index("repair") < len(order) - 1 - order[::-1].index("install")
    assert "apt-get install: ok on attempt 2 in 1s" in lines


def test_overall_deadline_caps_every_attempt_and_fails_closed() -> None:
    host = FakeHost(failures={"update": ["timeout"] * 3})
    tool, _ = helper(host, deadline=150)
    with pytest.raises(prereq.PrerequisiteError, match="budget spent"):
        tool.require(["codec"])
    limits = [seconds for argv, seconds, _ in host.calls if host.kind(argv) == "update"]
    assert limits[0] == prereq.UPDATE_SECONDS + 20
    assert all(limit <= 150 + 20 for limit in limits)
    assert host.now <= 150 + 20


def test_browser_download_retries_then_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES, failures={"download": ["fail"] * 3})
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="playwright install: failed after 3"):
        tool.require(["browser"])
    assert host.of("probe") == []


@pytest.mark.parametrize(
    "dry_run",
    ["", "nothing to install\n", 'apt-get install -y --no-install-recommends lib$(boom)"'],
)
def test_unreadable_playwright_dependency_list_fails_closed(dry_run: str) -> None:
    host = FakeHost(dry_run=dry_run)
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="Chromium system packages"):
        tool.require(["browser"])
    assert host.of("update") == host.of("download") == []


def test_browser_that_cannot_launch_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES, probe_ok=False)
    tool, _ = helper(host)
    with pytest.raises(prereq.PrerequisiteError, match="did not launch"):
        tool.require(["browser"])


def test_missing_command_after_install_fails_closed() -> None:
    host = FakeHost(installed=ALL_PACKAGES)
    tool, _ = helper(host)
    tool.which = lambda name: None if name == "findmnt" else f"/usr/bin/{name}"
    with pytest.raises(prereq.PrerequisiteError, match="findmnt"):
        tool.require(["filesystem"])


def test_cold_cache_captures_dependencies_and_warm_cache_never_contacts_mirrors(tmp_path) -> None:
    cold = FakeHost(installed={"util-linux", "e2fsprogs"})
    tool, _ = helper(cold)
    tool.package_cache = tmp_path
    tool.require(["codec", "filesystem", "browser"])
    assert len(cold.of("update")) == len(cold.of("apt-download")) == 1
    assert cold.of("install") == []
    record = json.loads((tmp_path / "manifest.json").read_text())
    assert "transitive-lib_1_amd64.deb" in record["archives"]
    (install,) = cold.of("offline-install")
    assert "--no-download" in install and "--no-remove" in install
    assert f"Dir::Cache::archives={tmp_path}/" in install
    assert str(tmp_path / "transitive-lib_1_amd64.deb") in install

    warm = FakeHost(installed={"util-linux", "e2fsprogs"}, failures={"update": ["timeout"] * 3})
    tool, lines = helper(warm)
    tool.package_cache, tool.offline = tmp_path, True
    tool.require(["codec", "filesystem", "browser"])
    assert warm.of("update") == warm.of("apt-download") == warm.of("download") == []
    assert len(warm.of("offline-install")) == len(warm.of("probe")) == 1
    assert len(warm.of("version")) == 2
    assert warm.installed >= ALL_PACKAGES
    assert any("no mirror access" in line for line in lines)


@pytest.mark.parametrize("damage", ["changed", "removed", "extra", "request", "manifest"])
def test_bad_warm_cache_fails_closed_without_network(tmp_path, damage) -> None:
    tool, _ = helper(FakeHost())
    tool.package_cache = tmp_path
    tool.require(["codec"])
    if damage == "changed":
        (tmp_path / "ffmpeg_1_amd64.deb").write_text("corrupt")
    elif damage == "removed":
        (tmp_path / "ffmpeg_1_amd64.deb").unlink()
    elif damage == "extra":
        (tmp_path / "extra_1_amd64.deb").write_text("extra")
    elif damage == "manifest":
        (tmp_path / "manifest.json").unlink()
    host = FakeHost()
    tool, _ = helper(host)
    tool.package_cache, tool.offline = tmp_path, True
    with pytest.raises(prereq.PrerequisiteError, match="cache"):
        tool.require(["filesystem"] if damage == "request" else ["codec"])
    assert host.of("update") == host.of("apt-download") == host.of("offline-install") == []


def test_fully_preinstalled_transaction_caches_without_apt(tmp_path) -> None:
    host = FakeHost(installed=ALL_PACKAGES)
    tool, _ = helper(host)
    tool.package_cache = tmp_path
    tool.require(["codec", "browser"])
    assert json.loads((tmp_path / "manifest.json").read_text())["archives"] == {}
    tool.offline = True
    tool.require(["codec", "browser"])
    assert host.of("update") == host.of("offline-install") == []
    assert len(host.of("probe")) == 2


def test_cache_key_tracks_runner_image_components_and_locked_node_packages(monkeypatch) -> None:
    tool, _ = helper(FakeHost())
    monkeypatch.setenv("ImageVersion", "20261022.1")
    key = tool.cache_key(["codec", "browser"])
    assert key == tool.cache_key(["browser", "codec"])
    assert key != tool.cache_key(["codec"])
    monkeypatch.setenv("ImageVersion", "20261023.1")
    assert key != tool.cache_key(["codec", "browser"])
    monkeypatch.setenv("ImageVersion", "20261022.1")
    tool.node_browser = True
    assert key != tool.cache_key(["codec", "browser"])
    assert tool.playwright == ["pnpm", "exec", "playwright"]


@pytest.mark.skipif(
    not shutil.which("apt-get") or not shutil.which("dpkg-deb"), reason="Debian tools"
)
def test_real_apt_passes_local_archives_to_dpkg_without_indexes_or_network(tmp_path) -> None:
    # Exercise real acquisition, not --simulate/--download-only (both can hide
    # a wrong archive directory). Replace dpkg with a recorder so host package
    # configuration and post-install hooks cannot run.
    archives = []
    directory = tmp_path / "archives"
    (directory / "partial").mkdir(parents=True)
    for name, dependency in [("ac-ci-fixture-dep", ""), ("ac-ci-fixture", "ac-ci-fixture-dep")]:
        package = tmp_path / name
        (package / "DEBIAN").mkdir(parents=True)
        (package / "DEBIAN/control").write_text(
            f"Package: {name}\nVersion: 1.0\nArchitecture: all\nMaintainer: CI <ci@example.test>\n"
            + (f"Depends: {dependency}\n" if dependency else "")
            + "Description: fictional CI offline acquisition fixture\n"
        )
        archive = directory / f"{name}_1.0_all.deb"
        subprocess.run(  # noqa: S603 - fixed executable and fictional fixture paths
            ["/usr/bin/dpkg-deb", "--build", str(package), str(archive)],
            check=True,
            capture_output=True,
        )
        archives.append(str(archive))
    (tmp_path / "state/lists/partial").mkdir(parents=True)
    (tmp_path / "empty-config").mkdir()
    (tmp_path / "log").mkdir()
    (tmp_path / "status").touch()
    (tmp_path / "empty.conf").touch()
    recorder = tmp_path / "dpkg-recorder"
    calls = tmp_path / "dpkg-argv"
    recorder.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >> " + shlex.quote(str(calls)) + "\n")
    recorder.chmod(0o700)
    config = tmp_path / "apt.conf"
    config.write_text(
        f'Dir::Etc::parts "{tmp_path}/empty-config";\nDir::Etc::main "{tmp_path}/empty.conf";\n'
    )
    command = [
        "/usr/bin/apt-get",
        "--yes",
        "--no-download",
        "--no-remove",
        "--no-install-recommends",
    ]
    for key, value in [
        ("Dir::State", tmp_path / "state"),
        ("Dir::State::status", tmp_path / "status"),
        ("Dir::Cache", tmp_path / "empty-cache"),
        ("Dir::Log", tmp_path / "log"),
        ("Dir::Etc::sourcelist", tmp_path / "empty.conf"),
        ("Dir::Etc::sourceparts", tmp_path / "empty-config"),
        ("Dir::Bin::dpkg", recorder),
        ("Debug::NoLocking", "1"),
    ]:
        command += ["-o", f"{key}={value}"]

    def install(options):
        return subprocess.run(  # noqa: S603 - real apt, isolated state, no-op dpkg, fictional inputs
            [*command, *options, "install", *archives],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "APT_CONFIG": str(config), "LC_ALL": "C"},
        )

    # This is the exact hosted failure, reproduced with no mirror or root access.
    assert install([]).returncode != 0
    result = install(["-o", f"Dir::Cache::archives={directory}/"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--unpack" in calls.read_text()
    assert all(path in calls.read_text() for path in archives)
    assert (tmp_path / "status").read_text() == ""


def test_main_reports_a_github_error_and_nonzero(monkeypatch, capsys) -> None:
    def refuse(self, components):
        raise prereq.PrerequisiteError("apt-get update: failed after 3 bounded attempts")

    monkeypatch.setattr(prereq.Prerequisites, "require", refuse)
    assert prereq.main(["codec"]) == 1
    assert "::error::CI prerequisites: apt-get update" in capsys.readouterr().out


def test_run_bounded_kills_the_whole_process_group_on_timeout(tmp_path) -> None:
    marker = tmp_path / "child-survived"
    started = time.monotonic()
    result = prereq.run_bounded(
        ["sh", "-c", f"(sleep 3; touch {shlex.quote(str(marker))}) & sleep 30"], 1
    )
    assert result.timed_out and result.returncode == 124
    assert time.monotonic() - started < 10
    time.sleep(3.5)
    assert not marker.exists()


def test_locked_playwright_reports_parseable_chromium_packages() -> None:
    tool = prereq.Prerequisites(python=sys.executable)
    packages = tool.browser_packages()
    assert "libnss3" in packages
    assert all(prereq.PACKAGE_NAME.fullmatch(name) for name in packages)


def _jobs() -> dict:
    workflow = (ROOT / ".github/workflows/application.yml").read_text(encoding="utf-8")
    assert "apt-get" not in workflow
    assert "--with-deps" not in workflow
    return yaml.safe_load(workflow)["jobs"]


@pytest.mark.parametrize(
    ("job_id", "step_name", "components", "first_use"),
    [
        (
            "validate-sales-xray-acquisition-browser",
            "Require codec and locked acquisition browser",
            ["codec", "browser"],
            "Build verified AudioAtlas for acquisition browser",
        ),
        (
            "validate-python-tests",
            "Require codec, filesystem and locked browser prerequisites",
            ["codec", "filesystem", "browser"],
            "Build verified AudioAtlas for conversation regressions",
        ),
        (
            "validate-python-gates",
            "Require codec, filesystem and locked browser prerequisites",
            ["codec", "filesystem", "browser"],
            "Build verified AudioAtlas for conversation regressions",
        ),
    ],
)
def test_each_job_runs_one_bounded_locked_prerequisite_step(
    job_id, step_name, components, first_use
) -> None:
    job = _jobs()[job_id]
    names = [step.get("name") for step in job["steps"]]
    assert names.count(step_name) == 1
    step = job["steps"][names.index(step_name)]
    assert "if" not in step and not step.get("continue-on-error", False)
    assert step["timeout-minutes"] * 60 > prereq.DEADLINE_SECONDS
    assert step["timeout-minutes"] < job["timeout-minutes"]
    assert step["uses"] == "./.github/actions/ci-prerequisites"
    assert step["with"]["components"].split() == components
    locked = next(i for i, name in enumerate(names) if name and name.startswith("Install locked"))
    assert locked < names.index(step_name) < names.index(first_use)


def test_python_shards_coverage_and_evidence_are_unchanged() -> None:
    jobs = _jobs()
    shards = jobs["validate-python-tests"]
    assert shards["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    assert shards["strategy"]["fail-fast"] is False
    assert shards["timeout-minutes"] == 30
    names = [step.get("name") for step in shards["steps"]]
    run = shards["steps"][names.index("Run deterministic Python test shard")]
    assert "--shard-count 4" in run["run"]
    evidence = shards["steps"][names.index("Retain Python shard evidence")]
    assert evidence["if"] == "always()"
    assert evidence["with"]["if-no-files-found"] == "error"
    aggregate = [step.get("name") for step in jobs["validate"]["steps"]]
    assert "Verify complete Python shard coverage" in aggregate


def test_shared_action_requires_verified_bundle_without_consumer_downloads() -> None:
    action = yaml.safe_load((ROOT / ".github/actions/ci-prerequisites/action.yml").read_text())
    assert action["inputs"]["bundle"]["required"] is True
    steps = action["runs"]["steps"]
    assert all("actions/cache" not in step.get("uses", "") for step in steps)
    install = next(step for step in steps if "consume --directory" in step.get("run", ""))
    assert install["env"]["PREREQ_BUNDLE"] == "${{ inputs.bundle }}"
    assert "continue-on-error" not in install
    for step in steps:
        assert "${{ inputs." not in step.get("run", "")


def test_workbench_routes_action_changes_and_overlays_action_for_historical_sources() -> None:
    spec = importlib.util.spec_from_file_location("wb_checks", ROOT / "scripts/ci/wb_checks.py")
    assert spec and spec.loader
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    families, full = checks.families(
        {
            "full": False,
            "checks": [],
            "changed_files": [".github/actions/ci-prerequisites/action.yml"],
        }
    )
    assert families == {"py", "web", "visual", "migrations", "control"} and full
    script = (ROOT / "scripts/ci/wb-ci").read_text()
    # Read only the shell array, not incidental mentions elsewhere in the tool.
    overlays = script.split("CI_FILES=(", 1)[1].split(")", 1)[0].split()
    assert ".github/actions/ci-prerequisites/action.yml" in overlays
    assert "scripts/ci/ci_prerequisites.py" in overlays


def test_workbench_jobs_use_cached_proofs_and_foreground_dependency_failures() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/workbench-checks.yml").read_text())["jobs"]
    for name in ("py-tests", "visual", "e2e"):
        steps = jobs[name]["steps"]
        required = [s for s in steps if s.get("uses") == "./.github/actions/ci-prerequisites"]
        assert len(required) == 1
        assert "if" not in required[0] and not required[0].get("continue-on-error")
    visual_steps = jobs["visual"]["steps"]
    dependencies = next(
        s for s in visual_steps if s.get("name") == "Install locked Node dependencies"
    )
    visual = next(s for s in visual_steps if "node-browser" in s.get("with", {}))
    assert visual_steps.index(dependencies) < visual_steps.index(visual)
    assert visual["with"] == {
        "bundle": "${{ needs.ci-prerequisites.outputs.bundle }}",
        "components": "browser",
        "python": "python3",
        "node-browser": "true",
    }
    scripts = "\n".join(s.get("run", "") for s in jobs["py-tests"]["steps"])
    assert "prereq.rc" not in scripts and "pnpm.rc" not in scripts
    node = next(
        s for s in jobs["py-tests"]["steps"] if s.get("name") == "Install locked Node dependencies"
    )
    assert node["timeout-minutes"] == 6
    assert "pnpm install --frozen-lockfile" in node["run"] and "&\n" not in node["run"]
