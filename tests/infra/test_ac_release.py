"""Behaviour of the staging release engine (infra/release/ac_release.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ac_release", ROOT / "infra/release/ac_release.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["ac_release"] = MODULE
SPEC.loader.exec_module(MODULE)

REPO = MODULE.REPOSITORY
HEAD = "a" * 40
OLD = "b" * 40
OUTSIDE = "c" * 40
DIGEST = "sha256:" + "d" * 64


def run(sha: str, workflow: str = MODULE.CORE_WORKFLOW, **overrides: Any) -> dict[str, Any]:
    data = {
        "id": 100,
        "run_number": 1,
        "head_sha": sha,
        "event": "push",
        "head_branch": "main",
        "path": f".github/workflows/{workflow}",
        "repository": {"full_name": REPO},
        "status": "completed",
        "conclusion": "success",
    }
    data.update(overrides)
    return data


def artifact(sha: str, name: str, run_id: int = 100, **overrides: Any) -> dict[str, Any]:
    data = {
        "id": 7,
        "name": name,
        "expired": False,
        "digest": DIGEST,
        "size_in_bytes": 1000,
        "workflow_run": {"id": run_id, "head_sha": sha},
    }
    data.update(overrides)
    return data


class FakeGitHub:
    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.artifacts: dict[int, list[dict[str, Any]]] = {}
        self.web_success: list[str] = []

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        params = params or {}
        if path.endswith("/runs") and "/workflows/" in path:
            workflow = path.split("/workflows/")[1].split("/")[0]
            if "head_sha" in params:
                return {"workflow_runs": self.runs.get((workflow, params["head_sha"]), [])}
            return {"workflow_runs": [{"head_sha": sha} for sha in self.web_success]}
        if path.endswith("/artifacts"):
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"artifacts": self.artifacts.get(run_id, [])}
        if path.endswith("/commits/main"):
            return {"sha": HEAD}
        raise AssertionError(path)


class FakeRunner:
    """Answers the git and docker commands the engine issues."""

    def __init__(self, head: str = HEAD, tags: list[str] | None = None) -> None:
        self.head = head
        self.tags = list(tags or [])
        self.ancestors: set[tuple[str, str]] = set()
        self.web_image = ""
        self.image_marker: dict[str, str] = {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        self.calls.append(argv)
        out, code = "", 0
        if argv[:2] == ["git", "init"] or "fetch" in argv:
            pass
        elif "for-each-ref" in argv:
            out = "\n".join(self.tags)
            if out:
                out += "\n"
        elif "rev-parse" in argv:
            out = self.head + "\n"
        elif "merge-base" in argv:
            older, newer = argv[-2], argv[-1]
            code = 0 if older == newer or (older, newer) in self.ancestors else 1
        elif argv[:2] == ["systemctl", "show"]:
            code = 1
        elif argv[:2] == ["docker", "inspect"]:
            out, code = (self.web_image, 0) if self.web_image else ("", 1)
        elif argv[:2] == ["docker", "run"]:
            image = argv[argv.index("cat") + 1]
            out = self.image_marker.get(image, "")
            code = 0 if out else 1
        else:
            raise AssertionError(f"unexpected command {argv}")
        if kwargs.get("check", True) and code:
            raise MODULE.ReleaseError(f"{argv[0]} failed")
        return subprocess.CompletedProcess(argv, code, out, "")


def make_engine(tmp_path: Path, github: FakeGitHub | None = None, runner: FakeRunner | None = None):
    paths = MODULE.Paths(
        state=tmp_path / "state",
        logs=tmp_path / "logs",
        store=tmp_path / "store",
        config=tmp_path / "config",
        application=tmp_path / "application",
        stage_root=tmp_path,
        lock=tmp_path / "lock",
        foundation=tmp_path / "foundation",
        backup_tool=tmp_path / "libexec" / "ac-postgres-backup.py",
        sales_xray=tmp_path / "sales-xray",
    )
    for directory in (paths.state, paths.config, paths.application):
        directory.mkdir(parents=True)
    (paths.state / "mirror.git").mkdir()
    (paths.state / "mirror.git" / "HEAD").write_text("ref: refs/heads/main\n")
    return MODULE.Engine(
        paths=paths,
        github=github or FakeGitHub(),
        run=runner or FakeRunner(),
        sleep=lambda _: None,
    )


def set_current_core(engine, sha: str) -> None:
    release = engine.paths.application / "releases" / sha
    release.mkdir(parents=True)
    (engine.paths.application / "current-staging").symlink_to(release)


# -- discovery ---------------------------------------------------------------


def test_only_successful_push_runs_on_main_for_this_repo_count() -> None:
    github = FakeGitHub()
    github.runs[(MODULE.CORE_WORKFLOW, HEAD)] = [
        run(HEAD, id=1, run_number=1, head_branch="task/x"),
        run(HEAD, id=2, run_number=2, event="workflow_dispatch"),
        run(HEAD, id=3, run_number=3, repository={"full_name": "fork/repo"}),
        run(HEAD, id=4, run_number=4, path=".github/workflows/other.yml"),
        run(HEAD, id=5, run_number=5),
    ]
    assert MODULE.find_push_run(github, MODULE.CORE_WORKFLOW, HEAD)["id"] == 5


@pytest.mark.parametrize(
    ("runs", "artifacts", "state"),
    [
        ([], [], "missing"),
        ([run(HEAD, status="in_progress", conclusion=None)], [], "building"),
        ([run(HEAD, conclusion="failure")], [], "failed"),
        ([run(HEAD, conclusion="cancelled")], [], "failed"),
        ([run(HEAD)], [], "failed"),
        ([run(HEAD)], [artifact(HEAD, f"ac-application-{HEAD}")], "ready"),
    ],
)
def test_core_candidate_states(runs, artifacts, state) -> None:
    github = FakeGitHub()
    github.runs[(MODULE.CORE_WORKFLOW, HEAD)] = runs
    github.artifacts[100] = artifacts
    candidate = MODULE.core_candidate(github, HEAD)
    assert candidate.state == state
    if state == "ready":
        assert candidate.build.artifact_digest == DIGEST


@pytest.mark.parametrize(
    "bad",
    [
        {"expired": True},
        {"digest": "sha1:abc"},
        {"digest": None},
        {"size_in_bytes": 0},
        {"size_in_bytes": MODULE.MAX_ARTIFACT_BYTES + 1},
        {"workflow_run": {"id": 999, "head_sha": HEAD}},
        {"workflow_run": {"id": 100, "head_sha": OLD}},
    ],
)
def test_untrustworthy_artifacts_are_ignored(bad) -> None:
    github = FakeGitHub()
    github.artifacts[100] = [artifact(HEAD, f"ac-application-{HEAD}", **bad)]
    assert MODULE.find_artifact(github, run(HEAD), f"ac-application-{HEAD}", HEAD) is None


def test_artifacts_with_another_name_are_ignored() -> None:
    github = FakeGitHub()
    github.artifacts[100] = [artifact(HEAD, "ac-application-other")]
    assert MODULE.find_artifact(github, run(HEAD), f"ac-application-{HEAD}", HEAD) is None


def test_duplicate_artifacts_are_ambiguous() -> None:
    github = FakeGitHub()
    name = f"ac-application-{HEAD}"
    github.artifacts[100] = [artifact(HEAD, name), artifact(HEAD, name, id=8)]
    assert MODULE.find_artifact(github, run(HEAD), name, HEAD) is None


# -- download and extraction --------------------------------------------------


def bundle_zip(
    path: Path, files: dict[str, bytes], *, checksums: dict[str, str] | None = None
) -> Path:
    sums = checksums or {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr(
            "SHA256SUMS", "".join(f"{digest}  {name}\n" for name, digest in sums.items())
        )
    return path


CORE = {"application-images.tar.gz": b"images", "release-images.env": b"AC_RELEASE_ID=x\n"}


def test_exact_bundle_extracts_and_verifies(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    MODULE.extract_exact(bundle_zip(tmp_path / "a.zip", CORE), out, MODULE.CORE_FILES)
    assert sorted(p.name for p in out.iterdir()) == sorted(MODULE.CORE_FILES)


def test_extra_or_unsafe_members_are_refused(tmp_path: Path) -> None:
    for extra in ("unexpected.txt", "../escape", "dir/file"):
        out = tmp_path / extra.replace("/", "_").replace(".", "_")
        out.mkdir()
        files = dict(CORE, **{extra: b"x"})
        with pytest.raises(MODULE.ReleaseError):
            MODULE.extract_exact(bundle_zip(out / "z.zip", files), out, MODULE.CORE_FILES)


def test_checksum_mismatch_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    wrong = {name: "0" * 64 for name in CORE}
    with pytest.raises(MODULE.ReleaseError, match="checksum failed"):
        MODULE.extract_exact(
            bundle_zip(tmp_path / "a.zip", CORE, checksums=wrong), out, MODULE.CORE_FILES
        )


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.requests: list[Any] = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.handler(request)


def test_token_is_never_sent_to_the_storage_redirect(tmp_path: Path) -> None:
    payload = b"zip-bytes"
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    github = MODULE.GitHub("secret-token")

    def api(request):
        error = urllib.error.HTTPError(request.full_url, 302, "Found", {}, None)
        error.headers = {"Location": "https://storage.example/blob?sig=1"}
        raise error

    github._api = Opener(api)
    github._plain = Opener(lambda request: Response(payload))
    github.download_artifact(7, tmp_path / "a.zip", digest)
    assert github._api.requests[0].get_header("Authorization") == "Bearer secret-token"
    storage_request = github._plain.requests[0]
    assert storage_request.full_url.startswith("https://storage.example/")
    assert storage_request.get_header("Authorization") is None
    assert (tmp_path / "a.zip").read_bytes() == payload


def test_digest_mismatch_and_plain_http_redirects_are_refused(tmp_path: Path) -> None:
    github = MODULE.GitHub("secret-token")
    github._api = Opener(lambda request: Response(b"other"))
    with pytest.raises(MODULE.ReleaseError, match="digest"):
        github.download_artifact(7, tmp_path / "a.zip", DIGEST)

    def insecure(request):
        error = urllib.error.HTTPError(request.full_url, 302, "Found", {}, None)
        error.headers = {"Location": "http://storage.example/blob"}
        raise error

    github._api = Opener(insecure)
    with pytest.raises(MODULE.ReleaseError, match="HTTPS"):
        github.download_artifact(7, tmp_path / "b.zip", DIGEST)


# -- automatic staging --------------------------------------------------------


def ready_core(github: FakeGitHub, sha: str) -> None:
    github.runs[(MODULE.CORE_WORKFLOW, sha)] = [run(sha)]
    github.artifacts[100] = [artifact(sha, f"ac-application-{sha}")]


def test_paused_staging_does_nothing(tmp_path: Path) -> None:
    runner = FakeRunner()
    engine = make_engine(tmp_path, runner=runner)
    engine.set_paused("staging", True, "test")
    assert engine.tick() == []
    assert runner.calls == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_current_staging_is_left_alone(tmp_path: Path) -> None:
    github = FakeGitHub()
    ready_core(github, HEAD)
    engine = make_engine(tmp_path, github)
    set_current_core(engine, HEAD)
    engine.deploy_core = lambda *a, **k: pytest.fail("must not redeploy")
    assert engine.tick() == []


def test_new_main_build_is_deployed_and_recorded(tmp_path: Path) -> None:
    github = FakeGitHub()
    ready_core(github, HEAD)
    engine = make_engine(tmp_path, github)
    deployed: list[str] = []
    engine.deploy_core = lambda env, build, dry_run: (
        deployed.append(build.sha) or {"previous": None}
    )
    results = engine.tick()
    assert deployed == [HEAD]
    assert results[0]["result"] == "success"
    assert engine.history()[-1]["sha"] == HEAD
    assert engine.passed_staging(HEAD)


def test_a_failed_core_deploy_pauses_staging_and_is_not_retried(tmp_path: Path) -> None:
    github = FakeGitHub()
    ready_core(github, HEAD)
    engine = make_engine(tmp_path, github)

    def fail(*args, **kwargs):
        raise MODULE.ReleaseError("installer exited with 1")

    engine.deploy_core = fail
    results = engine.tick()
    assert results[0]["result"] == "failed"
    assert engine.is_paused("staging")
    assert engine.failed_sha("staging", "core") == HEAD
    assert not engine.passed_staging(HEAD)
    assert engine.tick() == []
    engine.set_paused("staging", False)
    assert engine.failed_sha("staging", "core") is None


def test_builds_still_running_are_waited_for(tmp_path: Path) -> None:
    github = FakeGitHub()
    github.runs[(MODULE.CORE_WORKFLOW, HEAD)] = [run(HEAD, status="in_progress", conclusion=None)]
    engine = make_engine(tmp_path, github)
    engine.deploy_core = lambda *a, **k: pytest.fail("must wait")
    assert engine.tick() == []
    assert not engine.is_paused("staging")


def web_setup(tmp_path: Path, current_web_sha: str | None):
    github = FakeGitHub()
    ready_core(github, HEAD)
    github.web_success = [HEAD]
    github.runs[(MODULE.WEB_WORKFLOW, HEAD)] = [run(HEAD, MODULE.WEB_WORKFLOW, id=200)]
    github.artifacts[200] = [artifact(HEAD, f"ac-sales-xray-web-{HEAD}", run_id=200)]
    runner = FakeRunner()
    if current_web_sha:
        runner.web_image = "sha256:" + "e" * 64
        runner.image_marker[runner.web_image] = current_web_sha
    engine = make_engine(tmp_path, github, runner)
    engine.deploy_core = lambda *a, **k: {"previous": None}
    web: list[str] = []
    engine.deploy_web = lambda env, build, dry_run: web.append(build.sha) or {"previous": None}
    return engine, runner, web


def test_newer_web_build_is_deployed(tmp_path: Path) -> None:
    engine, runner, web = web_setup(tmp_path, OLD)
    runner.ancestors.add((OLD, HEAD))
    engine.tick()
    assert web == [HEAD]


def test_web_running_outside_main_history_counts_as_outdated(tmp_path: Path) -> None:
    engine, _, web = web_setup(tmp_path, OUTSIDE)
    engine.tick()
    assert web == [HEAD]


def test_web_build_older_than_the_running_image_is_skipped(tmp_path: Path) -> None:
    engine, runner, web = web_setup(tmp_path, OUTSIDE)
    runner.ancestors.add((HEAD, OUTSIDE))
    engine.tick()
    assert web == []


def test_web_release_marker_is_read_once_per_image(tmp_path: Path) -> None:
    engine, runner, _ = web_setup(tmp_path, OLD)
    engine.current_web("staging")
    engine.current_web("staging")
    assert sum(1 for call in runner.calls if call[:2] == ["docker", "run"]) == 1


# -- production gate ------------------------------------------------------------


def test_production_needs_enablement_and_a_staging_pass(tmp_path: Path) -> None:
    github = FakeGitHub()
    ready_core(github, HEAD)
    engine = make_engine(tmp_path, github)
    deployed: list[str] = []
    engine.deploy_core = lambda env, build, dry_run: deployed.append(env) or {}
    with pytest.raises(MODULE.ReleaseError, match="not enabled"):
        engine.deploy("production", HEAD, "core", dry_run=False)
    engine.paths.production_enabled.write_text("yes\n")
    with pytest.raises(MODULE.ReleaseError, match="not passed staging"):
        engine.deploy("production", HEAD, "core", dry_run=False)
    engine.record({"environment": "staging", "component": "core", "sha": HEAD, "result": "success"})
    engine.deploy("production", HEAD, "core", dry_run=False)
    assert deployed == ["production"]


def test_only_commits_on_main_can_be_deployed(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with pytest.raises(MODULE.ReleaseError, match="only commits on main"):
        engine.deploy("staging", OUTSIDE, "core", dry_run=True)


def test_status_reports_pause_and_failures(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    engine.set_paused("staging", True, "test")
    engine.paths.failed_flag("staging", "web").write_text(HEAD + "\n")
    report = engine.status()
    staging = report["environments"]["staging"]
    assert staging["paused"] is True and staging["auto_deploy"] is False
    assert staging["failed"] == {"core": None, "web": HEAD}
    assert json.loads(json.dumps(report))


def release_event(
    version: str,
    core_sha: str = HEAD,
    web_sha: str = OLD,
    *,
    action: str = "promote",
    rolled_back_from: str | None = None,
) -> dict[str, Any]:
    return {
        "version": version,
        "core_sha": core_sha,
        "web_sha": web_sha,
        "requested_by": "release-operator@example.invalid",
        "at": "2026-09-29T00:00:00Z",
        "action": action,
        "rolled_back_from": rolled_back_from,
    }


def promotion_setup(
    tmp_path: Path, *, production_core: str | None = OLD, production_web: str | None = OUTSIDE
):
    runner = FakeRunner()
    if production_core is not None:
        runner.ancestors.add((production_core, HEAD))
    engine = make_engine(tmp_path, runner=runner)
    engine.paths.production_enabled.write_text("enabled\n")
    core = {"staging": HEAD, "production": production_core}
    web = {"staging": HEAD, "production": production_web}
    engine.current_core = lambda environment: core[environment]
    engine.current_web = lambda environment: (web[environment], "sha256:" + "e" * 64)
    for component in MODULE.COMPONENTS:
        provenance = engine.paths.store / HEAD / f"{component}.provenance.json"
        provenance.parent.mkdir(parents=True, exist_ok=True)
        provenance.write_text(
            json.dumps(
                {
                    "run_id": 100,
                    "artifact_id": 7,
                    "artifact_name": f"{component}-{HEAD}",
                    "artifact_digest": DIGEST,
                }
            )
        )
        engine.record(
            {"environment": "staging", "component": component, "sha": HEAD, "result": "success"}
        )
    return engine, runner, core, web


@pytest.mark.parametrize(
    ("guard", "message"),
    [
        ("disabled", "not enabled"),
        ("incomplete_core", "complete core and web pair"),
        ("incomplete_web", "complete core and web pair"),
        ("core_not_main", "must be on main"),
        ("web_not_main", "must be on main"),
        ("core_not_staged", "successful staging deploy"),
        ("web_not_staged", "successful staging deploy"),
        ("staging_failed", "failed deploy"),
        ("core_build_missing", "stored builds"),
        ("web_build_missing", "stored builds"),
        ("not_forward", "not an ancestor"),
        ("already_pair", "already runs"),
        ("wrong_version", "next version"),
        ("stale_sha", "changed since"),
    ],
)
def test_promote_refuses_every_guard_without_attempt_or_release(
    tmp_path: Path, guard: str, message: str
) -> None:
    engine, _, core, web = promotion_setup(tmp_path)
    attempts: list[tuple[str, str]] = []
    engine.attempt = lambda environment, component, build, **kwargs: (
        attempts.append((environment, component)) or {"result": "success"}
    )
    expected_sha = None
    version = "v0.2.1"
    if guard == "disabled":
        engine.paths.production_enabled.unlink()
    elif guard == "incomplete_core":
        core["staging"] = None
    elif guard == "incomplete_web":
        web["staging"] = None
    elif guard == "core_not_main":
        core["staging"] = OUTSIDE
    elif guard == "web_not_main":
        web["staging"] = OUTSIDE
    elif guard in ("core_not_staged", "web_not_staged"):
        component = "core" if guard == "core_not_staged" else "web"
        records = [entry for entry in engine.history() if entry["component"] != component]
        engine.paths.history.write_text("".join(json.dumps(entry) + "\n" for entry in records))
    elif guard == "staging_failed":
        engine.paths.failed_flag("staging", "web").write_text(HEAD + "\n")
    elif guard in ("core_build_missing", "web_build_missing"):
        component = "core" if guard == "core_build_missing" else "web"
        (engine.paths.store / HEAD / f"{component}.provenance.json").unlink()
    elif guard == "not_forward":
        core["production"] = OUTSIDE
    elif guard == "already_pair":
        core["production"] = web["production"] = HEAD
    elif guard == "wrong_version":
        version = "v0.2.2"
    elif guard == "stale_sha":
        expected_sha = OUTSIDE

    with pytest.raises(MODULE.ReleaseError, match=message):
        engine.promote(
            "patch", version, requested_by="test", trigger="test", expected_sha=expected_sha
        )
    assert attempts == []
    assert engine.release_records() == []


def test_promote_deploys_core_then_web_and_records_the_typed_release(tmp_path: Path) -> None:
    engine, _, _, _ = promotion_setup(tmp_path)
    attempts: list[tuple[str, str, str, bool, str]] = []

    def attempt(environment, component, build, *, dry_run, trigger):
        attempts.append((environment, component, build.sha, dry_run, trigger))
        return {"result": "success", "component": component}

    engine.attempt = attempt
    result = engine.promote(
        "patch",
        "v0.2.1",
        requested_by="cli:operator",
        trigger="cli",
        expected_sha=engine.current_core("production"),
    )
    assert [entry["component"] for entry in result] == ["core", "web"]
    assert attempts == [
        ("production", "core", HEAD, False, "cli"),
        ("production", "web", HEAD, False, "cli"),
    ]
    record, previous = engine.production_releases()
    assert previous is None
    assert {
        key: record[key]
        for key in (
            "version",
            "core_sha",
            "web_sha",
            "requested_by",
            "action",
            "rolled_back_from",
        )
    } == {
        "version": "v0.2.1",
        "core_sha": HEAD,
        "web_sha": HEAD,
        "requested_by": "cli:operator",
        "action": "promote",
        "rolled_back_from": None,
    }
    assert record["at"]


def test_promote_retry_skips_core_when_production_already_runs_it(tmp_path: Path) -> None:
    engine, _, _, _ = promotion_setup(tmp_path, production_core=HEAD)
    attempts: list[str] = []
    engine.attempt = lambda environment, component, build, **kwargs: (
        attempts.append(component) or {"result": "success"}
    )
    result = engine.promote("patch", "v0.2.1", requested_by="test", trigger="test")
    assert [entry["result"] for entry in result] == ["success"]
    assert attempts == ["web"]
    assert engine.production_releases()[0]["version"] == "v0.2.1"


def test_failed_web_attempt_does_not_append_a_release(tmp_path: Path) -> None:
    engine, _, _, _ = promotion_setup(tmp_path)
    attempts: list[str] = []

    def attempt(environment, component, build, **kwargs):
        attempts.append(component)
        return {"result": "failed" if component == "web" else "success"}

    engine.attempt = attempt
    result = engine.promote("patch", "v0.2.1", requested_by="test", trigger="test")
    assert [entry["result"] for entry in result] == ["success", "failed"]
    assert attempts == ["core", "web"]
    assert engine.release_records() == []


def test_release_record_action_rules_and_rollback_parent(tmp_path: Path) -> None:
    with pytest.raises(MODULE.ReleaseError, match="promoted release cannot"):
        MODULE._validate_release_record(release_event("v0.3.0", rolled_back_from="v0.2.0"))
    with pytest.raises(MODULE.ReleaseError, match="rollback release must"):
        MODULE._validate_release_record(release_event("v0.3.0", action="rollback"))

    engine = make_engine(tmp_path)
    engine.append_release(release_event("v0.3.0"))
    with pytest.raises(MODULE.ReleaseError, match="current production version"):
        engine.append_release(release_event("v0.2.0", action="rollback", rolled_back_from="v0.2.9"))


@pytest.mark.parametrize(
    ("tags", "bump", "expected"),
    [
        ([], "minor", "v0.3.0"),
        (["v0.9.1"], "minor", "v0.10.0"),
        ([], "major", "v1.0.0"),
        (["nightly", "v1.2", "v2.3.4-rc1"], "minor", "v0.3.0"),
    ],
)
def test_next_version_uses_highest_semantic_tag_or_baseline(
    tmp_path: Path, tags: list[str], bump: str, expected: str
) -> None:
    runner = FakeRunner(tags=tags)
    engine = make_engine(tmp_path, runner=runner)
    assert engine.next_version(bump) == expected
    fetch = next(call for call in runner.calls if "fetch" in call)
    assert "+refs/tags/v*:refs/tags/v*" in fetch


def test_next_version_uses_release_record_above_every_tag(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, runner=FakeRunner(tags=["v1.5.0", "v1.3.9", "nightly"]))
    engine.append_release(release_event("v1.8.2"))
    assert engine.next_version("minor") == "v1.9.0"


def test_release_records_append_and_reader_returns_current_and_previous(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path)
    first = release_event("v0.3.0", HEAD, OLD)
    engine.append_release(first)
    first_line = engine.paths.releases.read_text(encoding="utf-8").splitlines()[0]

    second = release_event("v0.4.0", OLD, OUTSIDE)
    rollback = release_event("v0.3.0", HEAD, OLD, action="rollback", rolled_back_from="v0.4.0")
    engine.append_release(second)
    engine.append_release(rollback)

    lines = engine.paths.releases.read_text(encoding="utf-8").splitlines()
    current, previous = engine.production_releases()
    assert len(lines) == 3
    assert lines[0] == first_line
    assert current == rollback
    assert previous == second


def test_store_keeps_previous_production_builds_after_ten_newer_staging_builds(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path)
    previous_core = release_sha("production-previous-core")
    previous_web = release_sha("production-previous-web")
    current_core = release_sha("production-current-core")
    current_web = release_sha("production-current-web")
    staging_shas = [release_sha(f"staging-{index}") for index in range(12)]

    for sha in (previous_core, previous_web, current_core, current_web, *staging_shas):
        (engine.paths.store / sha / "core").mkdir(parents=True)
    engine.append_release(release_event("v0.3.0", previous_core, previous_web))
    engine.append_release(release_event("v0.4.0", current_core, current_web))
    for sha in staging_shas:
        engine.record(
            {"environment": "staging", "component": "core", "sha": sha, "result": "success"}
        )

    engine.prune_store()
    remaining = {path.name for path in engine.paths.store.iterdir()}
    assert {previous_core, previous_web, current_core, current_web} <= remaining
    assert set(staging_shas[-10:]) <= remaining
    assert not set(staging_shas[:-10]) & remaining


def test_successful_staging_attempt_keeps_store_when_release_ledger_is_truncated(
    tmp_path: Path,
) -> None:
    engine = make_engine(tmp_path)
    store_shas = [f"{index:040x}" for index in range(12)]
    for sha in store_shas:
        (engine.paths.store / sha / "core").mkdir(parents=True)
    engine.paths.releases.write_text('{"version":"v0.3.0"', encoding="utf-8")
    engine.deploy_core = lambda environment, build, dry_run: {"previous": None}

    result = engine.attempt(
        "staging",
        "core",
        MODULE.Build(HEAD, 100, 7, f"ac-application-{HEAD}", DIGEST),
        dry_run=False,
        trigger="test",
    )

    assert result["result"] == "success"
    assert result["pruned"] == []
    assert {path.name for path in engine.paths.store.iterdir()} == set(store_shas)


def test_store_keeps_running_and_recent_builds_only(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    shas = [f"{i:040x}" for i in range(15)]
    for sha in shas:
        bundle = engine.paths.store / sha / "core"
        bundle.mkdir(parents=True)
        (bundle / "application-images.tar.gz").write_bytes(b"x")
        (bundle / "application-images.tar.gz").chmod(0o400)
        bundle.chmod(0o500)
    for sha in shas[3:]:
        engine.record(
            {"environment": "staging", "component": "core", "sha": sha, "result": "success"}
        )
    engine.record(
        {"environment": "staging", "component": "core", "sha": shas[0], "result": "failed"}
    )
    engine.current_core = lambda environment: shas[1] if environment == "production" else None
    removed = engine.prune_store()
    kept = sorted(p.name for p in engine.paths.store.iterdir())
    assert kept == sorted([shas[1], *shas[5:]])
    assert sorted(removed) == sorted([shas[0], shas[2], shas[3], shas[4]])


def foundation_backup_tool(engine, *heads: str) -> None:
    engine.paths.backup_tool.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'HEAD_{i} = "{head}"' for i, head in enumerate(heads)]
    engine.paths.backup_tool.write_text("".join(f"{line}\n" for line in lines))


def bundle_with_head(tmp_path: Path, head: str) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "release-images.env").write_text(f"AC_RELEASE_ID=x\nAC_MIGRATION_HEAD={head}\n")
    return bundle


def test_known_migration_head_is_accepted(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    foundation_backup_tool(engine, "20261002_0067", "20261003_0069")
    engine.require_backup_support(bundle_with_head(tmp_path, "20261003_0069"))


@pytest.mark.parametrize("installed", [("20260924_0048",), ()])
def test_unknown_migration_head_is_refused_before_install(tmp_path: Path, installed) -> None:
    engine = make_engine(tmp_path)
    if installed:
        foundation_backup_tool(engine, *installed)
    with pytest.raises(MODULE.ReleaseError, match="do not recognise migration 20261003_0069"):
        engine.require_backup_support(bundle_with_head(tmp_path, "20261003_0069"))


def test_bundle_without_migration_head_is_refused(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    foundation_backup_tool(engine, "20261003_0069")
    with pytest.raises(MODULE.ReleaseError, match="no valid AC_MIGRATION_HEAD"):
        engine.require_backup_support(bundle_with_head(tmp_path, "latest"))


# -- installer artifact retention -----------------------------------------------

REGISTRY = "ghcr.io/authorityclosers"
NOW = 1_800_000_000


def release_sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:40]


def image_id(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def core_artifact(engine, sha: str, *, age_hours: int) -> Path:
    path = engine.paths.application / "artifacts" / sha
    path.mkdir(parents=True)
    (path / "application-images.tar.gz").write_bytes(b"x" * 1000)
    (path / "release-images.env").write_text(f"AC_RELEASE_ID={sha}\n")
    stamp = NOW - age_hours * 3600
    os.utime(path, (stamp, stamp))
    return path


def deployment_record(
    engine, environment: str, stamp: str, sha: str, status: str, previous: str = "", kind: str = ""
) -> None:
    root = engine.paths.application / "deployments" / environment
    root.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}-{sha}{'-' + kind if kind else ''}-AbC123.env"
    (root / name).write_text(
        f"AC_STATUS={status}\nAC_ENVIRONMENT={environment}\n"
        f"AC_RELEASE_ID={sha}\nAC_PREVIOUS_RELEASE={previous}\n"
    )


def link_current(engine, environment: str, sha: str) -> None:
    release = engine.paths.application / "releases" / sha
    release.mkdir(parents=True, exist_ok=True)
    try:
        (engine.paths.application / f"current-{environment}").symlink_to(release, True)
    except OSError as exc:
        pytest.skip(f"fixture symlinks are unavailable: {exc}")


class DockerImages:
    """Answers the docker listing and removal commands retention issues."""

    def __init__(self, images: dict[str, list[str]], used: list[str]) -> None:
        self.images = images
        self.used = used
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["docker", "image", "ls"]:
            rows = []
            for image, references in self.images.items():
                for reference in references or ["<none>:<none>"]:
                    repository, tag = reference.rsplit(":", 1)
                    rows.append(f"{image}\t{repository}\t{tag}\t1.5GB\n")
            out = "".join(rows)
        elif argv[:3] == ["docker", "container", "ls"]:
            out = "".join(f"{index:064x}\n" for index in range(len(self.used)))
        elif argv[:3] == ["docker", "container", "inspect"]:
            out = "".join(f"{image}\n" for image in self.used)
        elif argv[:3] == ["docker", "image", "rm"]:
            out = ""
        else:
            raise AssertionError(f"unexpected command {argv}")
        return subprocess.CompletedProcess(argv, 0, out, "")

    def removed(self) -> list[str]:
        return [call[3] for call in self.calls if call[:3] == ["docker", "image", "rm"]]


RUNNING_STAGING = release_sha("running-staging")
STAGING_ROLLBACK = release_sha("staging-rollback")
UNFINISHED = release_sha("unfinished")
FORWARD = release_sha("forward-recovery")
RUNNING_PRODUCTION = release_sha("running-production")
PRODUCTION_ROLLBACK = release_sha("production-rollback")
REFERENCED = release_sha("operator-input")
NEWEST = release_sha("newest")
OLD_COMMITTED = release_sha("old-committed")
OLD = release_sha("old")


def retention_fixture(tmp_path: Path, runner=None):
    """Ten installed releases; only OLD and OLD_COMMITTED are unneeded at N=1."""

    engine = make_engine(tmp_path, runner=runner)
    app = engine.paths.application
    ages = {
        NEWEST: 1,
        UNFINISHED: 2,
        FORWARD: 3,
        RUNNING_STAGING: 4,
        STAGING_ROLLBACK: 30,
        REFERENCED: 40,
        RUNNING_PRODUCTION: 50,
        PRODUCTION_ROLLBACK: 60,
        OLD_COMMITTED: 70,
        OLD: 80,
    }
    for sha, age in ages.items():
        core_artifact(engine, sha, age_hours=age)
    link_current(engine, "staging", RUNNING_STAGING)
    link_current(engine, "production", RUNNING_PRODUCTION)
    staging = [
        ("20260920T010000Z", OLD_COMMITTED, "COMMITTED", "", ""),
        ("20260921T010000Z", STAGING_ROLLBACK, "COMMITTED", OLD_COMMITTED, ""),
        ("20260926T010000Z", RUNNING_STAGING, "PREPARED_BEFORE_WRITE_EXPOSURE", "", "prepared"),
        ("20260926T010100Z", RUNNING_STAGING, "COMMITTED", STAGING_ROLLBACK, ""),
        ("20260927T010000Z", FORWARD, "FORWARD_RECOVERY_REQUIRED", "", "forward-recovery"),
    ]
    for stamp, sha, status, previous, kind in staging:
        deployment_record(engine, "staging", stamp, sha, status, previous, kind)
    (app / "deployments" / "staging" / f".prepared-{UNFINISHED}.Xy12Ab").write_text("")
    deployment_record(engine, "production", "20260920T020000Z", PRODUCTION_ROLLBACK, "COMMITTED")
    deployment_record(
        engine,
        "production",
        "20260923T020000Z",
        RUNNING_PRODUCTION,
        "COMMITTED",
        PRODUCTION_ROLLBACK,
    )
    intent = app / "operator-inputs" / "production" / "prepare-only" / "install.intent.json"
    intent.parent.mkdir(parents=True)
    bundle = f"/srv/authority-closers/application/artifacts/{REFERENCED}"
    intent.write_text(json.dumps({"bundle": bundle}))
    for name in (f"sales-xray-native-{OLD}", f"sales-xray-web-{OLD}", f".stage-{OLD}.QwErTy"):
        (app / "artifacts" / name).mkdir()
        (app / "artifacts" / name / "payload").write_bytes(b"y" * 500)
    return engine


def test_retention_keeps_running_rollback_recovery_referenced_and_newest(tmp_path: Path) -> None:
    engine = retention_fixture(tmp_path)
    report = engine.prune_artifacts(1, images=False)
    decisions = {entry["sha"]: entry["keep"] for entry in report["artifacts"]}
    unneeded = sorted(sha for sha, reasons in decisions.items() if not reasons)
    assert unneeded == sorted([OLD_COMMITTED, OLD])
    assert decisions[RUNNING_STAGING][:2] == ["running in staging", "last committed to staging"]
    assert "staging rollback target" in decisions[STAGING_ROLLBACK]
    assert decisions[FORWARD] == ["staging forward recovery (reapply this release)"]
    assert decisions[UNFINISHED] == ["unfinished staging record"]
    assert decisions[PRODUCTION_ROLLBACK] == ["production rollback target"]
    assert decisions[REFERENCED] == [
        "named in operator-inputs/production/prepare-only/install.intent.json"
    ]
    assert decisions[NEWEST] == ["one of the 1 newest"]
    assert report["artifacts"][0]["sha"] == NEWEST
    assert sorted(entry["name"] for entry in report["unmanaged"]) == sorted(
        [f".stage-{OLD}.QwErTy", f"sales-xray-native-{OLD}", f"sales-xray-web-{OLD}"]
    )
    assert report["applied"] is False
    assert (engine.paths.application / "artifacts" / OLD).is_dir()
    assert not engine.paths.history.exists()


def test_keep_recent_widens_the_kept_set(tmp_path: Path) -> None:
    engine = retention_fixture(tmp_path)
    report = engine.prune_artifacts(10, images=False)
    assert all(entry["keep"] for entry in report["artifacts"])


def test_apply_removes_only_unretained_artifacts_and_core_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollback_api = image_id("api-rollback")
    docker = DockerImages(
        {
            image_id("api-running"): [f"{REGISTRY}/authority-closers-api:{RUNNING_STAGING}"],
            rollback_api: [f"{REGISTRY}/authority-closers-api:{STAGING_ROLLBACK}"],
            image_id("api-newest"): [f"{REGISTRY}/authority-closers-api:{NEWEST}"],
            image_id("api-old"): [f"{REGISTRY}/authority-closers-api:{OLD}"],
            image_id("learner-old"): [
                f"{REGISTRY}/authority-closers-learner-web:{OLD}",
                f"{REGISTRY}/authority-closers-learner-web:{OLD_COMMITTED}",
            ],
            # Never managed: native runs from systemd units, not containers.
            image_id("native"): [f"{REGISTRY}/ac-sales-xray-native:{OLD}"],
            image_id("web"): [f"{REGISTRY}/ac-sales-xray-web:{OLD}"],
            image_id("mixed"): [
                f"{REGISTRY}/authority-closers-api:{OLD_COMMITTED}",
                f"{REGISTRY}/ac-sales-xray-web:{OLD_COMMITTED}",
            ],
            image_id("caddy"): ["caddy:2-alpine"],
            image_id("dangling"): [],
            image_id("api-latest"): [f"{REGISTRY}/authority-closers-api:latest"],
        },
        used=[image_id("api-running"), image_id("caddy")],
    )
    engine = retention_fixture(tmp_path, runner=docker)
    app = engine.paths.application
    # The rollback image is kept by its release manifest, not only by its tag.
    (app / "releases" / STAGING_ROLLBACK).mkdir(parents=True)
    (app / "releases" / STAGING_ROLLBACK / "release-images.env").write_text(
        f"AC_API_IMAGE={rollback_api}\n"
    )
    leftover = app / "artifacts" / f".prune-{OLD}.0badf00d"
    leftover.mkdir()
    (leftover / "application-images.tar.gz").write_bytes(b"z")
    unneeded_bytes = sum(
        path.stat().st_size
        for sha in (OLD, OLD_COMMITTED)
        for path in (app / "artifacts" / sha).iterdir()
    )
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0, raising=False)

    report = engine.prune_artifacts(1, apply=True)

    assert report["errors"] == []
    remaining = {path.name for path in (app / "artifacts").iterdir()}
    assert OLD not in remaining and OLD_COMMITTED not in remaining
    assert not any(name.startswith(".prune-") for name in remaining)
    assert {RUNNING_STAGING, STAGING_ROLLBACK, REFERENCED, NEWEST} <= remaining
    assert {f"sales-xray-native-{OLD}", f".stage-{OLD}.QwErTy"} <= remaining
    assert sorted(docker.removed()) == sorted(
        [
            f"{REGISTRY}/authority-closers-api:{OLD}",
            f"{REGISTRY}/authority-closers-learner-web:{OLD}",
            f"{REGISTRY}/authority-closers-learner-web:{OLD_COMMITTED}",
        ]
    )
    assert not any("--force" in call or "-f" in call for call in docker.calls)
    kept = {image["id"]: image["keep"] for image in report["images"]}
    assert kept[image_id("api-running")][0] == "used by a container"
    assert kept[rollback_api] == [f"belongs to kept release {STAGING_ROLLBACK[:12]}"]
    assert kept[image_id("api-newest")] == [f"belongs to kept release {NEWEST[:12]}"]
    assert report["unmanaged_images"] == 6
    entry = engine.history()[-1]
    assert entry["action"] == "prune-artifacts"
    assert entry["removed"] == len(report["removed"]) == 5
    assert entry["freed_bytes"] == unneeded_bytes


@pytest.mark.skipif(MODULE.fcntl is None, reason="POSIX file locks are unavailable")
def test_apply_refuses_while_an_install_holds_the_deployment_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = retention_fixture(tmp_path)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 0, raising=False)
    with (engine.paths.application / ".deployment.lock").open("a") as held:
        MODULE.fcntl.flock(held, MODULE.fcntl.LOCK_EX)
        with pytest.raises(MODULE.ReleaseError, match="deployment is running"):
            engine.prune_artifacts(1, apply=True, images=False)
    assert (engine.paths.application / "artifacts" / OLD).is_dir()


def test_apply_requires_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = retention_fixture(tmp_path)
    monkeypatch.setattr(MODULE.os, "geteuid", lambda: 1000, raising=False)
    with pytest.raises(MODULE.ReleaseError, match="must run as root"):
        engine.prune_artifacts(1, apply=True, images=False)
    assert (engine.paths.application / "artifacts" / OLD).is_dir()


@pytest.mark.parametrize(
    "content",
    [
        f"AC_STATUS=COMMITTED\nAC_RELEASE_ID={OLD}\n",
        f"AC_STATUS=COMMITTED\nAC_RELEASE_ID={NEWEST}\nAC_PREVIOUS_RELEASE=not-a-sha\n",
        f"AC_RELEASE_ID={NEWEST}\n",
        "not an assignment\n",
    ],
)
def test_unreadable_deployment_evidence_stops_retention(tmp_path: Path, content: str) -> None:
    engine = retention_fixture(tmp_path)
    records = engine.paths.application / "deployments" / "staging"
    (records / f"20260928T000000Z-{NEWEST}-ZzZzZz.env").write_text(content)
    with pytest.raises(MODULE.ReleaseError):
        engine.prune_artifacts(0, images=False)


def test_current_link_outside_releases_is_refused(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    artifact_dir = core_artifact(engine, OLD, age_hours=1)
    try:
        (engine.paths.application / "current-staging").symlink_to(artifact_dir, True)
    except OSError as exc:
        pytest.skip(f"fixture symlinks are unavailable: {exc}")
    with pytest.raises(MODULE.ReleaseError, match="does not resolve to an installed release"):
        engine.prune_artifacts(0, images=False)


def test_prune_artifacts_command_is_a_dry_run_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = retention_fixture(tmp_path)
    monkeypatch.setattr(MODULE, "Paths", lambda: engine.paths)
    assert MODULE.main(["prune-artifacts", "--no-images", "--keep-recent", "1"]) == 0
    output = capsys.readouterr().out
    assert f"remove {OLD[:12]}" in output
    assert f"keep   {RUNNING_STAGING[:12]}" in output
    assert "Keep 8 (" in output and "remove 2 (" in output
    assert "sales-xray-native-* x1" in output
    assert "Dry run: nothing was removed" in output
    assert (engine.paths.application / "artifacts" / OLD).is_dir()
    assert MODULE.main(["prune-artifacts", "--dry-run", "--no-images", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    with pytest.raises(SystemExit):
        MODULE.main(["prune-artifacts", "--dry-run", "--apply"])


# -- Sales Xray activation ------------------------------------------------------

NATIVE = "e" * 40
NOW = 1_800_000_000
DAY = 86_400
IMAGE = "sha256:" + "f" * 64
NATIVE_ZIP = b"native build bytes"
NATIVE_DIGEST = "sha256:" + hashlib.sha256(NATIVE_ZIP).hexdigest()


class NativeGitHub(FakeGitHub):
    """Adds the native-image run, its artifact and the records a proof pins."""

    def __init__(self, *, expired: bool = False) -> None:
        super().__init__()
        self.runs[(MODULE.NATIVE_WORKFLOW, NATIVE)] = [run(NATIVE, MODULE.NATIVE_WORKFLOW, id=300)]
        self.record = artifact(
            NATIVE,
            f"ac-sales-xray-native-{NATIVE}",
            run_id=300,
            id=30,
            expired=expired,
            digest=NATIVE_DIGEST,
            size_in_bytes=len(NATIVE_ZIP),
        )
        self.artifacts[300] = [self.record]
        self.downloads = 0

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        if path.endswith("/actions/artifacts/30"):
            return self.record
        if path.endswith("/actions/runs/300"):
            return run(NATIVE, MODULE.NATIVE_WORKFLOW, id=300)
        return super().get_json(path, params)

    def download_artifact(self, artifact_id: int, destination: Path, expected_digest: str) -> None:
        assert (artifact_id, expected_digest) == (30, NATIVE_DIGEST)
        self.downloads += 1
        destination.write_bytes(NATIVE_ZIP)


class PrepareRunner(FakeRunner):
    """Stands in for the repository's prepare tool and for docker inspect."""

    def __init__(self, *, fail: str = "") -> None:
        super().__init__()
        self.fail = fail
        self.prepared: list[list[str]] = []
        self.inspections: list[str] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        if argv[0] == "python3" and argv[1].endswith("prepare-sales-xray-native-activation.py"):
            self.prepared.append(argv)
            if self.fail:
                return subprocess.CompletedProcess(argv, 2, "", f"FAIL  refused: {self.fail}\n")
            target = argv[argv.index("--target-release-id") + 1]
            output = Path(argv[argv.index("--output-dir") + 1])
            output.mkdir()
            descriptor = output / f"activation-{target}.json"
            descriptor.write_text(json.dumps({"release_id": target}) + "\n")
            (output / f"activation-{target}.json.sha256").write_text(
                hashlib.sha256(descriptor.read_bytes()).hexdigest() + "\n"
            )
            (output / f"service-{target}.json").write_text("{}\n")
            result = {"release_id": target, "provider_calls": 0, "approval_replaced": False}
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")
        if argv[:2] == ["docker", "inspect"] and self.inspections:
            return subprocess.CompletedProcess(argv, 0, self.inspections.pop(0) + "\n", "")
        return super().__call__(argv, **kwargs)


