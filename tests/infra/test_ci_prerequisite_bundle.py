"""Verified bundle provenance, offline closure, recovery and workflow topology."""

from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ci import ci_prerequisite_bundle as bundle  # noqa: E402

HOST = {"id": "ubuntu", "version": "24.04", "architecture": "amd64"}
KEY = "b" * 64
SHA = "a" * 40
REPO = "fictional/project"


def fixture_archive(tmp_path, *, damage=None):
    deb = b"fictional Debian archive"
    names = {"debs/fictional_1_all.deb": deb, "debs/Packages": b"fictional index"}
    if damage == "path":
        names["browsers/../../escaped"] = b"no"
    if damage == "package":
        names["debs/fictional_1_all.deb"] = b"changed"
    payload = tmp_path / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        for name, content in names.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    original = tmp_path / "original.deb"
    original.write_bytes(deb)
    manifest = {
        "schema": bundle.SCHEMA,
        "policy": bundle.POLICY,
        "identity": KEY,
        "repository": REPO,
        "baseline": HOST,
        "producer": {"run_id": 12, "source_sha": SHA, "image": "20261021.1"},
        "origins": list(bundle.ORIGINS),
        "closure": "empty-status-offline-solve",
        "requested_packages": ["fictional"],
        "archive_sha256": bundle.digest(payload),
        "packages": {"fictional_1_all.deb": bundle.digest(original)},
    }
    if damage == "baseline":
        manifest["baseline"] = {**HOST, "version": "22.04"}
    elif damage == "producer":
        manifest["producer"]["run_id"] = 99
    elif damage == "identity":
        manifest["identity"] = "c" * 64
    elif damage == "closure":
        manifest["closure"] = "partial-producer-transaction"
    elif damage == "payload":
        manifest["archive_sha256"] = "d" * 64
    path = tmp_path / "artifact.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bundle.json", json.dumps(manifest))
        archive.write(payload, "bundle.tar.gz")
    ref = {
        "artifact_id": 34,
        "digest": bundle.digest(path),
        "run_id": 12,
        "source_sha": SHA,
        "repository": REPO,
        "identity": KEY,
    }
    return path, ref, manifest


def test_verified_bundle_unpacks_without_package_or_browser_downloads(tmp_path):
    path, ref, manifest = fixture_archive(tmp_path)
    result = bundle.unpack_artifact(path, ref, tmp_path / "unpacked", HOST)
    assert result == manifest
    assert (tmp_path / "unpacked/debs/fictional_1_all.deb").is_file()


@pytest.mark.parametrize(
    "damage", ["package", "baseline", "producer", "identity", "closure", "payload", "path"]
)
def test_corrupt_foreign_partial_or_incompatible_bundle_is_rejected(tmp_path, damage):
    path, ref, _ = fixture_archive(tmp_path, damage=damage)
    with pytest.raises((bundle.IntegrityError, tarfile.FilterError)):
        bundle.unpack_artifact(path, ref, tmp_path / "unpacked", HOST)
    assert not (tmp_path / "escaped").exists()


def test_artifact_digest_is_checked_before_extraction(tmp_path):
    path, ref, _ = fixture_archive(tmp_path)
    ref["digest"] = "c" * 64
    with pytest.raises(bundle.IntegrityError, match="digest mismatch"):
        bundle.unpack_artifact(path, ref, tmp_path / "unpacked", HOST)
    assert not (tmp_path / "unpacked").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository", "foreign/project"),
        ("source_sha", "not-a-sha"),
        ("run_id", 0),
        ("artifact_id", "34"),
        ("identity", "c" * 64),
    ],
)
def test_invalid_reference_is_rejected(field, value):
    ref = {
        "artifact_id": 34,
        "digest": "d" * 64,
        "run_id": 12,
        "source_sha": SHA,
        "repository": REPO,
        "identity": KEY,
    }
    ref[field] = value
    with pytest.raises(bundle.IntegrityError):
        bundle.validate_reference(ref, KEY, REPO)


def test_identity_binds_all_locked_inputs_and_producer_code(tmp_path):
    for name in bundle.IDENTITY_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
    key = bundle.identity(tmp_path)
    producer = tmp_path / ".github/actions/ci-prerequisite-bundle/action.yml"
    producer.write_text("changed producer")
    assert bundle.identity(tmp_path) != key


