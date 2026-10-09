"""Behaviour of the staging release engine (infra/release/ac_release.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
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
        elif "ls-tree" in argv:
            assert argv[-1] == MODULE.APPLICATION_SOURCE_MANIFEST
            # Existing delivery fixtures model releases before this opt-in.
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


@pytest.mark.parametrize("contract", ["current", "legacy", "missing", "unsupported"])
def test_core_source_archive_uses_target_revision_manifest(tmp_path: Path, contract: str) -> None:
    repository = tmp_path / "repository"
    application = repository / "infra/application"
    application.mkdir(parents=True)
    (application / "compose.yaml").write_text("inert fixture\n")
    canonical = MODULE.APPLICATION_SOURCE_EXTRAS[0]
    if contract != "missing":
        source = repository / canonical
        source.parent.mkdir(parents=True)
        source.write_bytes((ROOT / canonical).read_bytes())
    if contract != "legacy":
        (repository / MODULE.APPLICATION_SOURCE_MANIFEST).write_text(
            canonical + "\n" if contract != "unsupported" else "scripts/unapproved.py\n"
        )
    git = ["git", "-C", str(repository)]
    for arguments in [
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=AC Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "inert source fixture",
        ],
    ]:
        subprocess.run([*git, *arguments], check=True)  # noqa: S603 - test-owned repository
    sha = subprocess.run(  # noqa: S603 - test-owned repository
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    # A changed working file must never substitute for the exact commit's blob.
    if contract == "current":
        (repository / canonical).write_bytes(b"uncommitted replacement")
    paths = MODULE.Paths(state=tmp_path / "engine")
    paths.state.mkdir()
    shutil.copytree(repository / ".git", paths.mirror)

    def runner(argv, **kwargs):
        return subprocess.run(  # noqa: S603 - only Git on the test-owned repository
            argv, capture_output=True, text=True, check=True, **kwargs
        )

    engine = MODULE.Engine(paths=paths, run=runner)
    if contract == "missing":
        with pytest.raises(subprocess.CalledProcessError):
            engine.source_archive(sha, tmp_path, "infra/application")
        return
    if contract == "unsupported":
        with pytest.raises(MODULE.ReleaseError, match="unsupported paths"):
            engine.source_archive(sha, tmp_path, "infra/application")
        return
    archive, digest = engine.source_archive(sha, tmp_path, "infra/application")
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive) as contents:
        assert contents.pax_headers["comment"] == sha
        if contract == "legacy":
            assert canonical not in contents.getnames()
        else:
            with contents.extractfile(canonical) as blob:
                assert blob.read() == (ROOT / canonical).read_bytes()


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


class RecoveryGitHub(FakeGitHub):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__()
        self.recovery_runs = [
            run(OLD, MODULE.CORE_RECOVERY_WORKFLOW, id=200, event="workflow_dispatch")
        ]
        self.runs[(MODULE.CORE_WORKFLOW, HEAD)] = [run(HEAD)]
        self.artifacts[200] = [
            artifact(OLD, f"ac-application-recovered-{HEAD}", run_id=200, id=8),
            artifact(OLD, f"ac-application-recovery-proof-{HEAD}", run_id=200, id=9),
        ]
        self.digests = {
            key: f"ghcr.io/authorityclosers/authority-closers-{image}@{DIGEST}"
            for key, image in zip(
                ("api", "learner", "admin", "coach"),
                ("api", "learner-web", "admin-web", "coach-web"),
                strict=True,
            )
        }
        self.manifest = (
            f"AC_RELEASE_ID={HEAD}\n"
            + "".join(f"AC_{key.upper()}_REGISTRY_DIGEST={d}\n" for key, d in self.digests.items())
        ).encode()
        self.proof = {
            "schema": "ac.application-recovery/1",
            "repository": REPO,
            "release_sha": HEAD,
            "validation_run_id": 100,
            "recovery_run_id": 200,
            "recovery_head_sha": OLD,
            "artifact_id": 8,
            "artifact_name": f"ac-application-recovered-{HEAD}",
            "artifact_digest": DIGEST,
            "manifest_sha256": "sha256:" + hashlib.sha256(self.manifest).hexdigest(),
            "registry_digests": self.digests,
            "original_package_job_id": 300,
            "publication_log_sha256": DIGEST,
        }
        self.bundle = tmp_path / "bundle.zip"
        self.downloads: list[int] = []

    def get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        if f"/workflows/{MODULE.CORE_RECOVERY_WORKFLOW}/runs" in path:
            return {"workflow_runs": self.recovery_runs}
        return super().get_json(path, params)

    def download_artifact(self, artifact_id: int, destination: Path, digest: str) -> None:
        assert digest == DIGEST
        self.downloads.append(artifact_id)
        if artifact_id == 9:
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("recovery-proof.json", json.dumps(self.proof))
        else:
            assert artifact_id == 8
            shutil.copyfile(self.bundle, destination)


@pytest.mark.parametrize("original", [[], [artifact(HEAD, f"ac-application-{HEAD}", expired=True)]])
def test_missing_or_expired_core_uses_ci_recovery_bound_to_original_push(
    tmp_path, original
) -> None:
    github = RecoveryGitHub(tmp_path)
    github.artifacts[100] = original
    candidate = MODULE.core_candidate(github, HEAD)
    assert candidate.state == "ready"
    assert candidate.build.sha == HEAD
    assert candidate.build.run_id == 200
    assert candidate.build.recovery["validation_run_id"] == 100
    assert candidate.build.recovery["recovery_head_sha"] == OLD
    assert candidate.build.recovery["proof_artifact_digest"] == DIGEST
    assert github.downloads == [9]


def test_original_bundle_remains_preferred_over_recovery(tmp_path) -> None:
    github = RecoveryGitHub(tmp_path)
    github.artifacts[100] = [artifact(HEAD, f"ac-application-{HEAD}")]
    assert MODULE.core_candidate(github, HEAD).build.run_id == 100
    assert github.downloads == []


@pytest.mark.parametrize("status", ["failure", "cancelled", None])
def test_recovery_cannot_replace_unsuccessful_original_validation(tmp_path, status) -> None:
    github = RecoveryGitHub(tmp_path)
    github.runs[(MODULE.CORE_WORKFLOW, HEAD)] = [run(HEAD, conclusion=status)]
    assert MODULE.core_candidate(github, HEAD).build is None
    assert github.downloads == []


@pytest.mark.parametrize(
    "bad",
    [
        {"head_branch": "task/devenv/x"},
        {"event": "push"},
        {"repository": {"full_name": "fork/repo"}},
        {"path": ".github/workflows/other.yml"},
        {"head_sha": "invalid"},
        {"status": "in_progress"},
        {"conclusion": "failure"},
    ],
)
def test_recovery_ignores_untrusted_or_unfinished_workflow_runs(tmp_path, bad) -> None:
    github = RecoveryGitHub(tmp_path)
    github.recovery_runs[0].update(bad)
    assert MODULE.core_candidate(github, HEAD).build is None
    assert github.downloads == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_sha", OLD),
        ("validation_run_id", 101),
        ("recovery_run_id", 201),
        ("recovery_head_sha", HEAD),
        ("artifact_id", 99),
        ("artifact_digest", "sha256:" + "e" * 64),
        ("repository", "fork/repo"),
        ("manifest_sha256", "sha1:abc"),
        ("publication_log_sha256", "sha1:abc"),
        ("original_package_job_id", 0),
        ("registry_digests", {"api": DIGEST}),
    ],
)
def test_recovery_refuses_cross_run_cross_sha_or_unbound_proofs(tmp_path, field, value) -> None:
    github = RecoveryGitHub(tmp_path)
    github.proof[field] = value
    with pytest.raises(MODULE.ReleaseError, match="core recovery proof"):
        MODULE.core_candidate(github, HEAD)


@pytest.mark.parametrize("missing", [8, 9])
def test_recovery_requires_both_live_unique_artifacts(tmp_path, missing) -> None:
    github = RecoveryGitHub(tmp_path)
    github.artifacts[200] = [a for a in github.artifacts[200] if a["id"] != missing]
    assert MODULE.core_candidate(github, HEAD).state == "failed"


@pytest.mark.parametrize("bad", [{"expired": True}, {"workflow_run": {"id": 999, "head_sha": OLD}}])
def test_recovery_does_not_admit_superseded_or_cross_run_proof_artifact(tmp_path, bad):
    github = RecoveryGitHub(tmp_path)
    github.artifacts[200][1].update(bad)
    assert MODULE.core_candidate(github, HEAD).build is None


def test_recovery_refuses_ambiguous_duplicate_artifacts(tmp_path):
    github = RecoveryGitHub(tmp_path)
    github.artifacts[200].append({**github.artifacts[200][1], "id": 10})
    assert MODULE.core_candidate(github, HEAD).build is None


@pytest.mark.parametrize("proof", [[], {"schema": "ac.application-recovery/1"}])
def test_recovery_refuses_unstructured_proof(tmp_path, proof):
    github = RecoveryGitHub(tmp_path)
    github.proof = proof
    with pytest.raises(MODULE.ReleaseError, match="unexpected fields"):
        MODULE.core_candidate(github, HEAD)


def test_recovery_bounds_proof_download_and_expansion(tmp_path):
    github = RecoveryGitHub(tmp_path)
    github.artifacts[200][1]["size_in_bytes"] = MODULE.RECOVERY_PROOF_MAX_BYTES + 1
    with pytest.raises(MODULE.ReleaseError, match="size ceiling"):
        MODULE.core_candidate(github, HEAD)
    assert github.downloads == []
    github.artifacts[200][1]["size_in_bytes"] = 1000
    github.proof["padding"] = "x" * MODULE.RECOVERY_PROOF_MAX_BYTES
    with pytest.raises(MODULE.ReleaseError, match="archive is invalid"):
        MODULE.core_candidate(github, HEAD)


def test_recovery_turns_corrupt_zip_into_a_clear_refusal(tmp_path):
    github = RecoveryGitHub(tmp_path)
    github.download_artifact = lambda _id, path, _digest: path.write_bytes(b"broken")
    with pytest.raises(MODULE.ReleaseError, match="archive is invalid"):
        MODULE.core_candidate(github, HEAD)


def test_recovery_store_checks_manifest_and_preserves_ci_provenance(tmp_path) -> None:
    github = RecoveryGitHub(tmp_path)
    bundle_zip(github.bundle, {**CORE, "release-images.env": github.manifest})
    build = MODULE.core_candidate(github, HEAD).build
    engine = make_engine(tmp_path, github=github)
    engine.store_bundle(build, "core", MODULE.CORE_FILES)
    assert engine.stored_build(HEAD, "core") == build
    github.recovery_runs = []
    assert engine.store_bundle(engine.stored_build(HEAD, "core"), "core", MODULE.CORE_FILES)
    assert github.downloads == [9, 8]
    different = MODULE.Build(HEAD, 201, 10, build.artifact_name, DIGEST, build.recovery)
    with pytest.raises(MODULE.ReleaseError, match="stored core provenance differs"):
        engine.store_bundle(different, "core", MODULE.CORE_FILES)
    assert engine.stored_build(HEAD, "core") == build


@pytest.mark.parametrize("change_proof", [False, True])
def test_recovery_refuses_manifest_changed_even_with_valid_bundle_checksums(tmp_path, change_proof):
    github = RecoveryGitHub(tmp_path)
    manifest = github.manifest.replace(DIGEST.encode(), ("sha256:" + "e" * 64).encode())
    if change_proof:
        github.proof["manifest_sha256"] = "sha256:" + hashlib.sha256(manifest).hexdigest()
    bundle_zip(github.bundle, {**CORE, "release-images.env": manifest})
    build = MODULE.core_candidate(github, HEAD).build
    engine = make_engine(tmp_path, github=github)
    with pytest.raises(MODULE.ReleaseError, match="recovered core manifest"):
        engine.store_bundle(build, "core", MODULE.CORE_FILES)
    assert not (engine.paths.store / HEAD / "core.provenance.json").exists()


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
    foundation_backup_tool(engine, "20261002_0067", "20261003_0072")
    engine.require_backup_support(bundle_with_head(tmp_path, "20261003_0072"))


@pytest.mark.parametrize("installed", [("20260924_0048",), ()])
def test_unknown_migration_head_is_refused_before_install(tmp_path: Path, installed) -> None:
    engine = make_engine(tmp_path)
    if installed:
        foundation_backup_tool(engine, *installed)
    with pytest.raises(MODULE.ReleaseError, match="do not recognise migration 20261003_0072"):
        engine.require_backup_support(bundle_with_head(tmp_path, "20261003_0072"))


def test_bundle_without_migration_head_is_refused(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    foundation_backup_tool(engine, "20261003_0072")
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


def native_admission_fixture(tmp_path: Path):
    from tests.infra.test_sales_xray_native_installer import installer
    from tests.unit.test_native_artifact_compatibility import MODULE as verifier
    from tests.unit.test_native_artifact_compatibility import Bundle, git

    bundle = Bundle(tmp_path)
    previous = bundle.source
    workflow = bundle.repo / verifier.WORKFLOW
    workflow.write_bytes(workflow.read_bytes() + b"changed workflow input\n")
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Changed reviewed native workflow input")
    bundle.source = git(bundle.repo, "rev-parse", "HEAD")
    bundle.native.update(
        source_commit=bundle.source, context_tree_id=git(bundle.repo, "rev-parse", "HEAD^{tree}")
    )
    config = json.dumps(
        {
            "os": "linux",
            "architecture": "amd64",
            "config": {
                "User": "10001:10001",
                "WorkingDir": "/app",
                "Entrypoint": ["python", "-m", "ac_platform.conversation_intelligence"],
                "Cmd": ["doctor"],
            },
        }
    ).encode()
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    manifest = json.dumps(
        {"schemaVersion": 2, "config": {"digest": config_id, "size": len(config)}, "layers": []}
    ).encode()
    image_ref = "sha256:" + hashlib.sha256(manifest).hexdigest()
    buffer = io.BytesIO()
    native_tag = "ghcr.io/authorityclosers/ac-sales-xray-native:" + bundle.source
    with tarfile.open(fileobj=buffer, mode="w:gz") as image:
        index = json.dumps(
            {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "digest": image_ref,
                        "annotations": {"io.containerd.image.name": native_tag},
                    }
                ],
            }
        ).encode()
        entry = tarfile.TarInfo("index.json")
        entry.size = len(index)
        image.addfile(entry, io.BytesIO(index))
        for identity, raw in ((config_id, config), (image_ref, manifest)):
            member = tarfile.TarInfo("blobs/sha256/" + identity.removeprefix("sha256:"))
            member.size = len(raw)
            image.addfile(member, io.BytesIO(raw))
    transport = buffer.getvalue()
    bundle.native["image"].update(expected_runtime_ref=image_ref, image_id=config_id)
    bundle.native["transport"].update(
        bytes=len(transport),
        sha256=hashlib.sha256(transport).hexdigest(),
        manifest_digest=image_ref,
        config_digest=config_id,
    )
    bundle.payload["native-image.tar.gz"] = transport
    bundle.payload["native-image.env"] = (
        "\n".join(
            f"{key}={value}"
            for key, value in {
                "AC_NATIVE_IMAGE": image_ref,
                "AC_NATIVE_IMAGE_ID": config_id,
                "AC_NATIVE_SOURCE_COMMIT": bundle.source,
                "AC_NATIVE_IMAGE_TYPE": "oci_transport_manifest",
                "AC_NATIVE_TRANSPORT_MANIFEST_DIGEST": image_ref,
                "AC_NATIVE_TRANSPORT_CONFIG_DIGEST": config_id,
                "AC_NATIVE_TRANSPORT_SHA256": bundle.native["transport"]["sha256"],
                "AC_NATIVE_HELPER_SHA256": bundle.native["helper_source"]["sha256"],
            }.items()
        ).encode()
        + b"\n"
    )
    bundle.run.update(head_sha=bundle.source, event="push", head_branch="main", run_attempt=1)
    bundle.artifact.update(
        name="ac-sales-xray-native-" + bundle.source,
        expired=False,
        expires_at=MODULE.dt.datetime.fromtimestamp(NOW + DAY, MODULE.dt.UTC).isoformat(),
    )
    bundle.artifact["workflow_run"]["head_sha"] = bundle.source
    bundle.refresh()
    engine = make_engine(tmp_path / "engine")
    engine.clock = lambda: NOW
    # source_inputs accepts a working Git repository as well as the real bare mirror.
    engine.paths = SimpleNamespace(
        **engine.paths.__dict__, mirror=bundle.repo, native_store=engine.paths.native_store
    )
    return engine, bundle, verifier, installer, previous


def store_native_fixture(engine, bundle) -> Path:
    stored = engine.paths.native_store / bundle.source
    stored.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle.archive, stored / "native-artifact.zip")
    (stored / "artifact-metadata.json").write_text(json.dumps(bundle.artifact))
    (stored / "workflow-run.json").write_text(json.dumps(bundle.run))
    return stored


def test_changed_input_native_target_admission_checks_ci_source_and_transport(
    tmp_path: Path,
) -> None:
    engine, bundle, verifier, installer, previous = native_admission_fixture(tmp_path)
    assert (
        verifier.source_inputs(bundle.repo, previous)[1]
        != verifier.source_inputs(bundle.repo, bundle.source)[1]
    )
    store_native_fixture(engine, bundle)
    stage = tmp_path / "stage"
    stage.mkdir()
    target = engine.verify_native_target(bundle.source, stage, verifier, installer)
    assert (target / "native-image.json").read_bytes() == bundle.payload["native-image.json"]
    assert (target / "helper/scripts/native_runtime_helper.py").read_bytes() == bundle.files[
        "scripts/native_runtime_helper.py"
    ]
    assert not engine.run.calls  # no Docker load, systemd or provider runtime calls


@pytest.mark.parametrize(
    "defect",
    [
        "run",
        "rerun",
        "dispatch",
        "branch",
        "expired",
        "missing",
        "zip",
        "source",
        "config",
    ],
)
def test_native_target_admission_refuses_incomplete_mismatched_or_expired_provenance(
    tmp_path: Path, defect: str
) -> None:
    engine, bundle, verifier, installer, _ = native_admission_fixture(tmp_path)
    if defect == "run":
        bundle.run["head_sha"] = OLD
    elif defect == "rerun":
        bundle.run["run_attempt"] = 2
    elif defect == "dispatch":
        bundle.run["event"] = "workflow_dispatch"
    elif defect == "branch":
        bundle.run["head_branch"] = "feature"
    elif defect == "expired":
        bundle.artifact["expired"] = True
    elif defect == "source":
        bundle.native["source_commit"] = OLD
    elif defect == "config":
        bundle.native["transport"]["config_digest"] = IMAGE
    bundle.refresh()
    stored = store_native_fixture(engine, bundle)
    if defect == "missing":
        (stored / "workflow-run.json").unlink()
    if defect == "zip":
        (stored / "native-artifact.zip").write_bytes(b"corrupt")
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(MODULE.ReleaseError):
        engine.verify_native_target(bundle.source, stage, verifier, installer)
    assert not engine.run.calls


def native_delivery_fixture(
    tmp_path: Path, failure: str = "", *, core_sha: str = HEAD, environment: str = "staging"
):
    """A verified plan plus fictional systemd/Docker/application delivery adapters."""
    import grp

    from tests.infra.test_ac_release_foundation_install import MIGRATION, running_core, setup

    engine, base_runner, build = setup(tmp_path)
    build = MODULE.Build(
        core_sha, build.run_id, build.artifact_id, "ac-application-" + core_sha, DIGEST
    )
    engine.operator_group = grp.getgrgid(os.getgid()).gr_name
    engine.installed_engine = lambda: OUTSIDE
    foundation_backup_tool(engine, MIGRATION)
    running_core(engine, environment, OLD, MIGRATION)
    config = engine.paths.sales_xray / environment
    config.mkdir(parents=True)
    operator = engine.paths.application / "operator-inputs" / environment
    operator.mkdir(parents=True)
    approval = operator / "approval.json"
    approval.write_bytes(b'{"testers":["fictional"],"limits":7,"guards":["bounded"]}\n')
    approval_hash = MODULE._sha256_file(approval)
    previous_activation = engine.activation_path(environment, OLD)
    previous_activation.write_text(
        json.dumps(
            {
                "release_id": OLD,
                "approval_file": str(approval),
                "approval_sha256": approval_hash,
                "native_image_ref": IMAGE,
                "native_image_config_id": IMAGE,
            }
        )
    )
    previous_units = operator / "native-units.json"
    previous_units.write_text(
        json.dumps(
            {
                "supervisor_source": "/srv/authority-closers/application/releases/"
                + OLD
                + "/scripts/render-sales-xray-native.py",
                "units": {"native.service": "old helper", "native.mount": "old mount"},
            }
        )
    )
    old_manifest = operator / "native-image.json"
    old_manifest.write_text(json.dumps({"image": {"expected_runtime_ref": IMAGE}}))
    new_image = "sha256:" + "1" * 64
    target = tmp_path / "native-target"
    target.mkdir()
    (engine.paths.application / "artifacts").mkdir()
    for name in MODULE.NATIVE_FILES:
        (target / name).write_bytes(b"verified fictional artifact\n")
    (target / "native-image.json").write_text(
        json.dumps({"image": {"expected_runtime_ref": new_image}})
    )
    if environment == "production":
        running_core(engine, "staging", core_sha, MIGRATION)
        staging_inputs = engine.paths.application / "operator-inputs/staging"
        staging_inputs.mkdir(parents=True)
        staging_approval = staging_inputs / "approval.json"
        staging_approval.write_text('{"limits":99,"expires_at_epoch":1}\n')
        staging_config = engine.paths.sales_xray / "staging"
        staging_config.mkdir()
        engine.activation_path("staging", core_sha).write_text(
            json.dumps({"native_image_ref": new_image, "approval_file": str(staging_approval)})
        )
        engine.set_paused("staging", True, "unrelated staging containment")
        engine.paths.failed_flag("staging", "core").write_text(OUTSIDE + "\n")
    runtime = {"helper": IMAGE, "units": previous_units.read_bytes()}
    events = []

    class NativeOperator:
        def install(self, **kwargs):
            assert kwargs["environment"] == environment
            assert (
                kwargs["receipt"].parent == engine.paths.application / "deployments" / environment
            )
            assert kwargs["native_units"].is_relative_to(operator)
            image = json.loads(kwargs["native_artifact_manifest"].read_text())["image"][
                "expected_runtime_ref"
            ]
            events.append("native.restore" if image == IMAGE else "native.install")
            runtime.update(helper=image, units=kwargs["native_units"].read_bytes())
            if (failure == "native" and image == new_image) or (
                failure == "restore" and image == IMAGE
            ):
                raise MODULE.ReleaseError("fictional native installer failure")
            return {
                "status": "installed",
                "native_image_ref": image,
                "provider_calls": 0,
                "database_writes": 0,
            }

    plan = {
        "installer": NativeOperator(),
        "target": target,
        "binding": SimpleNamespace(image_ref=new_image, image_config_id=new_image),
        "previous_binding": SimpleNamespace(image_ref=IMAGE, image_config_id=IMAGE),
        "previous_manifest": old_manifest,
        "previous_manifest_sha256": MODULE._sha256_file(old_manifest),
        "previous_units": previous_units,
        "previous_digest": MODULE._sha256_file(previous_units),
        "units": {
            "supervisor_source": json.loads(previous_units.read_text())["supervisor_source"],
            "units": {"native.service": "new helper", "native.mount": "old mount"},
        },
        "renderer": Path("/fictional/renderer"),
        "supervisor": json.loads(previous_units.read_text())["supervisor_source"],
        "source_activation": previous_activation,
        "source_activation_sha256": MODULE._sha256_file(previous_activation),
        "approval_sha256": approval_hash,
        "previous_core": OLD,
        "previous_native": NATIVE,
        "rollback_build": MODULE.Build(OLD, 100, 7, "ac-application-" + OLD, DIGEST),
    }
    pointer = engine.native_preparation_path(environment, core_sha)
    pointer.parent.mkdir(parents=True)
    pointer.write_text("verified plan pin")
    engine.native_deployment_plan = lambda *args: plan

    def delivery(argv, **kwargs):
        argv = list(argv)
        if argv[:2] == ["docker", "load"]:
            events.append("docker.load")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "python3" and argv[1].endswith("prepare-sales-xray-native-activation.py"):
            events.append("activation.prepare")
            if plan.get("native_source", core_sha) != core_sha:
                proof = Path(argv[argv.index("--native-reuse-proof") + 1])
                assert (
                    MODULE._sha256_file(proof)
                    == argv[argv.index("--native-reuse-proof-sha256") + 1]
                )
                pinned = json.loads(proof.read_text())
                assert pinned["native_source_commit"] == plan["native_source"]
                assert pinned["target_release_id"] == core_sha
            if failure == "activation":
                raise MODULE.ReleaseError("fictional activation publication failure")
            output = Path(argv[argv.index("--output-dir") + 1])
            output.mkdir()
            prepared = output / f"activation-{core_sha}.json"
            data = json.loads(previous_activation.read_text())
            data.update(
                release_id=core_sha, native_image_ref=new_image, native_image_config_id=new_image
            )
            prepared.write_text(json.dumps(data))
            prepared.with_suffix(".json.sha256").write_text(MODULE._sha256_file(prepared) + "\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "bash" and argv[1].endswith("install-application-release.sh"):
            rollback = kwargs["env"].get("AC_CORE_ROLLBACK_ONLY") == "1"
            events.append("core.restore" if rollback else "core.install")
            assert runtime["helper"] == (IMAGE if rollback else new_image)
            target_sha = OLD if rollback else core_sha
            link = engine.paths.application / f"current-{environment}"
            if rollback or failure not in ("core-before",):
                release = engine.paths.application / "releases" / target_sha
                release.mkdir(exist_ok=True)
                link.unlink()
                link.symlink_to(release)
            return subprocess.CompletedProcess(
                argv,
                9 if not rollback and failure.startswith("core-") else 0,
                "AC_STATUS=COMMITTED\n",
                "",
            )
        return base_runner(argv, **kwargs)

    engine.run = delivery

    def check(environment, sha, log):
        assert engine.current_core(environment) == sha
        assert runtime["helper"] == (IMAGE if sha == OLD else new_image)
        if failure in ("readiness", "restore") and sha == core_sha:
            raise MODULE.ReleaseError("fictional core readiness failure")

    engine.check_core = check
    return engine, build, runtime, plan, events, approval


def staging_native_state(engine):
    roots = (
        engine.paths.sales_xray / "staging",
        engine.paths.application / "operator-inputs/staging",
        engine.paths.application / "deployments/staging",
    )
    return {
        "core": engine.current_core("staging"),
        "files": {
            str(path): path.read_bytes()
            for root in roots
            for path in root.rglob("*")
            if path.is_file()
        },
        "flags": {
            str(path): path.read_bytes() if path.exists() else None
            for path in (
                engine.paths.paused_flag("staging"),
                engine.paths.failed_flag("staging", "core"),
            )
        },
    }


@pytest.mark.parametrize(
    "failure", ["native", "activation", "core-before", "core-after", "readiness"]
)
@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_native_transition_failure_restores_native_core_and_activation_and_keeps_containment(
    tmp_path: Path, failure: str, environment: str
) -> None:
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path, failure, environment=environment
    )
    staging_before = staging_native_state(engine) if environment == "production" else None
    old_units = runtime["units"]
    old_activation = plan["source_activation"].read_bytes()
    staging_before = staging_native_state(engine) if environment == "production" else None
    old_approval = approval.read_bytes()
    result = engine.attempt(environment, "core", build, dry_run=False, trigger="auto")
    assert result["result"] == "failed"
    assert "pinned predecessor restored" in result["error"]
    assert runtime == {"helper": IMAGE, "units": old_units}
    assert engine.current_core(environment) == OLD
    assert plan["source_activation"].read_bytes() == old_activation
    assert approval.read_bytes() == old_approval
    assert not engine.activation_path(environment, HEAD).exists()
    assert events.index("native.restore") < events.index("core.restore")
    assert engine.is_paused(environment) and engine.failed_sha(environment, "core") == HEAD
    assert any(entry.get("result") == "restored" for entry in engine.history())
    if staging_before is not None:
        assert staging_native_state(engine) == staging_before


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_native_transition_success_publishes_exact_binding_and_unchanged_approval(
    tmp_path: Path,
    environment: str,
) -> None:
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path, environment=environment
    )
    staging_before = staging_native_state(engine) if environment == "production" else None
    old_approval = approval.read_bytes()
    result = engine.attempt(environment, "core", build, dry_run=False, trigger="auto")
    assert result["result"] == "success"
    assert runtime["helper"] == plan["binding"].image_ref
    assert engine.current_core(environment) == HEAD
    published = json.loads(engine.activation_path(environment, HEAD).read_text())
    assert published["native_image_ref"] == runtime["helper"]
    assert published["approval_sha256"] == MODULE._sha256_file(approval)
    assert approval.read_bytes() == old_approval
    assert events.index("native.install") < events.index("core.install")
    assert "native.restore" not in events
    if staging_before is not None:
        assert staging_native_state(engine) == staging_before


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_native_core_dry_run_preserves_runtime_publication_flags_and_approvals(
    tmp_path: Path,
    environment: str,
) -> None:
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path, environment=environment
    )
    engine.set_paused(environment, True, "existing containment")
    engine.paths.failed_flag(environment, "core").write_text(HEAD + "\n")
    before = {
        path: path.read_bytes()
        for path in [
            engine.paths.paused_flag(environment),
            engine.paths.failed_flag(environment, "core"),
            plan["source_activation"],
            approval,
        ]
    }
    old_units = runtime["units"]
    result = engine.attempt(environment, "core", build, dry_run=True, trigger="manual")
    assert result["result"] == "dry-run"
    assert not events and not engine.history()
    assert runtime == {"helper": IMAGE, "units": old_units}
    assert engine.current_core(environment) == OLD
    assert not engine.activation_path(environment, HEAD).exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_unverifiable_native_restore_stays_failed_and_paused(
    tmp_path: Path, environment: str
) -> None:
    engine, build, _, _, events, _ = native_delivery_fixture(
        tmp_path, "restore", environment=environment
    )
    result = engine.attempt(environment, "core", build, dry_run=False, trigger="auto")
    assert result["result"] == "failed"
    assert "could not be verified" in result["error"]
    assert engine.is_paused(environment) and engine.failed_sha(environment, "core") == HEAD
    assert "core.restore" not in events
    assert any(entry.get("result") == "recovery-failed" for entry in engine.history())


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_missing_rollback_pin_refuses_before_native_or_core_mutation(
    tmp_path: Path, environment: str
) -> None:
    engine, build, runtime, _, events, _ = native_delivery_fixture(
        tmp_path, environment=environment
    )

    def refuse(*args):
        raise MODULE.ReleaseError("native previous unit pin is missing")

    engine.native_deployment_plan = refuse
    result = engine.attempt(environment, "core", build, dry_run=True, trigger="manual")
    assert result["result"] == "failed"
    assert not events and runtime["helper"] == IMAGE
    assert engine.current_core(environment) == OLD


def test_native_transition_receipts_keep_both_core_bundles_and_installer_artifacts(
    tmp_path: Path,
) -> None:
    engine = retention_fixture(tmp_path)
    engine.record(
        {"action": "native-prepare", "target": HEAD, "previous_core": OLD, "result": "prepared"}
    )
    for sha in (HEAD, OLD, OUTSIDE):
        (engine.paths.store / sha / "core").mkdir(parents=True)
    assert engine.prune_store() == [OUTSIDE]
    assert engine.native_rollback_pins() == {HEAD, OLD}
    report = engine.prune_artifacts(1, images=False)
    decisions = {entry["sha"]: entry["keep"] for entry in report["artifacts"]}
    assert "governed native transition rollback pin" in decisions[OLD]


def test_invalid_native_rollback_receipt_refuses_pruning(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    (engine.paths.store / OLD / "core").mkdir(parents=True)
    engine.record({"action": "native-transition", "target": HEAD, "result": "armed"})
    with pytest.raises(MODULE.ReleaseError, match="rollback receipt is invalid"):
        engine.prune_store()
    assert (engine.paths.store / OLD / "core").is_dir()


@pytest.mark.parametrize("contents", ["{", '{"schema":"ac.release.native-preparation/1"}'])
def test_incomplete_native_preparation_receipt_refuses_before_runtime_mutation(
    tmp_path: Path, contents: str
) -> None:
    engine = make_engine(tmp_path)
    pointer = engine.native_preparation_path("staging", HEAD)
    pointer.parent.mkdir(parents=True)
    pointer.write_text(contents)
    with pytest.raises(MODULE.ReleaseError, match="native preparation"):
        engine.native_deployment_plan("staging", HEAD, tmp_path / "source", tmp_path / "stage")
    assert not engine.run.calls
    assert not engine.is_paused("staging")
    assert engine.failed_sha("staging", "core") is None


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
@pytest.mark.parametrize("dry_run", [True, False])
def test_prepare_native_is_distinct_from_installation_and_preserves_containment(
    tmp_path: Path, dry_run: bool, environment: str
) -> None:
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path, environment=environment
    )
    engine.stored_build = lambda *args: build
    engine.prepare_native_transition = lambda *args: plan
    stored = engine.paths.native_store / HEAD
    stored.mkdir(parents=True)
    for name in MODULE.NATIVE_STORE_FILES:
        (stored / name).write_bytes(b"fictional already admitted provenance\n")
    engine.set_paused(environment, True, "existing containment")
    engine.paths.failed_flag(environment, "core").write_text(HEAD + "\n")
    pointer = engine.native_preparation_path(environment, HEAD)
    paths = [
        engine.paths.paused_flag(environment),
        engine.paths.failed_flag(environment, "core"),
        plan["source_activation"],
        approval,
    ]
    before = {path: path.read_bytes() for path in paths}
    old_pointer = pointer.read_bytes()
    old_runtime = runtime.copy()
    receipt = engine.prepare_native(
        environment, HEAD, plan["previous_units"], plan["previous_digest"], dry_run=dry_run
    )
    assert receipt["environment"] == environment
    assert receipt["dry_run"] is dry_run and receipt["runtime_mutation"] is False
    assert not events and runtime == old_runtime
    assert engine.current_core(environment) == OLD
    assert not engine.activation_path(environment, HEAD).exists()
    assert {path: path.read_bytes() for path in paths} == before
    if dry_run:
        assert pointer.read_bytes() == old_pointer and not engine.history()
    else:
        assert json.loads(pointer.read_text()) == receipt
        assert engine.history()[0]["action"] == "native-prepare"
        # An offline record or ZIP change after preparation invalidates admission.
        (stored / "native-artifact.zip").write_bytes(b"changed archive")
        with pytest.raises(MODULE.ReleaseError, match="identities changed"):
            MODULE.Engine.native_deployment_plan(
                engine, environment, HEAD, tmp_path / "source", tmp_path
            )
        assert runtime == old_runtime and not events


def test_retained_native_bundle_remains_admissible_after_github_retention_deadline(
    tmp_path: Path,
) -> None:
    engine, bundle, verifier, installer, _ = native_admission_fixture(tmp_path)
    bundle.artifact["expires_at"] = "2020-01-01T00:00:00Z"
    bundle.refresh()
    store_native_fixture(engine, bundle)
    stage = tmp_path / "stage"
    stage.mkdir()
    target = engine.verify_native_target(bundle.source, stage, verifier, installer)
    assert (target / "native-image.json").read_bytes() == bundle.payload["native-image.json"]
    assert not engine.run.calls


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
@pytest.mark.parametrize(
    ("changed_inputs", "failure"), [(False, ""), (False, "core-after"), (True, "")]
)
def test_timer_and_promotion_use_prepared_native_ancestor_and_refuse_changed_inputs(
    tmp_path: Path, changed_inputs: bool, failure: str, environment: str
) -> None:
    from tests.unit.test_native_artifact_compatibility import git

    native_root = tmp_path / "native"
    native_root.mkdir()
    _, bundle, verifier, _, _ = native_admission_fixture(native_root)
    native_sha = bundle.source
    path = bundle.repo / (verifier.WORKFLOW if changed_inputs else "core-only.txt")
    path.write_bytes(
        path.read_bytes() + b"next native input\n" if changed_inputs else b"new core\n"
    )
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Later main core")
    core_sha = git(bundle.repo, "rev-parse", "HEAD")
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path / "delivery", failure, core_sha=core_sha, environment=environment
    )
    engine.native_preparation_path(environment, core_sha).unlink()
    plan.update(native_source=native_sha, core_target=core_sha)
    engine.main_head = lambda: core_sha
    engine.update_engine = lambda *args: None
    engine.publish_status = lambda **kwargs: ""
    engine.web_target = lambda *args: None
    engine.is_ancestor = lambda older, newer: (
        older == OLD or bool(git(bundle.repo, "merge-base", "--is-ancestor", older, newer) == "")
    )
    engine.stored_build = lambda sha, component: MODULE.Build(
        sha, build.run_id, build.artifact_id, "ac-application-" + sha, DIGEST
    )
    sources = []

    def preflight(env, native, previous, digest, source, stage, target=None):
        assert env == environment
        sources.append((native, target))
        return plan

    engine.prepare_native_transition = preflight
    engine.native_controller = lambda stage: (
        plan["installer"],
        SimpleNamespace(source_inputs=lambda root, sha: verifier.source_inputs(bundle.repo, sha)),
    )
    store_native_fixture(engine, bundle)
    engine.prepare_native(
        environment, native_sha, plan["previous_units"], plan["previous_digest"], dry_run=False
    )
    engine.native_deployment_plan = MODULE.Engine.native_deployment_plan.__get__(engine)
    ready_core(engine.github, core_sha)
    old_approval = approval.read_bytes()
    if environment == "production":
        engine.paths.production_enabled.write_text("enabled\n")
        engine.paths.failed_flag("staging", "core").unlink()
        engine.current_web = lambda env: (core_sha if env == "staging" else OUTSIDE, IMAGE)
        engine.deploy_web = lambda *args, **kwargs: {}
        for component in MODULE.COMPONENTS:
            engine.record(
                {
                    "environment": "staging",
                    "component": component,
                    "sha": core_sha,
                    "result": "success",
                }
            )
        staging_before = staging_native_state(engine)
        results = engine.promote(
            "patch", "v0.2.1", requested_by="fictional operator", trigger="cli"
        )
        assert staging_native_state(engine) == staging_before
    else:
        results = engine.tick()
    assert results[0]["sha"] == core_sha
    assert approval.read_bytes() == old_approval
    assert not (engine.paths.native_store / core_sha).exists()
    if changed_inputs:
        assert results[0]["result"] == "failed"
        assert "native_inputs_changed" in results[0]["error"]
        assert engine.current_core(environment) == OLD and runtime["helper"] == IMAGE
        assert not events and engine.is_paused(environment)
    elif failure:
        assert results[0]["result"] == "failed"
        assert "pinned predecessor restored" in results[0]["error"]
        assert sources == [(native_sha, None), (native_sha, core_sha)]
        assert engine.current_core(environment) == OLD and runtime["helper"] == IMAGE
        assert not engine.activation_path(environment, core_sha).exists()
        assert events.index("native.restore") < events.index("core.restore")
        assert engine.is_paused(environment) and engine.failed_sha(environment, "core") == core_sha
    else:
        assert results[0]["result"] == "success"
        assert sources == [(native_sha, None), (native_sha, core_sha)]
        assert results[0]["sales_xray_native"] == native_sha
        assert engine.current_core(environment) == core_sha
        assert runtime["helper"] == plan["binding"].image_ref
        activation = json.loads(engine.activation_path(environment, core_sha).read_text())
        assert activation["release_id"] == core_sha
        assert activation["native_image_ref"] == runtime["helper"]
        assert (
            engine.paths.application / "artifacts" / ("sales-xray-native-" + native_sha)
        ).is_dir()
        assert not (
            engine.paths.application / "artifacts" / ("sales-xray-native-" + core_sha)
        ).exists()
        # Old preparation receipts stop governing after their predecessor advances.
        assert (
            engine.native_deployment_plan(environment, core_sha, tmp_path / "source", tmp_path)
            is None
        )


@pytest.mark.parametrize("changed_inputs", [False, True])
def test_engine_native_reuse_proof_is_accepted_by_real_activation_preparer(
    tmp_path: Path, changed_inputs: bool
) -> None:
    from tests.unit.test_native_artifact_compatibility import git
    from tests.unit.test_prepare_sales_xray_native_activation import (
        _MODULE as preparer,
    )
    from tests.unit.test_prepare_sales_xray_native_activation import (
        _write_source_activation,
    )

    native_root = tmp_path / "native"
    native_root.mkdir()
    engine, bundle, verifier, installer, _ = native_admission_fixture(native_root)
    store_native_fixture(engine, bundle)
    path = bundle.repo / (verifier.WORKFLOW if changed_inputs else "core-only.txt")
    path.write_bytes(path.read_bytes() + b"new workflow\n" if changed_inputs else b"new core\n")
    git(bundle.repo, "add", ".")
    git(bundle.repo, "commit", "--quiet", "-m", "Next core target")
    target = git(bundle.repo, "rev-parse", "HEAD")
    source_root = tmp_path / "activation"
    source_root.mkdir()
    source, source_bytes = _write_source_activation(source_root)
    stage = tmp_path / "stage"
    stage.mkdir()
    admitted = engine.verify_native_target(bundle.source, stage, verifier, installer)
    args = engine.native_reuse_arguments(bundle.source, target, tmp_path / "proof-inputs")
    arguments = dict(
        source_activation=source,
        target_release_id=target,
        native_artifact_manifest=admitted / "native-image.json",
        native_artifact_sha256=MODULE._sha256_file(admitted / "native-image.json"),
        output_dir=tmp_path / "prepared",
        native_reuse_proof=Path(args[1]),
        native_reuse_proof_sha256=args[3],
        source_repository=Path(args[5]),
    )
    if changed_inputs:
        with pytest.raises(preparer.PrepareError, match="native_inputs_changed"):
            preparer.prepare(**arguments)
        assert not (tmp_path / "prepared").exists()
    else:
        result = preparer.prepare(**arguments)
        assert result["release_id"] == target
        assert result["native_source_commit"] == bundle.source
        assert result["approval_replaced"] is False and result["provider_calls"] == 0
        activation = json.loads(Path(result["activation"]).read_text())
        assert activation["native_image_ref"] == bundle.native["image"]["expected_runtime_ref"]
    assert all(Path(path).read_bytes() == raw for path, raw in source_bytes.items())


def native_preflight_fixture(tmp_path: Path, environment: str):
    """Exercise engine preflight with fictional installer/systemd boundary adapters."""
    engine, build, runtime, plan, events, approval = native_delivery_fixture(
        tmp_path, environment=environment
    )
    engine.clock = lambda: NOW
    engine.is_ancestor = lambda older, newer: True
    engine.stored_build = lambda sha, component: MODULE.Build(
        sha, 100, 7, "ac-application-" + sha, DIGEST
    )
    approval_data = json.loads(approval.read_text())
    approval_data["expires_at_epoch"] = NOW + DAY * 2
    approval.write_text(json.dumps(approval_data))
    activation = plan["source_activation"]
    descriptor = json.loads(activation.read_text())
    descriptor["approval_sha256"] = MODULE._sha256_file(approval)
    activation.write_text(json.dumps(descriptor))
    previous_units = plan["previous_units"]
    previous = json.loads(previous_units.read_text())
    renderer = engine.paths.application / "releases" / OLD / "scripts/render-sales-xray-native.py"
    renderer.parent.mkdir()
    renderer.write_text("# fictional reviewed renderer\n")
    previous["supervisor_source"] = str(renderer)
    previous_units.write_text(json.dumps(previous))
    runtime["units"] = previous_units.read_bytes()
    old_binding = plan["previous_binding"]
    old_binding.identities = {IMAGE}
    rendered = {**previous, "units": {"native.service": "new helper"}}
    checks = []

    def validate(*args, **kwargs):
        assert kwargs["environment"] == environment
        checks.append(kwargs["environment"])

    def stage_units(**kwargs):
        staged = tmp_path / "rehearsal"
        staged.mkdir()
        unit = staged / "native.service"
        unit.write_text(rendered["units"]["native.service"])
        return staged, {"native.service": unit}

    installer = SimpleNamespace(
        _artifact_binding=lambda manifest, *args, **kwargs: (
            old_binding if manifest == plan["previous_manifest"] else plan["binding"]
        ),
        _ensure_existing_parents=lambda *args, **kwargs: None,
        _ensure_owner=lambda *args, **kwargs: None,
        _safe_json=lambda path: (json.loads(path.read_text()), path.read_bytes()),
        _validate_descriptor=validate,
        _validate_renderer_binding=validate,
        REVIEWED_RENDERERS={MODULE._sha256_file(renderer): (environment,)},
        _verify_reference_renderer=lambda *args, **kwargs: None,
        SubprocessSystemd=lambda: SimpleNamespace(verify=lambda paths: None),
        SYSTEMD_UNIT_ROOT=tmp_path / "systemd",
        _reject_existing_drift=lambda **kwargs: None,
        _unit_path=lambda root, name: root / name,
        _safe_existing_unit=lambda path, **kwargs: previous["units"][path.name].encode(),
        _capture_states=lambda *args: {"native.service": {"active": True, "enabled": True}},
        _readback=lambda systemd, names, root, env: checks.append(env),
        SubprocessGroup=lambda: SimpleNamespace(ensure=lambda **kwargs: {"status": "present"}),
        SubprocessDocker=lambda binding: SimpleNamespace(inspect_identity=lambda: IMAGE),
        _rendered_descriptor=lambda **kwargs: (validate(**kwargs) or rendered, b""),
        _stage_units=stage_units,
        _remove_tree=shutil.rmtree,
    )
    verifier = SimpleNamespace(
        parse=json.loads,
        read=lambda path: path.read_bytes(),
        source_inputs=lambda *args: (None, "same"),
    )

    def controller(stage):
        script = (
            stage / "native-controller/infra/application/scripts/install-application-release.sh"
        )
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("# AC_CORE_ROLLBACK_ONLY\n")
        return installer, verifier

    engine.native_controller = controller
    engine.native_for_image = lambda image: (
        (NATIVE, plan["previous_manifest"])
        if image == IMAGE
        else (HEAD, plan["target"] / "native-image.json")
    )
    engine.verify_native_target = lambda *args: plan["target"]

    base_delivery = engine.run

    def prepare(argv, **kwargs):
        if argv[0] != "python3" or not argv[1].endswith("prepare-sales-xray-native-activation.py"):
            return base_delivery(argv, **kwargs)
        assert Path(argv[argv.index("--source-activation") + 1]) == activation
        output = Path(argv[argv.index("--output-dir") + 1])
        output.mkdir()
        prepared = json.loads(activation.read_text())
        prepared.update(
            native_image_ref=plan["binding"].image_ref,
            native_image_config_id=plan["binding"].image_config_id,
        )
        (output / f"activation-{HEAD}.json").write_text(json.dumps(prepared))
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "provider_calls": 0,
                    "approval_replaced": False,
                    "release_id": HEAD,
                }
            ),
            "",
        )

    engine.run = prepare
    for name in MODULE.NATIVE_STORE_FILES:
        stored = engine.paths.native_store / HEAD / name
        stored.parent.mkdir(parents=True, exist_ok=True)
        stored.write_bytes(b"fictional provenance\n")
    engine.native_preparation_path(environment, HEAD).unlink()
    return engine, plan, runtime, events, approval, checks


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
@pytest.mark.parametrize("dry_run", [True, False])
def test_native_preflight_preparation_keeps_own_approval_and_runtime(
    tmp_path: Path, environment: str, dry_run: bool
) -> None:
    engine, plan, runtime, events, approval, checks = native_preflight_fixture(
        tmp_path, environment
    )
    before = runtime.copy()
    source_before = plan["source_activation"].read_bytes()
    approval_before = approval.read_bytes()
    staging_before = staging_native_state(engine)
    receipt = engine.prepare_native(
        environment,
        HEAD,
        plan["previous_units"],
        MODULE._sha256_file(plan["previous_units"]),
        dry_run=dry_run,
    )
    assert checks == [environment] * 5
    assert receipt["approval_sha256"] == MODULE._sha256_file(approval)
    assert receipt["source_activation_sha256"] == MODULE._sha256_file(plan["source_activation"])
    assert not events and runtime == before
    assert plan["source_activation"].read_bytes() == source_before
    assert approval.read_bytes() == approval_before
    assert staging_native_state(engine) == staging_before
    assert engine.native_preparation_path(environment, HEAD).exists() is (not dry_run)


@pytest.mark.parametrize(
    "defect",
    [
        "different-native",
        "missing-activation",
        "missing-core",
        "staging-pin",
        "expired-approval",
        "approval-digest",
    ],
)
def test_production_native_preflight_refuses_before_mutation(tmp_path: Path, defect: str) -> None:
    engine, plan, runtime, events, approval, _ = native_preflight_fixture(tmp_path, "production")
    units = plan["previous_units"]
    expected = "preflight failed"
    if defect == "different-native":
        engine.activation_path("staging", HEAD).write_text(json.dumps({"native_image_ref": IMAGE}))
        expected = "not running on staging"
    elif defect == "missing-activation":
        engine.activation_path("staging", HEAD).unlink()
    elif defect == "missing-core":
        (engine.paths.application / "current-staging").unlink()
        expected = "requires a live staging activation"
    elif defect == "staging-pin":
        units = engine.paths.application / "operator-inputs/staging/native-units.json"
        units.write_bytes(plan["previous_units"].read_bytes())
        expected = "pin path invalid"
    elif defect == "expired-approval":
        data = json.loads(approval.read_text())
        data["expires_at_epoch"] = NOW + DAY - 1
        approval.write_text(json.dumps(data))
        expected = "expires within one day"
    elif defect == "approval-digest":
        approval.write_text(approval.read_text() + "\n")
        expected = "approval digest mismatch"
    before = runtime.copy()
    staging_before = staging_native_state(engine)
    with engine.stage(HEAD) as stage, pytest.raises(MODULE.ReleaseError, match=expected):
        engine.prepare_native_transition(
            "production",
            HEAD,
            units,
            MODULE._sha256_file(units),
            tmp_path / "source",
            stage,
        )
    assert not events and runtime == before
    assert staging_native_state(engine) == staging_before
    assert not engine.activation_path("production", HEAD).exists()
    assert not engine.native_preparation_path("production", HEAD).exists()


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_native_preparation_receipts_are_environment_scoped_and_legacy_staging_works(
    tmp_path: Path, environment: str
) -> None:
    engine, build, _, plan, events, _ = native_delivery_fixture(tmp_path, environment=environment)
    engine.stored_build = lambda *args: build
    engine.prepare_native_transition = lambda *args: plan
    engine.native_controller = lambda stage: (
        None,
        SimpleNamespace(source_inputs=lambda *args: (None, "same")),
    )
    stored = engine.paths.native_store / HEAD
    stored.mkdir(parents=True)
    for name in MODULE.NATIVE_STORE_FILES:
        (stored / name).write_bytes(b"fictional provenance\n")
    receipt = engine.prepare_native(
        environment,
        HEAD,
        plan["previous_units"],
        plan["previous_digest"],
        dry_run=False,
    )
    path = engine.native_preparation_path(environment, HEAD)
    other = "production" if environment == "staging" else "staging"
    other_path = engine.native_preparation_path(other, HEAD)
    # Even an unreadable receipt from the other environment is never selected.
    other_path.write_text("{")
    if environment == "staging":
        receipt.pop("environment")
        path.unlink()
        path.write_text(json.dumps(receipt))
    select = MODULE.Engine.native_deployment_plan.__get__(engine)
    assert select(environment, HEAD, tmp_path, tmp_path) is plan
    path.unlink()
    assert select(environment, HEAD, tmp_path, tmp_path) is None
    assert not events
    # Copying an explicit opposite-environment receipt under this prefix refuses.
    receipt["environment"] = other
    path.write_text(json.dumps(receipt))
    with pytest.raises(MODULE.ReleaseError, match="identity is invalid"):
        select(environment, HEAD, tmp_path, tmp_path)


def test_production_preparation_rechecks_staging_native_before_delivery(tmp_path: Path) -> None:
    engine, plan, runtime, events, _, _ = native_preflight_fixture(tmp_path, "production")
    engine.prepare_native(
        "production",
        HEAD,
        plan["previous_units"],
        MODULE._sha256_file(plan["previous_units"]),
        dry_run=False,
    )
    engine.activation_path("staging", HEAD).write_text(json.dumps({"native_image_ref": IMAGE}))
    select = MODULE.Engine.native_deployment_plan.__get__(engine)
    before = runtime.copy()
    with (
        engine.stage(HEAD) as stage,
        pytest.raises(MODULE.ReleaseError, match="not running on staging"),
    ):
        select("production", HEAD, tmp_path / "source", stage)
    assert not events and runtime == before
    assert engine.current_core("production") == OLD


@pytest.mark.parametrize("environment", MODULE.ENVIRONMENTS)
def test_prepare_native_cli_passes_environment_and_pins(
    tmp_path: Path, environment: str, monkeypatch, capsys
) -> None:
    calls = []
    units = tmp_path / "native-units.json"

    def prepare(*args, **kwargs):
        calls.append((args, kwargs))
        return {"environment": args[0], "runtime_mutation": False}

    monkeypatch.setattr(MODULE, "Engine", lambda **kwargs: SimpleNamespace(prepare_native=prepare))
    assert (
        MODULE.main(
            [
                "prepare-native",
                environment,
                HEAD,
                "--previous-native-units",
                str(units),
                "--previous-native-units-sha256",
                "a" * 64,
                "--dry-run",
            ]
        )
        == 0
    )
    assert calls == [((environment, HEAD, units, "a" * 64), {"dry_run": True})]
    assert json.loads(capsys.readouterr().out)["environment"] == environment
