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
    promote --bump patch|minor|major --version vX.Y.Z
    pause ENV | resume ENV          stop or restart automatic deploys
    rollback ENV --component web    restore the previous Sales Xray web image
    history [-n N]                  recent deploy records
    prune-artifacts [--apply] [--keep-recent N] [--no-images] [--json]
                                    report (default) or remove installer
                                    artifacts and core images nothing needs
    store-native SHA [--from ZIP]   keep a Sales Xray native build for good
                                    (GitHub deletes it after one day)

Production deploys are refused unless ``/etc/ac-release/production.enabled``
exists and the same commit already passed staging.

A core release that runs hosted Sales Xray needs an activation descriptor.
The engine carries the running release's activation forward with the
repository tool; it never creates or widens an approval.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import secrets
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
from typing import Any, NoReturn

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
NATIVE_WORKFLOW = "sales-xray-native-image.yml"
CORE_FILES = frozenset({"SHA256SUMS", "application-images.tar.gz", "release-images.env"})
WEB_FILES = frozenset({"SHA256SUMS", "web-image.env", "web-image.json", "web-image.tar.gz"})
MAX_ARTIFACT_BYTES = 450_000_000
# Stored bundles are several hundred MB each. Keep whatever runs in staging or
# production plus this many recent successful deploys (rollback and promotion).
KEEP_RECENT_BUILDS = 10
# The installer's own copies (application/artifacts/<sha>) are the local source
# for reinstalling an older core release: GitHub keeps each bundle for one day.
# prune-artifacts manages only these and the four core images they load.
CORE_IMAGE_REPOSITORIES = frozenset(
    f"ghcr.io/authorityclosers/authority-closers-{name}"
    for name in ("api", "learner-web", "admin-web", "coach-web")
)
CORE_IMAGE_KEYS = ("AC_API_IMAGE", "AC_LEARNER_IMAGE", "AC_ADMIN_IMAGE", "AC_COACH_IMAGE")
# A native build plus the GitHub records its reuse proofs pin. GitHub keeps the
# zip for one day, so the store keeps these for good (never pruned).
NATIVE_STORE_FILES = frozenset(
    {"native-artifact.zip", "artifact-metadata.json", "workflow-run.json"}
)
# The hosted worker cannot start once its approval lapses, so an approval with
# less than this left is never carried into a new release.
APPROVAL_MIN_REMAINING_SECONDS = 24 * 3600
# A crash-looping container can read "running" between restarts; it must stay
# up this long without a restart to count as started.
STEADY_SECONDS = 30
# The hosted worker reads its service and approval files through this group.
HOSTED_WORKER_GID = 10001
DEPLOYMENT_RECORD_RE = re.compile(r"[0-9]{8}T[0-9]{6}Z-([0-9a-f]{40})-[A-Za-z0-9-]+\.env")
UNFINISHED_RECORD_RE = re.compile(
    r"\.(?:prepared|deployment|forward-recovery)-([0-9a-f]{40})\.[A-Za-z0-9]+"
)
ARTIFACT_REFERENCE_RE = re.compile(rb"artifacts/([0-9a-f]{40})(?![0-9a-f])")
PRUNE_LEFTOVER_RE = re.compile(r"\.prune-[0-9a-f]{40}\.[0-9a-f]+")
REFERENCE_SCAN_MAX_BYTES = 1_000_000
SHA_RE = re.compile(r"[0-9a-f]{40}")
VERSION_RE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RELEASE_RECORD_FIELDS = frozenset(
    {"version", "core_sha", "web_sha", "requested_by", "at", "action", "rolled_back_from"}
)
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(r"sha256:[0-9a-f]{64}")
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
EDGE = "http://127.0.0.1:8080"


class ReleaseError(RuntimeError):
    """A deploy step failed; the message is safe to show and record."""


def _version_parts(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = VERSION_RE.fullmatch(value)
    if match is None:
        return None
    parts = tuple(int(part) for part in match.groups())
    return parts[0], parts[1], parts[2]


def _validate_release_record(entry: Mapping[str, Any]) -> dict[str, Any]:
    if set(entry) != RELEASE_RECORD_FIELDS:
        raise ReleaseError("production release record has an unexpected field set")
    record = dict(entry)
    if _version_parts(record["version"]) is None:
        raise ReleaseError("production release version is not semantic")
    for field_name in ("core_sha", "web_sha"):
        if not isinstance(record[field_name], str) or not SHA_RE.fullmatch(record[field_name]):
            raise ReleaseError(f"production release {field_name} is invalid")
    for field_name in ("requested_by", "at"):
        if not isinstance(record[field_name], str) or not record[field_name].strip():
            raise ReleaseError(f"production release {field_name} is missing")
    if record["action"] not in ("promote", "rollback"):
        raise ReleaseError("production release action is invalid")
    rolled_back_from = record["rolled_back_from"]
    if rolled_back_from is not None and _version_parts(rolled_back_from) is None:
        raise ReleaseError("production release rolled_back_from is invalid")
    if record["action"] == "promote" and rolled_back_from is not None:
        raise ReleaseError("a promoted release cannot set rolled_back_from")
    if record["action"] == "rollback" and rolled_back_from is None:
        raise ReleaseError("a rollback release must set rolled_back_from")
    return record


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
    foundation: Path = Path("/srv/authority-closers/current")
    sales_xray: Path = Path("/etc/authority-closers/sales-xray")
    engine: Path = Path("/opt/ac-release")

    @property
    def mirror(self) -> Path:
        return self.state / "mirror.git"

    @property
    def native_store(self) -> Path:
        return self.store / "native"

    @property
    def token(self) -> Path:
        return self.config / "github-actions-read.token"

    @property
    def history(self) -> Path:
        return self.state / "history.jsonl"

    @property
    def releases(self) -> Path:
        return self.state / "releases.jsonl"

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


def find_native_run(github: Any, sha: str) -> dict[str, Any] | None:
    """The successful native-image run for this commit, as reuse proofs accept it."""

    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/workflows/{NATIVE_WORKFLOW}/runs",
        {"head_sha": sha, "per_page": "20"},
    )
    runs = [
        run
        for run in data.get("workflow_runs", [])
        if run.get("head_sha") == sha
        and run.get("path") == f".github/workflows/{NATIVE_WORKFLOW}"
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and (
            run.get("event") == "workflow_dispatch"
            or (run.get("event") == "push" and run.get("head_branch") == "main")
        )
    ]
    if not runs:
        return None
    return max(runs, key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0)))