@pytest.mark.parametrize(
    "case", ["fresh", "expired", "near-expiry", "old", "pull-request", "sibling"]
)
def test_only_available_fresh_trusted_main_producer_can_be_reused(monkeypatch, case):
    now = datetime(2026, 10, 22, tzinfo=UTC)
    run = {
        "id": 12,
        "head_sha": SHA,
        "event": "push",
        "head_branch": "main",
        "conclusion": "success",
        "path": ".github/workflows/application.yml",
    }
    artifact = {
        "id": 34,
        "digest": "sha256:" + "d" * 64,
        "name": f"ci-prerequisites-v2-{KEY}-1",
        "expired": False,
        "created_at": (now - timedelta(hours=1)).isoformat(),
        "expires_at": (now + timedelta(days=3)).isoformat(),
    }
    if case == "expired":
        artifact["expired"] = True
    if case == "near-expiry":
        artifact["expires_at"] = (now + timedelta(hours=1)).isoformat()
    if case == "old":
        artifact["created_at"] = (now - timedelta(days=2)).isoformat()
    if case == "pull-request":
        run["event"] = "pull_request"
    if case == "sibling":
        run["head_branch"] = "wb-ci/sibling"
    monkeypatch.setattr(
        bundle,
        "github",
        lambda path: {"workflow_runs": [run]} if "/runs?" in path else {"artifacts": [artifact]},
    )
    ref = bundle.find_published(KEY, REPO, now)
    assert (ref is not None) == (case == "fresh")


def test_official_sources_are_isolated_signed_https_and_never_azure(tmp_path):
    options = bundle.official_options(tmp_path)
    sources = (tmp_path / "official.list").read_text()
    assert "azure" not in sources and "trusted=yes" not in sources
    assert all(origin in sources for origin in bundle.ORIGINS)
    assert "signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg" in sources
    assert "Dir::Etc::sourceparts=-" in options
    assert "APT::Get::AllowUnauthenticated=false" in options


def test_consumer_checks_empty_state_closure_then_compatible_baseline_without_downloads(
    tmp_path, monkeypatch
):
    installed = set()
    tool = SimpleNamespace(installed=lambda p: p in installed)
    calls = []

    def apt(tool, label, options, arguments, seconds=300):
        calls.append((label, options, arguments))
        if "install" in arguments and "--simulate" not in arguments:
            installed.add("fictional")

    monkeypatch.setattr(bundle, "apt", apt)
    bundle.install_offline(tool, tmp_path, ["fictional"])
    assert len(calls) == 4
    assert "Dir::State::status=" in " ".join(calls[1][1])
    assert "--simulate" in calls[1][2] and "--simulate" in calls[2][2]
    assert all("--no-download" in args and "--no-remove" in args for _, _, args in calls[1:])
    assert all("Dir::Etc::sourceparts=-" in options for _, options, _ in calls)
    assert (tmp_path / "offline.list").read_text().startswith("deb [trusted=yes] file:")


@pytest.mark.parametrize(
    "reuse", ["missing", "unavailable", "warm", "incompatible", "corrupt", "auth"]
)
def test_producer_recovery_is_bounded_and_never_accepts_corruption(tmp_path, monkeypatch, reuse):
    monkeypatch.setattr(sys, "argv", ["bundle", "prepare", "--directory", str(tmp_path)])
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "outputs"))
    monkeypatch.setattr(bundle, "identity", lambda _: KEY)
    monkeypatch.setattr(bundle, "require_runner", lambda: None)
    ref = {"producer": "fictional"}

    def find(*args):
        if reuse == "unavailable":
            raise bundle.PublisherUnavailable("expired")
        if reuse == "auth":
            raise bundle.BundleError("authentication failed")
        return None if reuse == "missing" else ref

    def consume(*args):
        if reuse == "incompatible":
            raise bundle.PrerequisiteError("offline solve failed")
        if reuse == "corrupt":
            raise bundle.IntegrityError("changed digest")

    builds = []
    monkeypatch.setattr(bundle, "find_published", find)
    monkeypatch.setattr(bundle, "consume", consume)
    monkeypatch.setattr(bundle, "prove", lambda *args: None)
    monkeypatch.setattr(bundle, "build", lambda *args: builds.append(args))
    monkeypatch.setattr(bundle, "admit_publication", lambda *args: None)
    assert bundle.main() == (1 if reuse in ("corrupt", "auth") else 0)
    assert bool(builds) == (reuse in ("missing", "unavailable", "incompatible"))


