#!/usr/bin/env python3
"""AC release engine: install verified main builds on staging, then production.

The engine runs on the VPS as root from a systemd timer. It never builds
anything. It downloads the exact bundles that CI produced for a commit on
``main``, keeps an immutable local copy, and runs the same source-owned
installers the laptop deploy script used to run over SSH.

Commands (``ac-release <command>``):

    status [--json]                 what runs where, pause state, last results
    tick                            timer entry point: auto-deploy staging
    deploy ENV [SHA] [--component core|web|all] [--dry-run]
    pause ENV | resume ENV          stop or restart automatic deploys
    rollback ENV --component web    restore the previous Sales Xray web image
    history [-n N]                  recent deploy records

Production deploys are refused unless ``/etc/ac-release/production.enabled``
exists and the same commit already passed staging.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows test hosts do not expose flock.
    fcntl = None  # type: ignore[assignment]

REPOSITORY = "authorityclosers/authority-closers-platform"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
API_ROOT = "https://api.github.com"
ENVIRONMENTS = ("staging", "production")
COMPONENTS = ("core", "web")
CORE_WORKFLOW = "application.yml"
WEB_WORKFLOW = "sales-xray-web-image.yml"
CORE_FILES = frozenset({"SHA256SUMS", "application-images.tar.gz", "release-images.env"})
WEB_FILES = frozenset({"SHA256SUMS", "web-image.env", "web-image.json", "web-image.tar.gz"})
MAX_ARTIFACT_BYTES = 450_000_000
# Stored bundles are several hundred MB each. Keep whatever runs in staging or
# production plus this many recent successful deploys (rollback and promotion).
KEEP_RECENT_BUILDS = 10
SHA_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(r"sha256:[0-9a-f]{64}")
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EDGE = "http://127.0.0.1:8080"


class ReleaseError(RuntimeError):
    """A deploy step failed; the message is safe to show and record."""


@dataclass(frozen=True)
class Paths:
    """Every location the engine touches, overridable for tests."""

    state: Path = Path("/var/lib/ac-release")
    logs: Path = Path("/var/log/ac-release")
    store: Path = Path("/srv/authority-closers/release-store")
    config: Path = Path("/etc/ac-release")
    application: Path = Path("/srv/authority-closers/application")
    stage_root: Path = Path("/var/tmp")  # noqa: S108 - root-only mkdtemp stages (0700)
    lock: Path = Path("/run/ac-release.lock")

    @property
    def mirror(self) -> Path:
        return self.state / "mirror.git"

    @property
    def token(self) -> Path:
        return self.config / "github-actions-read.token"

    @property
    def history(self) -> Path:
        return self.state / "history.jsonl"

    def paused_flag(self, environment: str) -> Path:
        return self.state / f"{environment}.paused"

    def failed_flag(self, environment: str, component: str) -> Path:
        return self.state / f"{environment}-{component}.failed"

    @property
    def production_enabled(self) -> Path:
        return self.config / "production.enabled"


# ---------------------------------------------------------------------------
# GitHub access


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class GitHub:
    """Read-only GitHub API client. The token never leaves api.github.com."""

    def __init__(self, token: str, *, timeout: float = 60.0) -> None:
        if not token or any(ch.isspace() for ch in token):
            raise ReleaseError("GitHub token is missing or malformed")
        self._token = token
        self._timeout = timeout
        self._api = urllib.request.build_opener(_NoRedirect)
        self._plain = urllib.request.build_opener(_NoRedirect)

    def _request(self, url: str, *, authenticated: bool) -> urllib.request.Request:
        request = urllib.request.Request(url)  # noqa: S310 - https GitHub and signed storage only
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "ac-release")
        if authenticated:
            request.add_header("Authorization", f"Bearer {self._token}")
        return request

    def get_json(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        if not path.startswith("/repos/"):
            raise ReleaseError("unexpected GitHub API path")
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            with self._api.open(
                self._request(url, authenticated=True), timeout=self._timeout
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ReleaseError(f"GitHub API {path} returned {error.code}") from None
        except urllib.error.URLError as error:
            raise ReleaseError(f"GitHub API {path} is unreachable: {error.reason}") from None

    def download_artifact(self, artifact_id: int, destination: Path, expected_digest: str) -> None:
        """Download an artifact zip, following one redirect without credentials."""

        path = f"/repos/{REPOSITORY}/actions/artifacts/{int(artifact_id)}/zip"
        location: str | None = None
        try:
            with self._api.open(
                self._request(API_ROOT + path, authenticated=True), timeout=self._timeout
            ) as response:
                _stream_to(response, destination, expected_digest)
                return
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise ReleaseError(f"artifact download returned {error.code}") from None
            location = error.headers.get("Location")
        if not location or urllib.parse.urlsplit(location).scheme != "https":
            raise ReleaseError("artifact download redirect is not HTTPS")
        # The signed storage URL is the credential; sending the GitHub token to
        # another host would leak it, so this request is unauthenticated.
        try:
            with self._plain.open(
                self._request(location, authenticated=False), timeout=self._timeout
            ) as response:
                _stream_to(response, destination, expected_digest)
        except urllib.error.HTTPError as error:
            raise ReleaseError(f"artifact storage returned {error.code}") from None


def _stream_to(response: Any, destination: Path, expected_digest: str) -> None:
    digest = hashlib.sha256()
    size = 0
    with destination.open("xb") as handle:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise ReleaseError("artifact is larger than the release ceiling")
            digest.update(chunk)
            handle.write(chunk)
    if f"sha256:{digest.hexdigest()}" != expected_digest:
        raise ReleaseError("downloaded artifact does not match its GitHub digest")


@dataclass(frozen=True)
class Build:
    """A successful CI run on main and its verified artifact metadata."""

    sha: str
    run_id: int
    artifact_id: int
    artifact_name: str
    artifact_digest: str


def find_push_run(github: Any, workflow: str, sha: str) -> dict[str, Any] | None:
    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/workflows/{workflow}/runs",
        {"branch": "main", "event": "push", "head_sha": sha, "per_page": "20"},
    )
    runs = [
        run
        for run in data.get("workflow_runs", [])
        if run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("head_branch") == "main"
        and run.get("path") == f".github/workflows/{workflow}"
        and run.get("repository", {}).get("full_name") == REPOSITORY
    ]
    if not runs:
        return None
    return max(runs, key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0)))


def find_artifact(
    github: Any, run: Mapping[str, Any], name: str, sha: str
) -> dict[str, Any] | None:
    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{int(run['id'])}/artifacts", {"name": name}
    )
    matches = [
        artifact
        for artifact in data.get("artifacts", [])
        if artifact.get("name") == name
        and not artifact.get("expired", True)
        and artifact.get("workflow_run", {}).get("id") == run["id"]
        and artifact.get("workflow_run", {}).get("head_sha") == sha
        and DIGEST_RE.fullmatch(str(artifact.get("digest") or ""))
        and 0 < int(artifact.get("size_in_bytes") or 0) <= MAX_ARTIFACT_BYTES
    ]
    if len(matches) != 1:
        return None
    return matches[0]


@dataclass(frozen=True)
class Candidate:
    """What CI says about one commit: waiting, failed, or ready with a build."""

    state: str  # "ready" | "building" | "failed" | "missing"
    build: Build | None = None
    detail: str = ""


def core_candidate(github: Any, sha: str) -> Candidate:
    run = find_push_run(github, CORE_WORKFLOW, sha)
    if run is None:
        return Candidate("missing", detail="no validation run for this commit yet")
    if run.get("status") != "completed":
        return Candidate("building", detail=f"validation run {run['id']} is {run.get('status')}")
    if run.get("conclusion") != "success":
        return Candidate("failed", detail=f"validation run {run['id']} {run.get('conclusion')}")
    name = f"ac-application-{sha}"
    artifact = find_artifact(github, run, name, sha)
    if artifact is None:
        return Candidate("failed", detail=f"run {run['id']} has no usable {name} artifact")
    return Candidate(
        "ready",
        Build(sha, int(run["id"]), int(artifact["id"]), name, str(artifact["digest"])),
    )


def validated(github: Any, sha: str) -> bool:
    """True when the full validation workflow for this main commit succeeded."""

    run = find_push_run(github, CORE_WORKFLOW, sha)
    return bool(run and run.get("status") == "completed" and run.get("conclusion") == "success")


def web_build_for(github: Any, sha: str) -> Build | None:
    run = find_push_run(github, WEB_WORKFLOW, sha)
    if run is None or run.get("status") != "completed" or run.get("conclusion") != "success":
        return None
    name = f"ac-sales-xray-web-{sha}"
    artifact = find_artifact(github, run, name, sha)
    if artifact is None:
        return None
    return Build(sha, int(run["id"]), int(artifact["id"]), name, str(artifact["digest"]))


def recent_web_shas(github: Any) -> list[str]:
    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/workflows/{WEB_WORKFLOW}/runs",
        {"branch": "main", "event": "push", "status": "success", "per_page": "20"},
    )
    shas: list[str] = []
    for run in data.get("workflow_runs", []):
        sha = str(run.get("head_sha", ""))
        if SHA_RE.fullmatch(sha) and sha not in shas:
            shas.append(sha)
    return shas


# ---------------------------------------------------------------------------
# Local commands


Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_command(
    argv: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    log: Path | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": SAFE_PATH,
        "HOME": "/root",
        "LANG": "C.UTF-8",
        "USER": "root",
        "LOGNAME": "root",
    }
    if env:
        base.update(env)
    completed = subprocess.run(  # noqa: S603 - argv lists built from reviewed constants
        list(argv),
        env=base,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if log is not None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {' '.join(argv)}\n{completed.stdout}{completed.stderr}\n")
    if check and completed.returncode != 0:
        raise ReleaseError(f"{Path(argv[0]).name} exited with {completed.returncode}")
    return completed


# ---------------------------------------------------------------------------
# Engine


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_writable_and_retry(
    function: Callable[..., Any], path: str, _error: BaseException
) -> None:
    """Stored bundles are read-only; allow pruning them."""

    parent = Path(path).parent
    parent.chmod(0o700)
    with contextlib.suppress(OSError):
        Path(path).chmod(0o700)
    function(path)


def extract_exact(zip_path: Path, destination: Path, expected: frozenset[str]) -> None:
    """Extract exactly the expected flat file set, refusing anything else."""

    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if sorted(names) != sorted(expected) or len(set(names)) != len(names):
            raise ReleaseError("artifact does not contain exactly the expected files")
        for member in members:
            if member.is_dir() or "/" in member.filename or "\\" in member.filename:
                raise ReleaseError("artifact contains an unsafe entry")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ReleaseError("artifact contains a symbolic link")
            with (
                archive.open(member) as source,
                (destination / member.filename).open("xb") as target,
            ):
                shutil.copyfileobj(source, target, 1024 * 1024)
    verify_checksums(destination, expected - {"SHA256SUMS"})


def verify_checksums(directory: Path, covered: frozenset[str]) -> None:
    seen: set[str] = set()
    for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?([^/\\\s]+)", line.strip())
        if match is None or match.group(2) in seen or match.group(2) not in covered:
            raise ReleaseError("SHA256SUMS contains an unexpected or malformed entry")
        if _sha256_file(directory / match.group(2)) != match.group(1):
            raise ReleaseError(f"checksum failed for {match.group(2)}")
        seen.add(match.group(2))
    if seen != set(covered):
        raise ReleaseError("SHA256SUMS does not cover the complete bundle")


@dataclass
class Engine:
    paths: Paths = field(default_factory=Paths)
    github: Any = None
    run: Runner = run_command
    sleep: Callable[[float], None] = time.sleep

    # -- state ---------------------------------------------------------------

    def is_paused(self, environment: str) -> bool:
        return self.paths.paused_flag(environment).exists()

    def set_paused(self, environment: str, paused: bool, reason: str = "") -> None:
        flag = self.paths.paused_flag(environment)
        if paused:
            flag.write_text(json.dumps({"at": _now(), "reason": reason}) + "\n", encoding="utf-8")
        else:
            flag.unlink(missing_ok=True)
            for component in COMPONENTS:
                self.paths.failed_flag(environment, component).unlink(missing_ok=True)

    def failed_sha(self, environment: str, component: str) -> str | None:
        flag = self.paths.failed_flag(environment, component)
        return flag.read_text(encoding="utf-8").strip() if flag.exists() else None

    def record(self, entry: Mapping[str, Any]) -> None:
        self.paths.state.mkdir(parents=True, exist_ok=True)
        with self.paths.history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(entry), sort_keys=True) + "\n")

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.paths.history.exists():
            return []
        lines = self.paths.history.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]

    def passed_staging(self, sha: str) -> bool:
        return any(
            entry.get("environment") == "staging"
            and entry.get("component") == "core"
            and entry.get("sha") == sha
            and entry.get("result") == "success"
            for entry in self.history(10_000)
        )

    # -- what runs where -----------------------------------------------------

    def current_core(self, environment: str) -> str | None:
        link = self.paths.application / f"current-{environment}"
        with contextlib.suppress(OSError):
            name = Path(os.path.realpath(link)).name
            if SHA_RE.fullmatch(name):
                return name
        return None

    def web_container(self, environment: str) -> str:
        return f"ac-sales-xray-web-{environment}-sales-xray-web-1"

    def current_web(self, environment: str) -> tuple[str | None, str | None]:
        """Return (release sha, image id) of the running Sales Xray web container."""

        container = self.web_container(environment)
        inspected = self.run(
            ["docker", "inspect", "--format", "{{.Image}}", container], check=False
        )
        image = inspected.stdout.strip()
        if inspected.returncode != 0 or not IMAGE_REF_RE.fullmatch(image):
            return None, None
        return self.image_release(image), image

    def image_release(self, image: str) -> str | None:
        """Read the baked release id once per image and remember it."""

        cache_path = self.paths.state / "image-releases.json"
        cache: dict[str, str] = {}
        with contextlib.suppress(OSError, ValueError):
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if image in cache:
            return cache[image]
        marker = self.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "cat",
                image,
                "/app/.ac-release-id",
            ],
            check=False,
        )
        sha = marker.stdout.strip()
        if marker.returncode != 0 or not SHA_RE.fullmatch(sha):
            return None
        cache[image] = sha
        self.paths.state.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, sort_keys=True) + "\n", encoding="utf-8")
        return sha

    def main_head(self) -> str:
        self.sync_mirror()
        head = self.run(
            ["git", f"--git-dir={self.paths.mirror}", "rev-parse", "refs/heads/main"]
        ).stdout.strip()
        if not SHA_RE.fullmatch(head):
            raise ReleaseError("could not resolve main")
        return head

    def sync_mirror(self) -> None:
        if not (self.paths.mirror / "HEAD").exists():
            self.paths.mirror.parent.mkdir(parents=True, exist_ok=True)
            self.run(["git", "init", "--quiet", "--bare", str(self.paths.mirror)])
        self.run(
            [
                "git",
                f"--git-dir={self.paths.mirror}",
                "fetch",
                "--quiet",
                "--prune",
                REPOSITORY_URL,
                "+refs/heads/main:refs/heads/main",
            ],
            timeout=300,
        )

    def is_ancestor(self, older: str, newer: str) -> bool:
        return (
            self.run(
                [
                    "git",
                    f"--git-dir={self.paths.mirror}",
                    "merge-base",
                    "--is-ancestor",
                    older,
                    newer,
                ],
                check=False,
            ).returncode
            == 0
        )

    # -- artifacts -------------------------------------------------------------

    def store_bundle(self, build: Build, component: str, expected: frozenset[str]) -> Path:
        """Download once into the immutable local store and return its path."""

        target = self.paths.store / build.sha / component
        provenance = target / "provenance.json"
        if provenance.exists():
            verify_checksums(target, expected - {"SHA256SUMS"})
            return target
        if target.exists():
            # A crash can leave a partial copy without provenance; start over.
            shutil.rmtree(target)
        if self.github is None:
            raise ReleaseError(f"no stored {component} bundle for {build.sha} and no GitHub access")
        self.paths.store.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.paths.store, prefix=".download-") as work:
            work_path = Path(work)
            zip_path = work_path / "artifact.zip"
            self.github.download_artifact(build.artifact_id, zip_path, build.artifact_digest)
            unpacked = work_path / component
            unpacked.mkdir()
            extract_exact(zip_path, unpacked, expected)
            (unpacked / "provenance.json").write_text(
                json.dumps(
                    {
                        "sha": build.sha,
                        "run_id": build.run_id,
                        "artifact_id": build.artifact_id,
                        "artifact_name": build.artifact_name,
                        "artifact_digest": build.artifact_digest,
                        "stored_at": _now(),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(unpacked, target)
        for item in [target, *target.iterdir()]:
            item.chmod(0o500 if item.is_dir() else 0o400)
        return target

    def source_archive(self, sha: str, stage: Path, prefix: str) -> tuple[Path, str]:
        archive = stage / f"ac-{prefix.replace('/', '-')}-{sha}.tar"
        self.run(
            [
                "git",
                f"--git-dir={self.paths.mirror}",
                "archive",
                "--format=tar",
                f"--output={archive}",
                sha,
                "--",
                prefix,
            ]
        )
        return archive, _sha256_file(archive)

    @staticmethod
    def extract_source(archive: Path, destination: Path, prefix: str) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as handle:
            members = [m for m in handle.getmembers() if m.name.startswith(prefix)]
            handle.extractall(destination, members=members, filter="data")

    @contextlib.contextmanager
    def stage(self, sha: str) -> Iterator[Path]:
        path = Path(tempfile.mkdtemp(prefix=f"ac-release-{sha}.", dir=self.paths.stage_root))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def new_log(self, environment: str, component: str, sha: str) -> Path:
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        return self.paths.logs / f"{stamp}-{environment}-{component}-{sha[:12]}.log"

    # -- core ------------------------------------------------------------------

    def deploy_core(
        self, environment: str, build: Build, *, dry_run: bool = False
    ) -> dict[str, Any]:
        log = self.new_log(environment, "core", build.sha)
        bundle = self.store_bundle(build, "core", CORE_FILES)
        previous = self.current_core(environment)
        with self.stage(build.sha) as stage:
            archive, archive_sha = self.source_archive(build.sha, stage, "infra/application")
            source = stage / "source"
            self.extract_source(archive, source, "infra/application")
            self.run(
                [
                    "python3",
                    str(source / "infra/application/scripts/verify-release-archive.py"),
                    str(archive),
                    archive_sha,
                    build.sha,
                ],
                log=log,
            )
            bundle_dir = stage / "bundle"
            bundle_dir.mkdir()
            for name in sorted(CORE_FILES):
                shutil.copyfile(bundle / name, bundle_dir / name)
            installer = source / "infra/application/scripts/install-application-release.sh"
            env = {
                "AC_TARGET_ENVIRONMENT": environment,
                "AC_RELEASE_ID": build.sha,
                "AC_RELEASE_ARCHIVE": str(archive),
                "AC_RELEASE_ARCHIVE_SHA256": archive_sha,
                "AC_IMAGE_BUNDLE_DIR": str(bundle_dir),
            }
            if dry_run:
                return {
                    "dry_run": True,
                    "previous": previous,
                    "installer": str(installer),
                    "log": str(log),
                }
            completed = self.run(
                ["bash", str(installer)], env=env, log=log, check=False, timeout=3600
            )
            status = re.findall(r"^AC_STATUS=([A-Z_]+)$", completed.stdout, flags=re.MULTILINE)
            if completed.returncode != 0:
                raise ReleaseError(
                    f"installer exited with {completed.returncode}"
                    + (f" ({status[-1]})" if status else "")
                    + f"; see {log}"
                )
        self.check_core(environment, build.sha, log)
        return {"previous": previous, "log": str(log)}

    def check_core(self, environment: str, sha: str, log: Path) -> None:
        release_dir = self.paths.application / "releases" / sha
        if self.current_core(environment) != sha:
            raise ReleaseError(f"current-{environment} does not point at {sha}")
        self.run(
            ["sha256sum", "--check", "--quiet", "RELEASE-FILES.sha256"], cwd=release_dir, log=log
        )
        images: dict[str, str] = {}
        for line in (release_dir / "release-images.env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            images[key] = value
        project = f"ac-application-{environment}"
        checks = [
            ("api", images.get("AC_API_IMAGE"), True, True),
            ("worker", images.get("AC_API_IMAGE"), False, True),
            ("learner-web", images.get("AC_LEARNER_IMAGE"), True, False),
            ("admin-web", images.get("AC_ADMIN_IMAGE"), True, False),
            ("coach-web", images.get("AC_COACH_IMAGE"), True, False),
        ]
        for service, image, healthy, release_env in checks:
            self.wait_for_container(
                f"{project}-{service}-1", image, healthy, sha if release_env else None, log
            )
        suffix = "-staging" if environment == "staging" else ""
        self.expect_http(
            f"learner{suffix}.authorityclosers.com", "/", 200, f"learner-{environment}"
        )
        self.expect_http(f"learner{suffix}.authorityclosers.com", "/healthz", 200, None)
        api = f"api{suffix}.authorityclosers.com"
        self.expect_http(api, "/health/live", 200, f"api-{environment}")
        self.expect_http(api, "/health/ready", 200, f"api-{environment}")
        self.expect_http(api, "/v1/programs", 200, f"api-{environment}")
        self.expect_http(api, "/docs", 404, f"api-{environment}")
        self.expect_http(api, "/openapi.json", 404, f"api-{environment}")
        self.expect_http(
            f"coach{suffix}.authorityclosers.com", "/login", 200, f"coach-{environment}"
        )

    def wait_for_container(
        self, container: str, image: str | None, healthy: bool, release: str | None, log: Path
    ) -> None:
        if not image:
            raise ReleaseError(f"release manifest has no image for {container}")
        fmt = "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.Image}}"
        last = ""
        for _ in range(60):
            result = self.run(["docker", "inspect", "--format", fmt, container], check=False)
            last = result.stdout.strip()
            state, _, rest = last.partition("|")
            health, _, actual = rest.partition("|")
            if state == "running" and actual == image and (not healthy or health == "healthy"):
                break
            self.sleep(5)
        else:
            raise ReleaseError(f"{container} is not running the release image healthily ({last})")
        if release is not None:
            env = self.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{range .Config.Env}}{{println .}}{{end}}",
                    container,
                ]
            ).stdout.splitlines()
            if f"AC_RELEASE_ID={release}" not in env:
                raise ReleaseError(f"{container} does not carry AC_RELEASE_ID={release}")
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"PASS {container}\n")

    def expect_http(self, host: str, path: str, status: int, route: str | None) -> str:
        result = self.run(
            [
                "curl",
                "--silent",
                "--show-error",
                "--max-time",
                "20",
                "--output",
                "-",
                "--write-out",
                "\n%{http_code} %header{x-authority-closers-route}",
                "--header",
                f"Host: {host}",
                f"{EDGE}{path}",
            ],
            check=False,
        )
        body, _, trailer = result.stdout.rpartition("\n")
        code, _, actual_route = trailer.partition(" ")
        if code != str(status) or (route is not None and actual_route.strip() != route):
            raise ReleaseError(
                f"{host}{path} returned {code} [{actual_route.strip()}], expected {status}"
            )
        return body

    # -- web -------------------------------------------------------------------

    def deploy_web(
        self, environment: str, build: Build, *, dry_run: bool = False
    ) -> dict[str, Any]:
        log = self.new_log(environment, "web", build.sha)
        bundle = self.store_bundle(build, "web", WEB_FILES)
        previous_sha, previous_image = self.current_web(environment)
        inputs = self.paths.application / "operator-inputs" / f"sales-xray-web-{build.sha}"
        with self.stage(build.sha) as stage:
            archive, archive_sha = self.source_archive(build.sha, stage, "infra/sales-xray-web")
            if inputs.exists():
                shutil.rmtree(inputs)
            inputs.mkdir(parents=True, mode=0o750)
            self.extract_source(archive, inputs / "source", "infra/sales-xray-web")
            source = inputs / "source" / "infra" / "sales-xray-web"
            proof = json.loads(
                self.run(
                    [
                        "python3",
                        str(source / "verify-artifact.py"),
                        "--artifact-dir",
                        str(bundle),
                        "--source-sha40",
                        build.sha,
                        "--metadata-sha256",
                        _sha256_file(bundle / "web-image.json"),
                    ],
                    log=log,
                ).stdout
            )
            runtime_ref = str(proof.get("runtime_ref", ""))
            if proof.get("verified_source") != build.sha or not IMAGE_REF_RE.fullmatch(runtime_ref):
                raise ReleaseError("web artifact verification did not bind this commit")
            if dry_run:
                shutil.rmtree(inputs, ignore_errors=True)
                return {
                    "dry_run": True,
                    "previous": previous_sha,
                    "runtime_ref": runtime_ref,
                    "log": str(log),
                }
            self.run(
                ["docker", "load", "--quiet", "--input", str(bundle / "web-image.tar.gz")], log=log
            )
            marker = self.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--entrypoint",
                    "cat",
                    runtime_ref,
                    "/app/.ac-release-id",
                ],
                log=log,
            ).stdout.strip()
            if marker != build.sha:
                raise ReleaseError("web image release marker does not match the commit")
            self.image_release(runtime_ref)
            verified = inputs / "verified-runtime.env"
            verified.write_text(f"AC_WEB_IMAGE={runtime_ref}\n", encoding="utf-8")
            rollback = inputs / "rollback-runtime.env"
            if previous_image:
                rollback.write_text(f"AC_WEB_IMAGE={previous_image}\n", encoding="utf-8")
            (inputs / "archive.sha256").write_text(archive_sha + "\n", encoding="utf-8")
        try:
            self.compose_web(environment, source, verified, log)
            self.check_web(environment, build.sha, runtime_ref, log)
        except ReleaseError:
            if previous_image and rollback.exists():
                self.compose_web(environment, source, rollback, log)
                raise ReleaseError(f"web deploy failed and was rolled back; see {log}") from None
            raise
        return {
            "previous": previous_sha,
            "previous_image": previous_image,
            "runtime_ref": runtime_ref,
            "log": str(log),
        }

    def compose_web(self, environment: str, source: Path, runtime_env: Path, log: Path) -> None:
        self.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(source / "environments" / f"{environment}.env"),
                "--env-file",
                str(runtime_env),
                "-f",
                str(source / "compose.yaml"),
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "90",
            ],
            cwd=source,
            log=log,
            timeout=300,
        )

    def check_web(self, environment: str, sha: str, runtime_ref: str, log: Path) -> None:
        suffix = "-staging" if environment == "staging" else ""
        self.wait_for_container(self.web_container(environment), runtime_ref, True, None, log)
        body = self.expect_http(f"salesxray{suffix}.authorityclosers.com", "/health", 200, None)
        with contextlib.suppress(ValueError):
            if json.loads(body).get("release_id") == sha:
                return
        raise ReleaseError("Sales Xray web /health does not report the new release")

    def rollback_web(self, environment: str) -> dict[str, Any]:
        _, image = self.current_web(environment)
        for entry in reversed(self.history(10_000)):
            if (
                entry.get("environment") == environment
                and entry.get("component") == "web"
                and entry.get("result") == "success"
                and entry.get("previous_image")
                and entry.get("runtime_ref") == image
            ):
                inputs = (
                    self.paths.application / "operator-inputs" / f"sales-xray-web-{entry['sha']}"
                )
                source = inputs / "source" / "infra" / "sales-xray-web"
                log = self.new_log(environment, "web-rollback", entry["sha"])
                self.compose_web(environment, source, inputs / "rollback-runtime.env", log)
                self.wait_for_container(
                    self.web_container(environment), entry["previous_image"], True, None, log
                )
                return {
                    "restored_image": entry["previous_image"],
                    "restored_sha": entry.get("previous"),
                    "log": str(log),
                }
        raise ReleaseError("no recorded web deploy with a previous image to restore")

    # -- orchestration -------------------------------------------------------

    @contextlib.contextmanager
    def locked(self, *, wait: bool) -> Iterator[bool]:
        self.paths.lock.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.lock.open("a") as handle:
            if fcntl is None:
                yield True
                return
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def attempt(
        self, environment: str, component: str, build: Build, *, dry_run: bool, trigger: str
    ) -> dict[str, Any]:
        started = time.monotonic()
        entry: dict[str, Any] = {
            "at": _now(),
            "environment": environment,
            "component": component,
            "sha": build.sha,
            "run_id": build.run_id,
            "trigger": trigger,
        }
        try:
            deploy = self.deploy_core if component == "core" else self.deploy_web
            entry.update(deploy(environment, build, dry_run=dry_run))
            entry["result"] = "dry-run" if dry_run else "success"
        except (ReleaseError, OSError, subprocess.SubprocessError, ValueError) as error:
            entry["result"] = "failed"
            entry["error"] = str(error)[:500]
            if not dry_run:
                self.paths.failed_flag(environment, component).write_text(
                    build.sha + "\n", encoding="utf-8"
                )
                if component == "core":
                    self.set_paused(environment, True, f"core deploy of {build.sha[:12]} failed")
        entry["duration_s"] = round(time.monotonic() - started, 1)
        if not dry_run:
            self.record(entry)
            if entry["result"] == "success":
                with contextlib.suppress(OSError):
                    entry["pruned"] = self.prune_store()
        return entry

    def prune_store(self) -> list[str]:
        """Keep what runs anywhere plus the most recent successful deploys."""

        keep: set[str | None] = set()
        for environment in ENVIRONMENTS:
            keep.add(self.current_core(environment))
            keep.add(self.current_web(environment)[0])
        recent: list[str] = []
        for entry in reversed(self.history(10_000)):
            sha = entry.get("sha")
            if entry.get("result") == "success" and sha and sha not in recent:
                recent.append(sha)
                if len(recent) >= KEEP_RECENT_BUILDS:
                    break
        keep.update(recent)
        removed: list[str] = []
        if not self.paths.store.exists():
            return removed
        for entry_path in sorted(self.paths.store.iterdir()):
            if SHA_RE.fullmatch(entry_path.name) and entry_path.name not in keep:
                shutil.rmtree(entry_path, onexc=_make_writable_and_retry)
                removed.append(entry_path.name)
        return removed

    def tick(self) -> list[dict[str, Any]]:
        """Timer entry point: bring staging up to the latest good main build."""

        environment = "staging"
        if self.is_paused(environment):
            return []
        with self.locked(wait=False) as acquired:
            if not acquired:
                return []
            head = self.main_head()
            results: list[dict[str, Any]] = []
            if (
                self.current_core(environment) != head
                and self.failed_sha(environment, "core") != head
            ):
                candidate = core_candidate(self.github, head)
                if candidate.state == "ready" and candidate.build is not None:
                    results.append(
                        self.attempt(
                            environment, "core", candidate.build, dry_run=False, trigger="auto"
                        )
                    )
                    if results[-1]["result"] != "success":
                        return results
            web = self.web_target(environment, head)
            if web is not None and self.failed_sha(environment, "web") != web.sha:
                results.append(self.attempt(environment, "web", web, dry_run=False, trigger="auto"))
            return results

    def web_target(self, environment: str, head: str) -> Build | None:
        """Newest successful web build on main that is newer than what runs."""

        current_sha, _ = self.current_web(environment)
        for sha in recent_web_shas(self.github):
            if sha == current_sha:
                return None
            if not self.is_ancestor(sha, head):
                continue
            # Skip only builds that are older than the running image. A running
            # commit outside main's history (for example before a squash merge)
            # counts as outdated.
            if current_sha and self.is_ancestor(sha, current_sha):
                return None
            if not validated(self.github, sha):
                continue
            return web_build_for(self.github, sha)
        return None

    def deploy(
        self, environment: str, sha: str | None, component: str, *, dry_run: bool
    ) -> list[dict[str, Any]]:
        if environment not in ENVIRONMENTS:
            raise ReleaseError("unknown environment")
        with self.locked(wait=True):
            head = self.main_head()
            sha = sha or head
            if not SHA_RE.fullmatch(sha) or not self.is_ancestor(sha, head):
                raise ReleaseError("only commits on main can be deployed")
            if environment == "production" and not dry_run:
                if not self.paths.production_enabled.exists():
                    raise ReleaseError("production deploys are not enabled on this server yet")
                if not self.passed_staging(sha):
                    raise ReleaseError("this commit has not passed staging")
            results = []
            if component in ("core", "all"):
                candidate = (
                    core_candidate(self.github, sha) if self.github else Candidate("missing")
                )
                build = candidate.build or self.stored_build(sha, "core")
                if build is None:
                    raise ReleaseError(f"no core build for {sha[:12]}: {candidate.detail}")
                results.append(
                    self.attempt(environment, "core", build, dry_run=dry_run, trigger="manual")
                )
                if results[-1]["result"] == "failed":
                    return results
            if component in ("web", "all"):
                build = (
                    web_build_for(self.github, sha) if self.github else None
                ) or self.stored_build(sha, "web")
                if build is not None:
                    results.append(
                        self.attempt(environment, "web", build, dry_run=dry_run, trigger="manual")
                    )
                elif component == "web":
                    raise ReleaseError(f"no Sales Xray web build for {sha[:12]}")
            return results

    def stored_build(self, sha: str, component: str) -> Build | None:
        provenance = self.paths.store / sha / component / "provenance.json"
        if not provenance.exists():
            return None
        data = json.loads(provenance.read_text(encoding="utf-8"))
        return Build(
            sha,
            int(data["run_id"]),
            int(data["artifact_id"]),
            str(data["artifact_name"]),
            str(data["artifact_digest"]),
        )

    def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {"at": _now(), "environments": {}}
        for environment in ENVIRONMENTS:
            web_sha, web_image = self.current_web(environment)
            report["environments"][environment] = {
                "core": self.current_core(environment),
                "web": web_sha,
                "web_image": web_image,
                "auto_deploy": environment == "staging" and not self.is_paused(environment),
                "paused": self.is_paused(environment),
                "failed": {c: self.failed_sha(environment, c) for c in COMPONENTS},
            }
        report["production_enabled"] = self.paths.production_enabled.exists()
        report["recent"] = self.history(5)
        return report


# ---------------------------------------------------------------------------
# CLI


def _load_github(paths: Paths, *, required: bool) -> GitHub | None:
    try:
        token = paths.token.read_text(encoding="utf-8").strip()
    except OSError:
        if required:
            raise ReleaseError(f"GitHub token missing at {paths.token}") from None
        return None
    return GitHub(token)


def _print(data: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return
    if isinstance(data, dict) and "environments" in data:
        for name, env in data["environments"].items():
            state = "paused" if env["paused"] else ("auto" if env["auto_deploy"] else "manual")
            core, web = str(env["core"])[:12], str(env["web"])[:12]
            print(f"{name:<11} core={core:<12} web={web:<12} {state}")
            for component, sha in env["failed"].items():
                if sha:
                    print(f"{'':<11} {component} deploy of {sha[:12]} FAILED (resume to retry)")
        print(f"production deploys enabled: {data['production_enabled']}")
        return
    for entry in data if isinstance(data, list) else [data]:
        print(json.dumps(entry, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ac-release", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    sub.add_parser("tick")
    deploy = sub.add_parser("deploy")
    deploy.add_argument("environment", choices=ENVIRONMENTS)
    deploy.add_argument("sha", nargs="?")
    deploy.add_argument("--component", choices=("core", "web", "all"), default="all")
    deploy.add_argument("--dry-run", action="store_true")
    for name in ("pause", "resume"):
        sub.add_parser(name).add_argument("environment", choices=ENVIRONMENTS)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("environment", choices=ENVIRONMENTS)
    rollback.add_argument("--component", choices=("web",), required=True)
    history = sub.add_parser("history")
    history.add_argument("-n", type=int, default=20)
    args = parser.parse_args(argv)

    paths = Paths()
    engine = Engine(paths=paths)
    try:
        if args.command == "status":
            _print(engine.status(), args.json)
        elif args.command == "history":
            _print(engine.history(args.n), True)
        elif args.command in ("pause", "resume"):
            engine.set_paused(args.environment, args.command == "pause", "paused by operator")
            engine.record({"at": _now(), "environment": args.environment, "action": args.command})
            print(f"{args.environment}: {args.command}d")
        elif args.command == "rollback":
            with engine.locked(wait=True):
                result = engine.rollback_web(args.environment)
            engine.record(
                {
                    "at": _now(),
                    "environment": args.environment,
                    "component": "web",
                    "action": "rollback",
                    **result,
                }
            )
            _print(result, True)
        else:
            engine.github = _load_github(paths, required=args.command == "tick")
            results = (
                engine.tick()
                if args.command == "tick"
                else engine.deploy(args.environment, args.sha, args.component, dry_run=args.dry_run)
            )
            _print(results, True)
            if any(entry.get("result") == "failed" for entry in results):
                return 1
    except ReleaseError as error:
        print(f"ac-release: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