def hosted_setup(tmp_path: Path, *, expires_in: int = 90 * DAY, github=None, runner=None):
    """Staging runs OLD with a hosted activation on the NATIVE build's image."""

    engine = make_engine(tmp_path, github or NativeGitHub(), runner or PrepareRunner())
    engine.clock = lambda: NOW
    # Root test hosts seal ownership too; use a group that exists there.
    import grp

    engine.operator_group = grp.getgrgid(os.getgid()).gr_name
    set_current_core(engine, OLD)
    approval = tmp_path / "approval.json"
    approval.write_text(
        json.dumps(
            {
                "expires_at_epoch": NOW + expires_in + DAY,
                "acquisition_policy": {"expires_at_epoch": NOW + expires_in},
            }
        )
    )
    (engine.paths.sales_xray / "staging").mkdir(parents=True)
    engine.activation_path("staging", OLD).write_text(
        json.dumps({"approval_file": str(approval), "native_image_ref": IMAGE})
    )
    native = engine.paths.application / "artifacts" / f"sales-xray-native-{NATIVE}"
    native.mkdir(parents=True)
    (native / "native-image.json").write_text(
        json.dumps({"source_commit": NATIVE, "image": {"expected_runtime_ref": IMAGE}})
    )
    (engine.paths.application / "operator-inputs" / "staging").mkdir(parents=True)
    return engine