def test_workflow_producer_gates_every_offline_consumer_and_has_its_own_retention():
    for filename, consumers in [
        (
            "application.yml",
            (
                "validate-python-tests",
                "validate-python-gates",
                "validate-sales-xray-acquisition-browser",
            ),
        ),
        ("workbench-checks.yml", ("py-tests", "visual", "e2e")),
    ]:
        jobs = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"]
        producer = jobs["ci-prerequisites"]
        assert producer["outputs"]["bundle"] == "${{ steps.bundle.outputs.bundle }}"
        for name in consumers:
            assert "ci-prerequisites" in jobs[name]["needs"]
            step = next(
                s
                for s in jobs[name]["steps"]
                if s.get("uses") == "./.github/actions/ci-prerequisites"
            )
            assert step["with"]["bundle"] == "${{ needs.ci-prerequisites.outputs.bundle }}"
            assert not step.get("continue-on-error")
    producer = yaml.safe_load(
        (ROOT / ".github/actions/ci-prerequisite-bundle/action.yml").read_text()
    )
    upload = next(s for s in producer["runs"]["steps"] if s.get("id") == "upload")
    assert upload["with"]["retention-days"] == 2
    consumer = (ROOT / ".github/actions/ci-prerequisites/action.yml").read_text()
    assert "actions/cache" not in consumer and "consume --directory" in consumer
    assert "127.0.0.1 azure.archive.ubuntu.com" in consumer
    overlays = (ROOT / "scripts/ci/wb-ci").read_text().split("CI_FILES=(")[1].split(")")[0]
    assert "scripts/ci/ci_prerequisite_bundle.py" in overlays
    assert ".github/actions/ci-prerequisite-bundle/action.yml" in overlays


@pytest.mark.skipif(
    not shutil.which("apt-get") or not shutil.which("dpkg-deb"), reason="Debian tools"
)
def test_real_local_repository_solves_complete_closure_without_network(tmp_path):
    import pwd

    debs = tmp_path / "debs"
    debs.mkdir()
    controls = []
    for name, dependency in [("ac-bundle-dep", ""), ("ac-bundle-main", "ac-bundle-dep")]:
        package = tmp_path / name / "DEBIAN"
        package.mkdir(parents=True)
        control = (
            f"Package: {name}\nVersion: 1.0\nArchitecture: all\nMaintainer: CI <ci@example.test>\n"
            + (f"Depends: {dependency}\n" if dependency else "")
            + "Description: fictional fixture\n"
        )
        (package / "control").write_text(control)
        path = debs / f"{name}_1.0_all.deb"
        subprocess.run(  # noqa: S603 - fixed Debian tool, fictional fixture paths
            ["/usr/bin/dpkg-deb", "--build", str(package.parent), str(path)],
            check=True,
            capture_output=True,
        )  # noqa: S603
        controls.append(
            control
            + f"Filename: {path.name}\nSize: {path.stat().st_size}\nSHA256: {bundle.digest(path)}\n"
        )
    (debs / "Packages").write_text("\n".join(controls))
    parts = tmp_path / "config-parts"
    parts.mkdir()
    (tmp_path / "log").mkdir()
    empty = tmp_path / "empty"
    empty.touch()
    config = tmp_path / "apt.conf"
    config.write_text(f'Dir::Etc::parts "{parts}";\nDir::Etc::main "{empty}";\n')
    calls = tmp_path / "dpkg-argv"
    recorder = tmp_path / "dpkg-recorder"
    recorder.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" >> " + shlex.quote(str(calls)) + "\n")
    recorder.chmod(0o700)
    options = bundle.local_options(tmp_path)
    for key, value in [
        ("Dir::State", tmp_path / "state"),
        ("Dir::State::status", empty),
        ("Dir::Cache", tmp_path / "cache"),
        ("Dir::Log", tmp_path / "log"),
        ("Dir::Bin::dpkg", recorder),
        ("Debug::NoLocking", "1"),
        ("APT::Sandbox::User", pwd.getpwuid(os.getuid()).pw_name),
    ]:
        options.extend(["-o", f"{key}={value}"])
    command = ["/usr/bin/apt-get", *options]
    env = {**os.environ, "APT_CONFIG": str(config), "LC_ALL": "C"}

    def apt(*args):
        return subprocess.run(  # noqa: S603 - isolated apt state and fictional local repository
            [*command, *args], env=env, text=True, capture_output=True, timeout=30
        )  # noqa: S603

    updated = apt("update")
    assert updated.returncode == 0, updated.stdout + updated.stderr
    solved = apt("install", "--simulate", "--no-download", "--no-remove", "ac-bundle-main")
    assert solved.returncode == 0, solved.stdout + solved.stderr
    assert "Inst ac-bundle-dep" in solved.stdout and empty.read_text() == ""
    installed = apt("install", "--yes", "--no-download", "--no-remove", "ac-bundle-main")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "--unpack" in calls.read_text()
    assert "ac-bundle-dep_1.0_all.deb" in calls.read_text()
    assert "ac-bundle-main_1.0_all.deb" in calls.read_text()
    assert empty.read_text() == ""  # no system dpkg writes or maintainer hooks
    # A producer that omitted a dependency cannot pass the same real solver.
    (debs / "Packages").write_text(controls[1])
    shutil.rmtree(tmp_path / "local-lists")
    (tmp_path / "local-lists/partial").mkdir(parents=True)
    assert apt("update").returncode == 0
    assert apt("install", "--simulate", "--no-download", "ac-bundle-main").returncode != 0


