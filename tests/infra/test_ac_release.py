"""Behaviour of the staging release engine (infra/release/ac_release.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
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
        raise AssertionError(path)


class FakeRunner:
    """Answers the git and docker commands the engine issues."""

    def __init__(self, head: str = HEAD) -> None:
        self.head = head
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
        elif "rev-parse" in argv:
            out = self.head + "\n"
        elif "merge-base" in argv:
            older, newer = argv[-2], argv[-1]
            code = 0 if older == newer or (older, newer) in self.ancestors else 1
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