def prepare(engine, tmp_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    return engine.prepare_activation(
        "staging", HEAD, tmp_path / "source", stage, dry_run=dry_run, log=tmp_path / "log"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_activation_is_carried_forward_with_a_native_reuse_proof(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path)
    summary = prepare(engine, tmp_path)

    assert summary == {
        "sales_xray_activation": f"carried forward from {OLD[:12]}",
        "sales_xray_native": NATIVE,
        "sales_xray_approval_expires": MODULE._date(NOW + 90 * DAY),
    }
    argv = engine.run.prepared[0]
    assert argv[argv.index("--source-activation") + 1] == str(
        engine.activation_path("staging", OLD)
    )
    assert "--approval-file" not in argv  # the approval is carried forward unchanged
    assert argv[argv.index("--source-repository") + 1] == str(engine.paths.mirror)
    proof_path = Path(argv[argv.index("--native-reuse-proof") + 1])
    proof = json.loads(proof_path.read_text())
    stored = engine.paths.native_store / NATIVE
    assert proof["schema"] == "ac.sales-xray.native-reuse-input/1"
    assert (proof["native_source_commit"], proof["target_release_id"]) == (NATIVE, HEAD)
    assert proof["archive_path"] == str(stored / "native-artifact.zip")
    assert proof["workflow_run"]["sha256"] == MODULE._sha256_file(stored / "workflow-run.json")
    assert proof["artifact_metadata"]["path"] == str(stored / "artifact-metadata.json")
    assert argv[argv.index("--native-reuse-proof-sha256") + 1] == MODULE._sha256_file(proof_path)
    operator_inputs = engine.paths.application / "operator-inputs" / "staging"
    assert proof_path.parent.parent.parent == operator_inputs

    published = engine.activation_path("staging", HEAD)
    digest = published.with_name(published.name + ".sha256").read_text().strip()
    assert digest == MODULE._sha256_file(published)
    assert oct(published.stat().st_mode & 0o777) == "0o444"
    # A retry finds the published activation and prepares nothing new.
    assert prepare(engine, tmp_path) == {"sales_xray_activation": "present"}
    assert len(engine.run.prepared) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_dry_run_prepares_in_the_stage_and_publishes_nothing(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path)
    summary = prepare(engine, tmp_path, dry_run=True)
    assert summary["sales_xray_native"] == NATIVE
    argv = engine.run.prepared[0]
    assert Path(argv[argv.index("--output-dir") + 1]).is_relative_to(tmp_path / "stage")
    assert not engine.activation_path("staging", HEAD).exists()
    assert not list((engine.paths.application / "operator-inputs" / "staging").iterdir())


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_without_hosted_sales_xray_nothing_is_prepared(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path)
    engine.activation_path("staging", OLD).unlink()
    assert prepare(engine, tmp_path) == {}
    assert engine.run.prepared == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_an_approval_about_to_lapse_is_refused(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path, expires_in=3600)
    with pytest.raises(MODULE.ReleaseError, match="renew it before deploying"):
        prepare(engine, tmp_path)
    assert engine.run.prepared == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_changed_native_inputs_ask_for_the_new_native_build(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path, runner=PrepareRunner(fail="native_inputs_changed"))
    with pytest.raises(MODULE.ReleaseError, match="changes the Sales Xray native image"):
        prepare(engine, tmp_path)
    assert not engine.activation_path("staging", HEAD).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_the_running_native_image_must_be_loaded(tmp_path: Path) -> None:
    engine = hosted_setup(tmp_path)
    native = engine.paths.application / "artifacts" / f"sales-xray-native-{NATIVE}"
    (native / "native-image.json").write_text(json.dumps({"source_commit": NATIVE}))
    with pytest.raises(MODULE.ReleaseError, match="no single loaded native artifact"):
        prepare(engine, tmp_path)


def test_native_build_is_downloaded_once_and_kept(tmp_path: Path) -> None:
    github = NativeGitHub()
    engine = make_engine(tmp_path, github)
    stored = engine.store_native(NATIVE)
    assert (stored / "native-artifact.zip").read_bytes() == NATIVE_ZIP
    assert json.loads((stored / "artifact-metadata.json").read_text())["digest"] == NATIVE_DIGEST
    assert json.loads((stored / "workflow-run.json").read_text())["id"] == 300
    assert engine.store_native(NATIVE) == stored
    assert github.downloads == 1
    # Kept outside the per-commit bundles, so the store prune never removes it.
    assert engine.prune_store() == []
    assert stored.is_dir()


def test_a_saved_zip_is_adopted_only_when_it_matches_github(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, NativeGitHub(expired=True))
    wrong = tmp_path / "wrong.zip"
    wrong.write_bytes(b"something else")
    with pytest.raises(MODULE.ReleaseError, match="not the native build GitHub recorded"):
        engine.store_native(NATIVE, local_zip=wrong)
    with pytest.raises(MODULE.ReleaseError, match="store-native"):
        engine.store_native(NATIVE)
    saved = tmp_path / "saved.zip"
    saved.write_bytes(NATIVE_ZIP)
    stored = engine.store_native(NATIVE, local_zip=saved)
    assert (stored / "native-artifact.zip").read_bytes() == NATIVE_ZIP


def test_commits_without_a_native_build_store_nothing(tmp_path: Path) -> None:
    engine = make_engine(tmp_path, NativeGitHub())
    engine.keep_native_build(HEAD)
    assert not engine.paths.native_store.exists()
    engine.keep_native_build(NATIVE)
    assert (engine.paths.native_store / NATIVE / "native-artifact.zip").is_file()


def test_a_restarting_sales_xray_worker_fails_the_check(tmp_path: Path) -> None:
    runner = PrepareRunner()
    engine = make_engine(tmp_path, runner=runner)
    log = tmp_path / "log"
    runner.inspections = ["running|0|t1", "running|1|t2"]
    with pytest.raises(MODULE.ReleaseError, match="did not stay up"):
        engine.require_steady("worker", log)
    runner.inspections = ["running|0|t1", "running|0|t1"]
    engine.require_steady("worker", log)
    assert "STEADY worker" in log.read_text()


class EngineRunner(FakeRunner):
    """Answers tree lookups per commit and records the engine reinstall."""

    def __init__(self, trees: dict[str, str], install_code: int = 0) -> None:
        super().__init__()
        self.trees = trees
        self.install_code = install_code
        self.installs: list[list[str]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        if "rev-parse" in argv and argv[-1].endswith(":infra/release"):
            tree = self.trees.get(argv[-1].split(":")[0], "")
            return subprocess.CompletedProcess(argv, 0 if tree else 128, tree + "\n", "")
        if argv[:2] == ["git", "clone"] or (argv[0] == "git" and "checkout" in argv):
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "bash" and argv[1].endswith("install-release-engine.sh"):
            self.installs.append(argv)
            return subprocess.CompletedProcess(argv, self.install_code, "", "")
        return super().__call__(argv, **kwargs)


def engine_setup(tmp_path: Path, trees: dict[str, str], *, validated_head: bool = True, **kw):
    github = FakeGitHub()
    if validated_head:
        ready_core(github, HEAD)
    runner = EngineRunner(trees, **kw)
    engine = make_engine(tmp_path, github, runner)
    engine.paths = MODULE.Paths(**{**engine.paths.__dict__, "engine": tmp_path / "engine"})
    release = engine.paths.engine / "releases" / OLD
    release.mkdir(parents=True)
    (engine.paths.engine / "current").symlink_to(release)
    engine.deploy_core = lambda *a, **k: pytest.fail("an engine update ends the tick")
    return engine, runner


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_engine_updates_itself_when_validated_main_changes_it(tmp_path: Path) -> None:
    engine, runner = engine_setup(tmp_path, {OLD: "1" * 40, HEAD: "2" * 40})
    assert engine.installed_engine() == OLD
    results = engine.tick()
    assert [(r["action"], r["from"], r["to"], r["result"]) for r in results] == [
        ("engine-update", OLD, HEAD, "success")
    ]
    assert len(runner.installs) == 1
    assert engine.history()[-1]["action"] == "engine-update"


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_unchanged_engine_or_unvalidated_main_is_left_alone(tmp_path: Path) -> None:
    same, runner = engine_setup(tmp_path / "same", {OLD: "1" * 40, HEAD: "1" * 40})
    assert same.update_engine(HEAD) is None
    waiting, waiting_runner = engine_setup(
        tmp_path / "waiting", {OLD: "1" * 40, HEAD: "2" * 40}, validated_head=False
    )
    assert waiting.update_engine(HEAD) is None
    assert runner.installs == waiting_runner.installs == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_failed_engine_update_is_not_retried_for_the_same_commit(tmp_path: Path) -> None:
    engine, runner = engine_setup(tmp_path, {OLD: "1" * 40, HEAD: "2" * 40}, install_code=1)
    first = engine.update_engine(HEAD)
    assert first is not None and first["result"] == "failed"
    assert engine.update_engine(HEAD) is None
    assert len(runner.installs) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_status_shows_when_the_sales_xray_approval_lapses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = hosted_setup(tmp_path, expires_in=40 * DAY)
    staging = engine.status()["environments"]["staging"]
    assert staging["sales_xray_approval_expires"] == MODULE._date(NOW + 40 * DAY)
    assert staging["sales_xray_approval_days_left"] == 40
    MODULE._print(engine.status(), False)
    assert "Sales Xray approval until" in capsys.readouterr().out