def publication_artifact(*, artifact_id=34, key=KEY, age=1, expires=24, size=452_074_312):
    now = datetime.now(UTC)
    return {
        "id": artifact_id,
        "name": f"ci-prerequisites-v2-{key}-1",
        "digest": "sha256:" + "d" * 64,
        "workflow_run": {"id": 12, "head_sha": SHA},
        "size_in_bytes": size,
        "expired": False,
        "created_at": (now - timedelta(hours=age)).isoformat(),
        "expires_at": (now + timedelta(hours=expires)).isoformat(),
    }


def pinned_bootstrap(tmp_path, monkeypatch):
    pin = {
        "identity": KEY,
        "repository": REPO,
        "artifact_id": 34,
        "digest": "d" * 64,
        "run_id": 12,
        "source_sha": SHA,
        "reviewed_source_sha": "e" * 40,
    }
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps([pin]))
    monkeypatch.setattr(bundle, "BOOTSTRAP_FILE", path)
    run = {
        "id": 12,
        "head_sha": SHA,
        "event": "push",
        "path": ".github/workflows/workbench-checks.yml",
        "conclusion": "success",
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    artifact = publication_artifact()
    calls = []

    def github(path):
        calls.append(path)
        if "workflows/application.yml/runs?" in path:
            return {"workflow_runs": []}
        if "/actions/runs/" in path:
            return run
        if "/commits/" in path:
            return {
                "sha": SHA,
                "parents": [{"sha": "e" * 40}],
                "files": [{"filename": ".wb-ci/request.json"}],
            }
        return artifact

    monkeypatch.setattr(bundle, "github", github)
    return pin, run, artifact, calls


def test_no_main_reuses_only_exact_reviewed_bootstrap(tmp_path, monkeypatch):
    pin, _, _, calls = pinned_bootstrap(tmp_path, monkeypatch)
    assert bundle.find_published(KEY, REPO) == pin
    assert calls[-3:] == [
        f"repos/{REPO}/actions/runs/12",
        f"repos/{REPO}/commits/{SHA}?per_page=2",
        f"repos/{REPO}/actions/artifacts/34",
    ]
    assert bundle.find_published("c" * 64, REPO) is None
    assert bundle.find_published(KEY, "foreign/project") is None


@pytest.mark.parametrize(
    "damage", ["source", "run", "foreign", "pr", "workflow", "digest", "artifact", "review"]
)
def test_bootstrap_rejects_foreign_or_corrupt_pinned_producer(tmp_path, monkeypatch, damage):
    pin, run, artifact, _ = pinned_bootstrap(tmp_path, monkeypatch)
    if damage == "source":
        run["head_sha"] = "f" * 40
    elif damage == "run":
        run["id"] = 99
    elif damage == "foreign":
        run["head_repository"]["full_name"] = "foreign/project"
    elif damage == "pr":
        run["event"] = "pull_request"
    elif damage == "workflow":
        run["path"] = ".github/workflows/foreign.yml"
    elif damage == "digest":
        artifact["digest"] = "f" * 64
    elif damage == "artifact":
        artifact["workflow_run"]["head_sha"] = "f" * 40
    else:
        pin["reviewed_source_sha"] = "unreviewed"
        bundle.BOOTSTRAP_FILE.write_text(json.dumps([pin]))
    with pytest.raises(bundle.IntegrityError):
        bundle.find_published(KEY, REPO)


@pytest.mark.parametrize("case", ["expired", "near-expiry", "old"])
def test_bootstrap_expiry_allows_bounded_recovery(tmp_path, monkeypatch, case):
    _, _, artifact, _ = pinned_bootstrap(tmp_path, monkeypatch)
    artifact.update(
        publication_artifact(
            age=37 if case == "old" else 1, expires=1 if case == "near-expiry" else 24
        )
    )
    artifact["expired"] = case == "expired"
    assert bundle.find_published(KEY, REPO) is None
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    monkeypatch.setattr(bundle, "github", lambda _: {"total_count": 1, "artifacts": [artifact]})
    assert bundle.admit_publication(KEY, REPO)["retained_identity_publications"] == (
        case != "expired"
    )


def test_simultaneous_no_main_publishers_recheck_after_shared_ownership(monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    artifacts = []
    monkeypatch.setattr(
        bundle, "github", lambda _: {"total_count": len(artifacts), "artifacts": list(artifacts)}
    )
    barrier = threading.Barrier(2)
    ownership = threading.Lock()  # repository-wide job concurrency, asserted below

    def request():
        barrier.wait(timeout=5)
        with ownership:
            try:
                bundle.admit_publication(KEY, REPO)
            except bundle.PublicationDeclined as error:
                assert "duplicate publication declined" in str(error)
                return "declined"
            artifacts.append(publication_artifact())
            return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: request(), range(2)))
    assert sorted(outcomes) == ["declined", "published"]
    assert len(artifacts) == 1