def native_artifact_record(github: Any, run: Mapping[str, Any], sha: str) -> dict[str, Any] | None:
    """The run's native artifact record, expired or not: its digest outlives the zip."""

    name = f"ac-sales-xray-native-{sha}"
    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/runs/{int(run['id'])}/artifacts", {"name": name}
    )
    matches = [
        artifact
        for artifact in data.get("artifacts", [])
        if artifact.get("name") == name
        and artifact.get("workflow_run", {}).get("id") == run["id"]
        and artifact.get("workflow_run", {}).get("head_sha") == sha
        and DIGEST_RE.fullmatch(str(artifact.get("digest") or ""))
        and 0 < int(artifact.get("size_in_bytes") or 0) <= MAX_ARTIFACT_BYTES
    ]
    if len(matches) != 1:
        return None
    return matches[0]


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


def read_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file written by the installer, refusing anything else."""

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ReleaseError(f"{path.name} is not a KEY=VALUE file")
        values[key] = value
    return values


def _tree_size(path: Path) -> int:
    if path.is_symlink() or not path.is_dir():
        return path.lstat().st_size
    total = 0
    for directory, _, names in os.walk(path):
        for name in names:
            total += (Path(directory) / name).lstat().st_size
    return total


def _add_reason(keep: dict[str, list[str]], sha: str, reason: str) -> None:
    reasons = keep.setdefault(sha, [])
    if reason not in reasons:
        reasons.append(reason)


def _refuse_unreadable(error: OSError) -> NoReturn:
    # A file we cannot read may name an artifact, so never guess past it.
    raise ReleaseError(f"cannot read {error.filename}: {error.strerror}")


def _date(epoch: int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _size(count: int) -> str:
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if count >= scale:
            return f"{count / scale:.1f} {unit}"
    return f"{count} B"


@dataclass
class Engine:
    paths: Paths = field(default_factory=Paths)
    github: Any = None
    run: Runner = run_command
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.time
    operator_group: str = "acops"

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

    def release_records(self) -> list[dict[str, Any]]:
        """Read the append-only production release ledger in event order."""

        if not self.paths.releases.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            self.paths.releases.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                message = f"production release record {line_number} is invalid JSON"
                raise ReleaseError(message) from error
            if not isinstance(value, dict):
                raise ReleaseError(f"production release record {line_number} is invalid")
            records.append(_validate_release_record(value))
        return records

    def append_release(self, entry: Mapping[str, Any]) -> None:
        """Append one production release event without changing prior history."""

        record = _validate_release_record(entry)
        if record["action"] == "rollback":
            current, _ = self.production_releases()
            if current is None or record["rolled_back_from"] != current["version"]:
                raise ReleaseError("rollback must refer to the current production version")
        self.paths.state.mkdir(parents=True, exist_ok=True)
        with self.paths.releases.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def production_releases(
        self,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return the current and previous production events, newest first."""

        records = self.release_records()
        current = records[-1] if records else None
        previous = records[-2] if len(records) > 1 else None
        return current, previous

    def passed_staging(self, sha: str, component: str = "core") -> bool:
        return any(
            entry.get("environment") == "staging"
            and entry.get("component") == component
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
                "+refs/tags/v*:refs/tags/v*",
            ],
            timeout=300,
        )

    def next_version(self, bump: str) -> str:
        """Calculate a patch, minor, or major version from tags and releases."""

        if bump not in ("patch", "minor", "major"):
            raise ReleaseError("version bump must be patch, minor, or major")
        self.sync_mirror()
        result = self.run(
            [
                "git",
                f"--git-dir={self.paths.mirror}",
                "for-each-ref",
                "--format=%(refname:short)",
                "refs/tags/v*",
            ]
        )
        versions = [
            parts
            for tag in result.stdout.splitlines()
            if (parts := _version_parts(tag.strip())) is not None
        ]
        versions.extend(
            parts
            for record in self.release_records()
            if (parts := _version_parts(record["version"])) is not None
        )
        major, minor, patch = max(versions, default=(0, 2, 0))
        if bump == "major":
            return f"v{major + 1}.0.0"
        if bump == "minor":
            return f"v{major}.{minor + 1}.0"
        return f"v{major}.{minor}.{patch + 1}"

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

    def promote(
        self,
        bump: str,
        version: str,
        *,
        requested_by: str,
        trigger: str,
        expected_sha: str | None = None,
    ) -> list[dict[str, Any]]:
        """Promote the tested staging pair, recording a release only on success."""

        with self.locked(wait=True):
            if not self.paths.production_enabled.exists():
                raise ReleaseError("production deploys are not enabled on this server yet")
            core_sha = self.current_core("staging")
            web_sha, _ = self.current_web("staging")
            if core_sha is None or web_sha is None:
                raise ReleaseError("staging does not have a complete core and web pair")
            head = self.main_head()
            if not self.is_ancestor(core_sha, head) or not self.is_ancestor(web_sha, head):
                raise ReleaseError("both staging commits must be on main")
            if not self.passed_staging(core_sha, "core") or not self.passed_staging(web_sha, "web"):
                raise ReleaseError("both staging components must have a successful staging deploy")
            if any(
                self.paths.failed_flag("staging", component).exists() for component in COMPONENTS
            ):
                raise ReleaseError("staging has a failed deploy that must be cleared first")
            core_build = self.stored_build(core_sha, "core")
            web_build = self.stored_build(web_sha, "web")
            if core_build is None or web_build is None:
                raise ReleaseError("the stored builds for the staging pair are incomplete")
            production_core = self.current_core("production")
            production_web, _ = self.current_web("production")
            if production_core and not self.is_ancestor(production_core, core_sha):
                raise ReleaseError("production core is not an ancestor of the staging core")
            if production_core == core_sha and production_web == web_sha:
                raise ReleaseError("production already runs this staging pair")
            if version != self.next_version(bump):
                raise ReleaseError(
                    "requested version does not match the next version for this bump"
                )
            if expected_sha is not None and expected_sha != production_core:
                raise ReleaseError("production core changed since this promotion was requested")

            attempts: list[dict[str, Any]] = []
            if production_core != core_sha:
                attempts.append(
                    self.attempt("production", "core", core_build, dry_run=False, trigger=trigger)
                )
                if attempts[-1]["result"] != "success":
                    return attempts
            attempts.append(
                self.attempt("production", "web", web_build, dry_run=False, trigger=trigger)
            )
            if attempts[-1]["result"] != "success":
                return attempts
            self.append_release(
                {
                    "version": version,
                    "core_sha": core_sha,
                    "web_sha": web_sha,
                    "requested_by": requested_by,
                    "at": _now(),
                    "action": "promote",
                    "rolled_back_from": None,
                }
            )
            return attempts

    # -- artifacts -------------------------------------------------------------

    def store_bundle(self, build: Build, component: str, expected: frozenset[str]) -> Path:
        """Download once into the immutable local store and return its path."""

        target = self.paths.store / build.sha / component
        # Provenance sits beside the bundle: verifiers require exact file sets.
        provenance = self.paths.store / build.sha / f"{component}.provenance.json"
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
            record = work_path / "provenance.json"
            record.write_text(
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
            for item in [*target.iterdir(), target]:
                item.chmod(0o500 if item.is_dir() else 0o400)
            os.replace(record, provenance)
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
        blockers: list[str] = []
        try:
            self.require_backup_support(bundle)
        except ReleaseError as error:
            if not dry_run:
                raise
            # A rehearsal reports every blocker instead of stopping at the first.
            blockers.append(str(error))
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
            activation: dict[str, Any] = {}
            try:
                self.keep_native_build(build.sha)
                activation = self.prepare_activation(
                    environment, build.sha, source, stage, dry_run=dry_run, log=log
                )
            except ReleaseError as error:
                if not dry_run:
                    raise
                blockers.append(str(error))
            if dry_run:
                if blockers:
                    raise ReleaseError("dry run found blockers: " + "; ".join(blockers))
                return {
                    "dry_run": True,
                    "previous": previous,
                    "installer": str(installer),
                    "log": str(log),
                    **activation,
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
        return {"previous": previous, "log": str(log), **activation}

    def require_backup_support(self, bundle: Path) -> None:
        """Refuse a schema the installed foundation backup tools cannot attest.

        ac-postgres-backup checks every environment's migration head before it
        backs up any of them, so one unknown head stops production backups too.
        """

        head = ""
        for line in (bundle / "release-images.env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "AC_MIGRATION_HEAD":
                head = value.strip()
        if not re.fullmatch(r"[0-9]{8}_[0-9]{4}", head):
            raise ReleaseError("release bundle has no valid AC_MIGRATION_HEAD")
        backup_tool = self.paths.foundation / "scripts" / "ac-postgres-backup.py"
        try:
            known = f'"{head}"' in backup_tool.read_text(encoding="utf-8")
        except OSError:
            known = False
        if not known:
            raise ReleaseError(
                f"the installed foundation backup tools do not recognise migration {head}; "
                "install the foundation release from main first, or backups for every "
                "environment would stop"
            )

    # -- Sales Xray activation ---------------------------------------------------

    def activation_path(self, environment: str, sha: str) -> Path:
        return self.paths.sales_xray / environment / f"activation-{sha}.json"

    @staticmethod
    def approval_expiry(descriptor: Mapping[str, Any]) -> int:
        """When the activation's approval, or its acquisition policy, lapses."""

        approval = json.loads(Path(str(descriptor["approval_file"])).read_text(encoding="utf-8"))
        ends = [int(approval["expires_at_epoch"])]
        policy = approval.get("acquisition_policy")
        if isinstance(policy, dict):
            ends.append(int(policy["expires_at_epoch"]))
        return min(ends)

    def approval_expires(self, environment: str) -> int | None:
        current = self.current_core(environment)
        if current is None:
            return None
        path = self.activation_path(environment, current)
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            return self.approval_expiry(json.loads(path.read_text(encoding="utf-8")))
        return None

    def store_native(self, sha: str, *, local_zip: Path | None = None) -> Path:
        """Keep one native build and its GitHub records for good.

        Every later release's reuse proof needs the original zip, and GitHub
        deletes it a day after the build. A saved copy is adopted only when it
        matches the digest and size GitHub recorded for that build.
        """

        if not SHA_RE.fullmatch(sha):
            raise ReleaseError("a native build is named by its full commit id")
        target = self.paths.native_store / sha
        if all((target / name).is_file() for name in NATIVE_STORE_FILES):
            return target
        if self.github is None:
            raise ReleaseError(
                f"native build {sha[:12]} is not stored and GitHub is not configured"
            )
        run = find_native_run(self.github, sha)
        record = native_artifact_record(self.github, run, sha) if run is not None else None
        if run is None or record is None:
            raise ReleaseError(f"GitHub has no successful native image build for {sha[:12]}")
        self.paths.native_store.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.paths.native_store, prefix=".download-") as work:
            unpacked = Path(work) / sha
            unpacked.mkdir()
            zip_path = unpacked / "native-artifact.zip"
            if local_zip is not None:
                if (
                    local_zip.stat().st_size != int(record["size_in_bytes"])
                    or f"sha256:{_sha256_file(local_zip)}" != record["digest"]
                ):
                    raise ReleaseError("the saved zip is not the native build GitHub recorded")
                shutil.copyfile(local_zip, zip_path)
            elif record.get("expired", True):
                raise ReleaseError(
                    f"native build {sha[:12]} has expired on GitHub; adopt a saved copy with "
                    f"`ac-release store-native {sha} --from ZIP`"
                )
            else:
                self.github.download_artifact(int(record["id"]), zip_path, str(record["digest"]))
            metadata = self.github.get_json(
                f"/repos/{REPOSITORY}/actions/artifacts/{int(record['id'])}"
            )
            workflow_run = self.github.get_json(
                f"/repos/{REPOSITORY}/actions/runs/{int(run['id'])}"
            )
            if metadata.get("digest") != record["digest"] or workflow_run.get("id") != run["id"]:
                raise ReleaseError("GitHub returned inconsistent records for the native build")
            for name, value in (
                ("artifact-metadata.json", metadata),
                ("workflow-run.json", workflow_run),
            ):
                (unpacked / name).write_text(
                    json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            for item in unpacked.iterdir():
                item.chmod(0o400)
            if target.exists():
                shutil.rmtree(target, onexc=_make_writable_and_retry)
            os.replace(unpacked, target)
            target.chmod(0o500)
        return target

    def keep_native_build(self, sha: str) -> None:
        """Store this commit's own native build, if CI made one, before GitHub drops it."""

        if self.github is not None and find_native_run(self.github, sha) is not None:
            self.store_native(sha)

    def native_for_image(self, image_ref: str) -> tuple[str, Path]:
        """The loaded native artifact (source commit, manifest) behind an image."""

        matches: list[tuple[str, Path]] = []
        root = self.paths.application / "artifacts"
        for manifest in sorted(root.glob("sales-xray-native-*/native-image.json")):
            sha = manifest.parent.name.removeprefix("sales-xray-native-")
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if (
                    SHA_RE.fullmatch(sha)
                    and data["source_commit"] == sha
                    and data["image"]["expected_runtime_ref"] == image_ref
                ):
                    matches.append((sha, manifest))
        if len(matches) != 1:
            raise ReleaseError(f"no single loaded native artifact provides {image_ref[:19]}")
        return matches[0]

    def prepare_activation(
        self, environment: str, sha: str, source: Path, stage: Path, *, dry_run: bool, log: Path
    ) -> dict[str, Any]:
        """Carry the running release's Sales Xray activation forward to ``sha``.

        Uses the repository's prepare tool with the approval unchanged and the
        running native image, proven reusable from the stored native build and
        this engine's mirror. Nothing happens when hosted Sales Xray is not
        active or the target already has an activation.
        """

        if self.activation_path(environment, sha).is_file():
            return {"sales_xray_activation": "present"}
        current = self.current_core(environment)
        if current is None or not self.activation_path(environment, current).is_file():
            return {}
        previous = self.activation_path(environment, current)
        descriptor = json.loads(previous.read_text(encoding="utf-8"))
        expires = self.approval_expiry(descriptor)
        if expires - self.clock() < APPROVAL_MIN_REMAINING_SECONDS:
            raise ReleaseError(
                f"the {environment} Sales Xray approval expires {_date(expires)}; "
                "renew it before deploying"
            )
        native_sha, manifest = self.native_for_image(str(descriptor["native_image_ref"]))
        stamp = dt.datetime.fromtimestamp(self.clock(), dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        home = (
            stage / "sales-xray-activation"
            if dry_run
            else self.paths.application / "operator-inputs" / environment / f"release-{sha}-{stamp}"
        )
        inputs, output = home / "inputs", home / "activation-bundle"
        inputs.mkdir(parents=True)
        argv = [
            "python3",
            str(source / "infra/application/scripts/prepare-sales-xray-native-activation.py"),
            "--source-activation",
            str(previous),
            "--target-release-id",
            sha,
            "--native-artifact-manifest",
            str(manifest),
            "--native-artifact-sha256",
            _sha256_file(manifest),
            "--output-dir",
            str(output),
        ]
        if native_sha != sha:
            proof = self.native_reuse_proof(native_sha, sha, inputs)
            argv += [
                "--native-reuse-proof",
                str(proof),
                "--native-reuse-proof-sha256",
                _sha256_file(proof),
                "--source-repository",
                str(self.paths.mirror),
            ]
        completed = self.run(argv, log=log, check=False, timeout=900)
        if completed.returncode != 0:
            lines = completed.stderr.strip().splitlines()
            detail = lines[-1][:300] if lines else f"exit {completed.returncode}"
            if "native_inputs_changed" in detail:
                raise ReleaseError(
                    f"{sha[:12]} changes the Sales Xray native image; install its native "
                    f"build before deploying it ({detail})"
                )
            raise ReleaseError(f"Sales Xray activation could not be prepared: {detail}")
        result = json.loads(completed.stdout)
        if (
            result.get("release_id") != sha
            or result.get("provider_calls") != 0
            or result.get("approval_replaced") is not False
        ):
            raise ReleaseError("the Sales Xray prepare tool returned an unexpected result")
        summary = {
            "sales_xray_activation": f"carried forward from {current[:12]}",
            "sales_xray_native": native_sha,
            "sales_xray_approval_expires": _date(expires),
        }
        if not dry_run:
            self._seal_activation(home, output)
            self._publish_activation(environment, sha, output)
        return summary

    def native_reuse_proof(self, native_sha: str, sha: str, directory: Path) -> Path:
        stored = self.store_native(native_sha)
        proof = directory / "native-reuse-input.json"
        pinned = {
            name.removesuffix(".json").replace("-", "_"): {
                "path": str(stored / name),
                "sha256": _sha256_file(stored / name),
            }
            for name in ("artifact-metadata.json", "workflow-run.json")
        }
        proof.write_text(
            json.dumps(
                {
                    "archive_path": str(stored / "native-artifact.zip"),
                    **pinned,
                    "native_source_commit": native_sha,
                    "repository": REPOSITORY,
                    "schema": "ac.sales-xray.native-reuse-input/1",
                    "target_release_id": sha,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return proof

    def _seal_activation(self, home: Path, output: Path) -> None:
        """Give prepared files the reviewed layout: root-owned and read-only."""

        for item in output.iterdir():
            item.chmod(0o440)
        if os.name != "posix" or os.geteuid() != 0:
            return
        import grp

        try:
            operators = grp.getgrnam(self.operator_group).gr_gid
        except KeyError:
            raise ReleaseError(f"operator group {self.operator_group} is absent") from None
        for directory in (home, home / "inputs", output):
            os.chown(directory, 0, operators)
        for item in output.iterdir():
            group = HOSTED_WORKER_GID if item.name.startswith("service-") else operators
            os.chown(item, 0, group)
        home.chmod(0o2750)
        (home / "inputs").chmod(0o2750)
        output.chmod(0o2755)

    def _publish_activation(self, environment: str, sha: str, output: Path) -> None:
        """Install the descriptor, then its digest, where the installer reads them."""

        descriptor = output / f"activation-{sha}.json"
        digest = output / f"activation-{sha}.json.sha256"
        if digest.read_text(encoding="ascii").strip() != _sha256_file(descriptor):
            raise ReleaseError("the prepared activation digest does not match its descriptor")
        config = self.paths.sales_xray / environment
        for item in (descriptor, digest):
            temporary = config / f".{item.name}.{secrets.token_hex(4)}"
            shutil.copyfile(item, temporary)
            temporary.chmod(0o444)
            os.replace(temporary, config / item.name)

    def require_steady(self, container: str, log: Path) -> None:
        """Fail when a container restarts or stops within STEADY_SECONDS."""

        fmt = "{{.State.Status}}|{{.RestartCount}}|{{.State.StartedAt}}"
        argv = ["docker", "inspect", "--format", fmt, container]
        before = self.run(argv, check=False).stdout.strip()
        self.sleep(STEADY_SECONDS)
        after = self.run(argv, check=False).stdout.strip()
        if not after.startswith("running|") or after != before:
            raise ReleaseError(
                f"{container} did not stay up after the deploy ({before} -> {after}); "
                f"see `docker logs {container}`"
            )
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"STEADY {container}\n")

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
        if self.activation_path(environment, sha).is_file():
            # The hosted worker has no health check; a bad activation shows up
            # only as a restart loop, so it must stay up on the release image.
            worker = f"{project}-sales-xray-worker-1"
            self.wait_for_container(worker, images.get("AC_API_IMAGE"), False, None, log)
            self.require_steady(worker, log)
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
        if previous_sha == build.sha and not dry_run:
            # The live container's compose files are in `inputs`; never rebuild them.
            return {"unchanged": True, "previous": previous_sha, "log": str(log)}
        # Anything short of a started container leaves no operator inputs behind.
        prepared = False
        try:
            with self.stage(build.sha) as stage:
                # A dry run never touches the live operator inputs.
                workdir = stage / "inputs" if dry_run else inputs
                archive, archive_sha = self.source_archive(build.sha, stage, "infra/sales-xray-web")
                if workdir.exists():
                    shutil.rmtree(workdir)
                workdir.mkdir(parents=True, mode=0o750)
                self.extract_source(archive, workdir / "source", "infra/sales-xray-web")
                source = workdir / "source" / "infra" / "sales-xray-web"
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
                if proof.get("verified_source") != build.sha or not IMAGE_REF_RE.fullmatch(
                    runtime_ref
                ):
                    raise ReleaseError("web artifact verification did not bind this commit")
                if dry_run:
                    return {
                        "dry_run": True,
                        "previous": previous_sha,
                        "runtime_ref": runtime_ref,
                        "log": str(log),
                    }
                self.run(
                    ["docker", "load", "--quiet", "--input", str(bundle / "web-image.tar.gz")],
                    log=log,
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
                verified = workdir / "verified-runtime.env"
                verified.write_text(f"AC_WEB_IMAGE={runtime_ref}\n", encoding="utf-8")
                rollback = workdir / "rollback-runtime.env"
                if previous_image:
                    rollback.write_text(f"AC_WEB_IMAGE={previous_image}\n", encoding="utf-8")
                (workdir / "archive.sha256").write_text(archive_sha + "\n", encoding="utf-8")
            prepared = True
        finally:
            if not prepared and not dry_run:
                shutil.rmtree(inputs, ignore_errors=True)
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

        try:
            production_releases = self.production_releases()
        except ReleaseError:
            # If the ledger is damaged, we cannot know which builds production
            # needs. Keep the entire store so pruning cannot break a deploy.
            return []

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
        for release in production_releases:
            if release is not None:
                keep.update((release["core_sha"], release["web_sha"]))
        removed: list[str] = []
        if not self.paths.store.exists():
            return removed
        for entry_path in sorted(self.paths.store.iterdir()):
            if SHA_RE.fullmatch(entry_path.name) and entry_path.name not in keep:
                shutil.rmtree(entry_path, onexc=_make_writable_and_retry)
                removed.append(entry_path.name)
        return removed

    # -- installer artifact retention ------------------------------------------

    def retained_releases(self) -> dict[str, list[str]]:
        """Releases whose installer artifact must stay, each with its reasons.

        Keeps what each environment runs, every release its deployment records
        name from the last COMMITTED record onward (the rollback target and any
        unfinished or forward-recovery attempt to reapply), and every release a
        file under deployments/ or operator-inputs/ names by artifact path.
        """

        keep: dict[str, list[str]] = {}
        for environment in ENVIRONMENTS:
            current = self._current_release(environment)
            if current:
                _add_reason(keep, current, f"running in {environment}")
            for sha, reason in self._deployment_record_releases(environment):
                _add_reason(keep, sha, reason)
        for sha, reason in self._artifact_references():
            _add_reason(keep, sha, reason)
        return keep

    def _current_release(self, environment: str) -> str | None:
        link = self.paths.application / f"current-{environment}"
        if not link.is_symlink():
            if link.exists():
                raise ReleaseError(f"current-{environment} is not a symbolic link")
            return None
        target = Path(os.path.realpath(link))
        releases = Path(os.path.realpath(self.paths.application / "releases"))
        if target.parent != releases or not SHA_RE.fullmatch(target.name):
            raise ReleaseError(f"current-{environment} does not resolve to an installed release")
        return target.name

    def _deployment_record_releases(self, environment: str) -> list[tuple[str, str]]:
        root = self.paths.application / "deployments" / environment
        if not root.is_dir():
            return []
        found: list[tuple[str, str]] = []
        records: list[dict[str, str]] = []
        for path in sorted(root.iterdir()):
            unfinished = UNFINISHED_RECORD_RE.fullmatch(path.name)
            if unfinished:
                # The installer is writing this record, or was killed while it did.
                found.append((unfinished.group(1), f"unfinished {environment} record"))
                continue
            named = DEPLOYMENT_RECORD_RE.fullmatch(path.name)
            if named is None:
                continue
            if path.is_symlink() or not path.is_file():
                raise ReleaseError(f"deployment record {path.name} is not a regular file")
            values = read_env_file(path)
            previous = values.get("AC_PREVIOUS_RELEASE", "")
            if (
                values.get("AC_RELEASE_ID") != named.group(1)
                or not values.get("AC_STATUS")
                or (previous and not SHA_RE.fullmatch(previous))
            ):
                raise ReleaseError(f"deployment record {path.name} does not match its name")
            records.append(values)
        # Record names start with a UTC timestamp, so sorted order is time order.
        committed = [i for i, values in enumerate(records) if values["AC_STATUS"] == "COMMITTED"]
        for values in records[committed[-1] if committed else 0 :]:
            status = values["AC_STATUS"]
            if status == "COMMITTED":
                reason = f"last committed to {environment}"
            elif status == "FORWARD_RECOVERY_REQUIRED":
                reason = f"{environment} forward recovery (reapply this release)"
            else:
                reason = f"unfinished {environment} attempt"
            found.append((values["AC_RELEASE_ID"], reason))
            if values.get("AC_PREVIOUS_RELEASE"):
                found.append((values["AC_PREVIOUS_RELEASE"], f"{environment} rollback target"))
        return found

    def _artifact_references(self) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for top in ("deployments", "operator-inputs"):
            base = self.paths.application / top
            if not base.is_dir():
                continue
            for directory, _, names in os.walk(base, onerror=_refuse_unreadable):
                for name in sorted(names):
                    path = Path(directory) / name
                    try:
                        if (
                            path.is_symlink()
                            or not path.is_file()
                            or path.stat().st_size > REFERENCE_SCAN_MAX_BYTES
                        ):
                            continue
                        data = path.read_bytes()
                    except OSError as error:
                        _refuse_unreadable(error)
                    relative = path.relative_to(self.paths.application).as_posix()
                    for match in sorted(set(ARTIFACT_REFERENCE_RE.findall(data))):
                        found.append((match.decode(), f"named in {relative}"))
        return found

    def artifact_retention(
        self, keep_recent: int = KEEP_RECENT_BUILDS, *, images: bool = True
    ) -> dict[str, Any]:
        """Report each installer artifact (and core image) with why it stays.

        An entry without reasons is not needed. Only full-SHA directories are
        managed; Sales Xray native helpers and web bundles that share the
        directory, and the installer's own .stage-* directories, are listed
        as unmanaged and never removed.
        """

        root = self.paths.application / "artifacts"
        keep = self.retained_releases()
        core: list[Path] = []
        leftovers: list[Path] = []
        unmanaged: list[Path] = []
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if path.is_symlink() or not path.is_dir():
                    unmanaged.append(path)
                elif SHA_RE.fullmatch(path.name):
                    core.append(path)
                elif PRUNE_LEFTOVER_RE.fullmatch(path.name):
                    leftovers.append(path)
                else:
                    unmanaged.append(path)
        core.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        for path in core[:keep_recent]:
            _add_reason(keep, path.name, f"one of the {keep_recent} newest")
        report: dict[str, Any] = {
            "artifacts_root": str(root),
            "keep_recent": keep_recent,
            "artifacts": [
                {
                    "sha": path.name,
                    "bytes": _tree_size(path),
                    "written": dt.datetime.fromtimestamp(path.stat().st_mtime, dt.UTC).strftime(
                        "%Y-%m-%d"
                    ),
                    "keep": keep.get(path.name, []),
                }
                for path in core
            ],
            "leftovers": [path.name for path in leftovers],
            "unmanaged": [{"name": path.name, "bytes": _tree_size(path)} for path in unmanaged],
        }
        if images:
            report.update(self.image_retention(keep))
        return report

    def image_retention(self, keep: Mapping[str, list[str]]) -> dict[str, Any]:
        """Core application images, each with why it stays.

        An image is managed only when every tag is a core repository tagged
        with a full commit. It stays when any container uses it or when it
        belongs to a kept release. Sales Xray native images run from systemd
        units rather than containers, so they are never managed here.
        """

        kept_images: dict[str, str] = {}
        for sha in keep:
            for manifest in (
                self.paths.application / "releases" / sha / "release-images.env",
                self.paths.application / "artifacts" / sha / "release-images.env",
            ):
                if not manifest.is_file():
                    continue
                values = read_env_file(manifest)
                for key in CORE_IMAGE_KEYS:
                    image = values.get(key, "")
                    if image and not IMAGE_REF_RE.fullmatch(image):
                        raise ReleaseError(f"{manifest} has a malformed {key}")
                    if image:
                        kept_images[image] = sha
        listing = self.run(
            [
                "docker",
                "image",
                "ls",
                "--all",
                "--no-trunc",
                "--format",
                "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}",
            ]
        ).stdout
        tags: dict[str, list[str]] = {}
        sizes: dict[str, str] = {}
        for line in listing.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) != 4 or not IMAGE_REF_RE.fullmatch(fields[0]):
                raise ReleaseError("docker image ls returned an unexpected line")
            image, repository, tag, size = fields
            sizes[image] = size
            references = tags.setdefault(image, [])
            if repository != "<none>" and tag != "<none>":
                references.append(f"{repository}:{tag}")
        containers = self.run(
            ["docker", "container", "ls", "--all", "--quiet", "--no-trunc"]
        ).stdout.split()
        used: set[str] = set()
        if containers:
            used.update(
                self.run(
                    ["docker", "container", "inspect", "--format", "{{.Image}}", *containers]
                ).stdout.split()
            )
        managed: list[dict[str, Any]] = []
        unmanaged = 0
        for image, references in tags.items():
            parsed = [reference.rsplit(":", 1) for reference in references]
            if not parsed or any(
                repository not in CORE_IMAGE_REPOSITORIES or not SHA_RE.fullmatch(tag)
                for repository, tag in parsed
            ):
                unmanaged += 1
                continue
            reasons = ["used by a container"] if image in used else []
            releases = {tag for _, tag in parsed if tag in keep}
            if image in kept_images:
                releases.add(kept_images[image])
            reasons += [f"belongs to kept release {sha[:12]}" for sha in sorted(releases)]
            managed.append({"id": image, "tags": references, "size": sizes[image], "keep": reasons})
        managed.sort(key=lambda entry: entry["tags"])
        return {"images": managed, "unmanaged_images": unmanaged}

    @contextlib.contextmanager
    def deployment_lock(self) -> Iterator[None]:
        """Hold the installer's own lock so no core install runs meanwhile."""

        path = self.paths.application / ".deployment.lock"
        with path.open("a") as handle:
            if fcntl is not None:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise ReleaseError(
                        "an application deployment is running; try again when it finishes"
                    ) from None
            yield

    def prune_artifacts(
        self, keep_recent: int = KEEP_RECENT_BUILDS, *, apply: bool = False, images: bool = True
    ) -> dict[str, Any]:
        """Report, or with apply remove, what artifact_retention finds unneeded."""

        if keep_recent < 0:
            raise ReleaseError("--keep-recent cannot be negative")
        if not apply:
            return {**self.artifact_retention(keep_recent, images=images), "applied": False}
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise ReleaseError("prune-artifacts --apply must run as root")
        with self.locked(wait=False) as acquired:
            if not acquired:
                raise ReleaseError("a release engine run is active; try again when it finishes")
            with self.deployment_lock():
                # Decide again under both locks so a just-finished install counts.
                report = {**self.artifact_retention(keep_recent, images=images), "applied": True}
                report["removed"], report["errors"] = self._remove_unretained(report)
        self.record(
            {
                "at": _now(),
                "action": "prune-artifacts",
                "removed": len(report["removed"]),
                "freed_bytes": sum(
                    entry["bytes"]
                    for entry in report["artifacts"]
                    if f"artifacts/{entry['sha']}" in report["removed"]
                ),
                "errors": report["errors"],
            }
        )
        return report

    def _remove_unretained(self, report: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        root = self.paths.application / "artifacts"
        removed: list[str] = []
        errors: list[str] = []
        doomed = [(root / name, f"artifacts/{name}") for name in report["leftovers"]]
        for artifact in report["artifacts"]:
            if artifact["keep"]:
                continue
            source = root / artifact["sha"]
            # Rename first: an install must never find a half-removed bundle.
            target = root / f".prune-{artifact['sha']}.{secrets.token_hex(4)}"
            try:
                source.rename(target)
            except OSError as error:
                errors.append(f"artifacts/{artifact['sha']}: {error.strerror}")
                continue
            doomed.append((target, f"artifacts/{artifact['sha']}"))
        for path, label in doomed:
            try:
                shutil.rmtree(path, onexc=_make_writable_and_retry)
            except OSError as error:
                errors.append(f"{label}: {error.strerror}")
                continue
            removed.append(label)
        for image in report.get("images", []):
            if image["keep"]:
                continue
            # Untag one reference at a time without --force: Docker itself
            # refuses if a container started using the image meanwhile.
            for reference in image["tags"]:
                completed = self.run(["docker", "image", "rm", reference], check=False)
                if completed.returncode != 0:
                    errors.append(f"{reference}: {completed.stderr.strip()[:200]}")
                    break
            else:
                removed.append(image["id"])
        return removed, errors

    def installed_engine(self) -> str | None:
        """Commit of the installed engine (``current`` links to ``releases/<sha>``)."""

        with contextlib.suppress(OSError):
            name = Path(os.path.realpath(self.paths.engine / "current")).name
            if SHA_RE.fullmatch(name):
                return name
        return None

    def release_tree(self, sha: str) -> str:
        """Git tree of infra/release at a commit; empty when the mirror lacks it."""

        result = self.run(
            ["git", f"--git-dir={self.paths.mirror}", "rev-parse", f"{sha}:infra/release"],
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def update_engine(self, head: str) -> dict[str, Any] | None:
        """Reinstall this engine from main when a validated main commit changed it.

        Only owner-merged commits whose full validation passed are installed:
        the same trust the engine already gives the installers it runs. A
        failed install is not retried for the same commit; deploys continue
        on the engine already installed.
        """

        installed = self.installed_engine()
        failed = self.paths.state / "engine-update.failed"
        if installed is None or installed == head:
            return None
        if failed.exists() and failed.read_text(encoding="utf-8").strip() == head:
            return None
        if self.release_tree(installed) == self.release_tree(head):
            return None
        if self.github is None or not validated(self.github, head):
            return None
        entry: dict[str, Any] = {
            "at": _now(),
            "action": "engine-update",
            "from": installed,
            "to": head,
        }
        log = self.new_log("engine", "update", head)
        with self.stage(head) as stage:
            checkout = stage / "source"
            self.run(
                ["git", "clone", "--quiet", "--no-checkout", str(self.paths.mirror), str(checkout)],
                log=log,
            )
            self.run(["git", "-C", str(checkout), "checkout", "--quiet", head], log=log)
            completed = self.run(
                ["bash", str(checkout / "infra/release/install-release-engine.sh")],
                log=log,
                check=False,
                timeout=300,
            )
        if completed.returncode == 0:
            entry["result"] = "success"
        else:
            entry["result"] = "failed"
            entry["error"] = f"engine install exited with {completed.returncode}; see {log}"
            failed.write_text(head + "\n", encoding="utf-8")
        self.record(entry)
        return entry

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
            update = self.update_engine(head)
            if update is not None:
                # The next tick runs the new engine; this one stops here.
                return [update]
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
        provenance = self.paths.store / sha / f"{component}.provenance.json"
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
            expires = self.approval_expires(environment)
            report["environments"][environment] = {
                "core": self.current_core(environment),
                "web": web_sha,
                "web_image": web_image,
                "auto_deploy": environment == "staging" and not self.is_paused(environment),
                "paused": self.is_paused(environment),
                "failed": {c: self.failed_sha(environment, c) for c in COMPONENTS},
                "sales_xray_approval_expires": _date(expires) if expires else None,
                "sales_xray_approval_days_left": (
                    int((expires - self.clock()) // 86400) if expires else None
                ),
            }
        report["production_enabled"] = self.paths.production_enabled.exists()
        report["engine"] = self.installed_engine()
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
            if env.get("sales_xray_approval_expires"):
                print(
                    f"{'':<11} Sales Xray approval until {env['sales_xray_approval_expires']} "
                    f"({env['sales_xray_approval_days_left']} days)"
                )
        print(f"production deploys enabled: {data['production_enabled']}")
        if data.get("engine"):
            print(f"engine: {data['engine'][:12]} (updates itself from main)")
        return
    for entry in data if isinstance(data, list) else [data]:
        print(json.dumps(entry, sort_keys=True))


def _why(reasons: Sequence[str]) -> str:
    shown = "; ".join(reasons[:2])
    return shown + (f" (+{len(reasons) - 2} more)" if len(reasons) > 2 else "")


def _print_retention(report: Mapping[str, Any]) -> None:
    artifacts = report["artifacts"]
    kept = [entry for entry in artifacts if entry["keep"]]
    unneeded = [entry for entry in artifacts if not entry["keep"]]
    total = sum(entry["bytes"] for entry in artifacts)
    print(f"Installer artifacts in {report['artifacts_root']}: {len(artifacts)}, {_size(total)}")
    for entry in artifacts:
        decision = "keep" if entry["keep"] else "remove"
        print(
            f"  {decision:<6} {entry['sha'][:12]}  {entry['written']}  "
            f"{_size(entry['bytes']):>8}  {_why(entry['keep'])}".rstrip()
        )
    print(
        f"Keep {len(kept)} ({_size(sum(entry['bytes'] for entry in kept))}); "
        f"remove {len(unneeded)} ({_size(sum(entry['bytes'] for entry in unneeded))})."
    )
    if report["leftovers"]:
        print(f"Also remove {len(report['leftovers'])} left over from an interrupted removal.")
    groups: dict[str, list[int]] = {}
    for entry in report["unmanaged"]:
        groups.setdefault(re.sub(r"[0-9a-f]{40}.*$", "*", entry["name"]), []).append(entry["bytes"])
    if groups:
        listed = ", ".join(
            f"{pattern} x{len(sizes)} ({_size(sum(sizes))})"
            for pattern, sizes in sorted(groups.items())
        )
        print(f"Never removed by this command: {listed}")
    if "images" in report:
        images = report["images"]
        print(f"\nCore application images in Docker: {len(images)}")
        for image in images:
            decision = "keep" if image["keep"] else "remove"
            names = ", ".join(
                f"{repository.rsplit('/', 1)[-1]}:{tag[:12]}"
                for repository, tag in (reference.rsplit(":", 1) for reference in image["tags"])
            )
            print(
                f"  {decision:<6} {image['id'][7:19]}  {image['size']:>8}  {names}  "
                f"{_why(image['keep'])}".rstrip()
            )
        removable = sum(1 for image in images if not image["keep"])
        print(
            f"Keep {len(images) - removable}; remove {removable}. Layers are shared, so compare "
            "`docker system df` before and after to see the space freed."
        )
        print(
            f"Never removed by this command: {report['unmanaged_images']} other images "
            "(Sales Xray web and native, foundation, untagged)."
        )
    print()
    if not report["applied"]:
        print("Dry run: nothing was removed. Run again with --apply to remove what says remove.")
        return
    print(f"Removed {len(report['removed'])}.")
    for error in report["errors"]:
        print(f"  FAILED {error}")


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
    promote = sub.add_parser("promote")
    promote.add_argument("--bump", choices=("patch", "minor", "major"), required=True)
    promote.add_argument("--version", required=True, metavar="vX.Y.Z")
    for name in ("pause", "resume"):
        sub.add_parser(name).add_argument("environment", choices=ENVIRONMENTS)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("environment", choices=ENVIRONMENTS)
    rollback.add_argument("--component", choices=("web",), required=True)
    history = sub.add_parser("history")
    history.add_argument("-n", type=int, default=20)
    prune = sub.add_parser("prune-artifacts")
    mode = prune.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report only (the default)")
    mode.add_argument("--apply", action="store_true", help="remove what the report marks remove")
    prune.add_argument("--keep-recent", type=int, default=KEEP_RECENT_BUILDS, metavar="N")
    prune.add_argument("--no-images", action="store_true", help="leave Docker images out")
    prune.add_argument("--json", action="store_true")
    native = sub.add_parser("store-native")
    native.add_argument("sha")
    native.add_argument("--from", dest="local_zip", type=Path, metavar="ZIP")
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
        elif args.command == "promote":
            user = os.environ.get("SUDO_USER") or getpass.getuser()
            results = engine.promote(
                args.bump, args.version, requested_by=f"cli:{user}", trigger="cli"
            )
            _print(results, True)
            if any(entry.get("result") == "failed" for entry in results):
                return 1
        elif args.command == "prune-artifacts":
            report = engine.prune_artifacts(
                args.keep_recent, apply=args.apply, images=not args.no_images
            )
            if args.json:
                _print(report, True)
            else:
                _print_retention(report)
            if report.get("errors"):
                return 1
        elif args.command == "store-native":
            engine.github = _load_github(paths, required=True)
            with engine.locked(wait=True):
                print(engine.store_native(args.sha, local_zip=args.local_zip))
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