@pytest.mark.parametrize(
    "case", ["diagnostics", "bundles", "identity", "ownership", "inventory", "pagination", "auth"]
)
def test_storage_admission_declines_without_acquisition_or_upload(monkeypatch, case):
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    artifacts = []
    total = 0
    if case == "diagnostics":
        artifacts = [
            {
                **publication_artifact(size=bundle.MAX_RETAINED_ARTIFACT_BYTES),
                "name": "release-evidence",
            }
        ]
    elif case == "bundles":
        artifacts = [publication_artifact(key="f" * 64, size=bundle.MAX_RETAINED_BUNDLE_BYTES)]
    elif case == "identity":
        artifacts = [publication_artifact(artifact_id=i, age=40, size=1) for i in (34, 35)]
    elif case == "ownership":
        monkeypatch.delenv("PREREQ_PUBLICATION_OWNER")
    elif case == "pagination":
        total = 10001
    calls = []

    def github(path):
        calls.append(path)
        if case == "inventory":
            raise bundle.PublisherUnavailable("inventory unavailable")
        if case == "auth":
            raise bundle.BundleError("authentication failed")
        return {"total_count": max(total, len(artifacts)), "artifacts": artifacts}

    monkeypatch.setattr(bundle, "github", github)
    with pytest.raises(bundle.BundleError):
        bundle.admit_publication(KEY, REPO)
    assert len(calls) <= 100
    if case == "ownership":
        assert calls == []


def test_inventory_is_complete_before_admission_and_rechecked_before_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    calls = []
    diagnostics = {**publication_artifact(size=1), "name": "fictional diagnostic"}

    def github(path):
        calls.append(path)
        return {
            "total_count": 101,
            "artifacts": [diagnostics] * (100 if path.endswith("&page=1") else 1),
        }

    monkeypatch.setattr(bundle, "github", github)
    assert bundle.admit_publication(KEY, REPO)["retained_artifact_bytes"] == 101
    assert len(calls) == 2
    (tmp_path / "publication.json").write_text(json.dumps({"identity": KEY, "recovery": None}))
    (tmp_path / "publish").mkdir()
    (tmp_path / "publish/bundle.tar.gz").write_bytes(b"fixture")
    monkeypatch.setattr(bundle, "identity", lambda _: KEY)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setattr(sys, "argv", ["bundle", "admit", "--directory", str(tmp_path)])
    monkeypatch.setattr(
        bundle, "github", lambda _: {"total_count": 1, "artifacts": [publication_artifact()]}
    )
    assert bundle.main() == 1  # a publisher appeared during acquisition: no upload


def test_baseline_recovery_is_limited_to_one_replacement(monkeypatch):
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    artifacts = [publication_artifact(size=1)]
    monkeypatch.setattr(
        bundle, "github", lambda _: {"total_count": len(artifacts), "artifacts": artifacts}
    )
    assert (
        bundle.admit_publication(KEY, REPO, {"artifact_id": 34})["retained_identity_publications"]
        == 1
    )
    artifacts.append(publication_artifact(artifact_id=35, size=1))
    with pytest.raises(bundle.PublicationDeclined, match="identity publication bound"):
        bundle.admit_publication(KEY, REPO, {"artifact_id": 35})


def test_oversize_bundle_is_declined_before_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle, "identity", lambda _: KEY)
    monkeypatch.setattr(bundle, "MAX_PUBLICATION_BYTES", 65540)
    (tmp_path / "publication.json").write_text(json.dumps({"identity": KEY, "recovery": None}))
    (tmp_path / "publish").mkdir()
    (tmp_path / "publish/bundle.tar.gz").write_bytes(b"too big")
    monkeypatch.setattr(sys, "argv", ["bundle", "admit", "--directory", str(tmp_path)])
    assert bundle.main() == 1


def test_publication_lock_spans_prepare_admission_upload_and_reference_in_both_workflows():
    for filename in ("application.yml", "workbench-checks.yml"):
        job = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"][
            "ci-prerequisites"
        ]
        assert job["concurrency"] == {
            "group": bundle.PUBLICATION_OWNER,
            "cancel-in-progress": False,
        }
        assert job["env"]["PREREQ_PUBLICATION_OWNER"] == bundle.PUBLICATION_OWNER
        assert any(
            s.get("uses") == "./.github/actions/ci-prerequisite-bundle" for s in job["steps"]
        )
    steps = yaml.safe_load(
        (ROOT / ".github/actions/ci-prerequisite-bundle/action.yml").read_text()
    )["runs"]["steps"]
    prepare = next(i for i, s in enumerate(steps) if s.get("id") == "prepare")
    admit = next(i for i, s in enumerate(steps) if " admit --directory" in s.get("run", ""))
    upload = next(i for i, s in enumerate(steps) if s.get("id") == "upload")
    reference = next(i for i, s in enumerate(steps) if s.get("id") == "reference")
    assert prepare < admit < upload < reference
    assert steps[admit]["if"] == steps[upload]["if"]
    assert not steps[admit].get("continue-on-error")
    assert (
        "scripts/ci/ci-prerequisite-bootstrap.json"
        in (ROOT / "scripts/ci/wb-ci").read_text().split("CI_FILES=(")[1].split(")")[0]
    )
    assert "scripts/ci/ci-prerequisite-bootstrap.json" not in bundle.IDENTITY_FILES


@pytest.mark.parametrize("damage", ["parent", "overlay"])
def test_bootstrap_producer_must_be_exact_reviewed_source_plus_request(
    tmp_path, monkeypatch, damage
):
    pinned_bootstrap(tmp_path, monkeypatch)
    original = bundle.github

    def github(path):
        result = original(path)
        if "/commits/" in path:
            if damage == "parent":
                result["parents"] = [{"sha": "f" * 40}]
            else:
                result["files"].append({"filename": "scripts/ci/ci_prerequisite_bundle.py"})
        return result

    monkeypatch.setattr(bundle, "github", github)
    with pytest.raises(bundle.IntegrityError, match="differs from the reviewed source"):
        bundle.find_published(KEY, REPO)


def test_no_main_existing_unreviewed_bundle_prevents_another_build(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bundle", "prepare", "--directory", str(tmp_path)])
    monkeypatch.setattr(bundle, "require_runner", lambda: None)
    monkeypatch.setattr(bundle, "identity", lambda _: KEY)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("PREREQ_PUBLICATION_OWNER", bundle.PUBLICATION_OWNER)
    calls = []

    def github(path):
        calls.append(path)
        if "/workflows/" in path:
            return {"workflow_runs": []}
        return {"total_count": 1, "artifacts": [publication_artifact()]}

    monkeypatch.setattr(bundle, "github", github)
    builds = []
    monkeypatch.setattr(bundle, "build", lambda *args: builds.append(args))
    assert bundle.main() == 1
    assert builds == []
    assert not (tmp_path / "publication.json").exists()
