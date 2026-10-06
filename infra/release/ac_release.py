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
    promote --bump patch|minor|major --version vX.Y.Z [--dry-run]
    pause ENV | resume ENV          stop or restart automatic deploys
    train [--now] [--dry-run]        gated automatic patch promotion
    rollback ENV --component core|web restore a previous application component
    rollback production [--dry-run] restore the previous production release pair
    publish-status                  write the Admin snapshot (admin/outbox/status.json)
    history [-n N]                  recent deploy records
    prune-artifacts [--apply] [--keep-recent N] [--no-images] [--json]
                                    report (default) or remove installer
                                    artifacts and core images nothing needs
    store-native SHA [--from ZIP]   keep a Sales Xray native build for good
                                    (GitHub deletes it after one day)
    prepare-native staging SHA --previous-native-units PATH --previous-native-units-sha256 HASH
                                    pin an exact native transition, without starting it

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
import importlib.util
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
CORE_RECOVERY_WORKFLOW = "application-recovery.yml"
RECOVERY_PROOF_MAX_BYTES = 64 * 1024
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
NATIVE_FILES = frozenset(
    {
        "SHA256SUMS",
        "native-image.json",
        "native-image.env",
        "native-image.tar.gz",
        "native-helper.tar.gz",
        "native-helper-files.sha256",
    }
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
STATUS_MAX_BYTES = 256 * 1024
STATUS_LIST_LIMIT = 20
STATUS_NOTES_LIMIT = 50
BUMPS = ("patch", "minor", "major")
# Snapshot text is read by Admin: never pass on an email address or a GitHub token.
UNSAFE_TEXT_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}"
)


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
    if set(entry) - {"smoke", "train"} != RELEASE_RECORD_FIELDS:
        raise ReleaseError("production release record has an unexpected field set")
    record = dict(entry)
    if "smoke" in record:
        smoke = record["smoke"]
        if not isinstance(smoke, dict) or set(smoke) != {"staging", "production"}:
            raise ReleaseError("production release smoke evidence is invalid")
        if any(
            value is not None and not DIGEST_RE.fullmatch(str(value)) for value in smoke.values()
        ):
            raise ReleaseError("production release smoke digest is invalid")
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
    if "train" in record:
        _validate_train_evidence(record)
    return record


def _validate_train_evidence(record: Mapping[str, Any]) -> None:
    """Old releases stay readable; new train evidence is complete and typed."""
    train = record["train"]
    fields = {
        "core_sha",
        "web_sha",
        "artifacts",
        "patch_version",
        "migration",
        "dump",
        "restore",
        "promotion_outcome",
        "production_smoke",
        "rollback",
        "paused",
    }

    def require(condition: bool) -> None:
        if not condition:
            raise ValueError("invalid train evidence")

    try:
        require(isinstance(train, dict) and set(train) == fields)
        require(record["requested_by"] == "standing-approval:AUT-72@2026-09-29T19:05Z")
        require(all(SHA_RE.fullmatch(train[k]) for k in ("core_sha", "web_sha")))
        require(_version_parts(train["patch_version"]) is not None)
        require(set(train["artifacts"]) == set(COMPONENTS))
        require(all(DIGEST_RE.fullmatch(v) for v in train["artifacts"].values()))
        migration = train["migration"]
        require(set(migration) == {"from", "to", "classification"})
        require(migration["classification"] == "additive")
        require(all(re.fullmatch(r"[0-9]{8}_[0-9]{4}", migration[k]) for k in ("from", "to")))
        dump = train["dump"]
        require(set(dump) == {"path", "sha256", "bytes"})
        require(isinstance(dump["path"], str) and Path(dump["path"]).is_absolute())
        require(re.fullmatch(r"[0-9a-f]{64}", dump["sha256"]))
        require(type(dump["bytes"]) is int and dump["bytes"] > 0)
        restore = train["restore"]
        require(set(restore) == {"unit", "exit_timestamp"})
        require(restore["unit"] == "ac-restic-postgres-restore-proof@production.service")
        dt.datetime.strptime(restore["exit_timestamp"], "%a %Y-%m-%d %H:%M:%S %Z")
        require(train["promotion_outcome"] in ("promoted", "failed"))
        require(train["production_smoke"] in ("pending", "pass", "fail", "skipped"))
        require(type(train["paused"]) is bool)
        require(isinstance(train["rollback"], dict))
        require(set(train["rollback"]) in (set(), set(COMPONENTS)))
        require(all(isinstance(v, str) and v for v in train["rollback"].values()))
        smoke = record["smoke"]
        require(DIGEST_RE.fullmatch(smoke["staging"]))
        if train["production_smoke"] == "pending":
            require(smoke["production"] is None and not train["rollback"])
        else:
            require(DIGEST_RE.fullmatch(smoke["production"]))
        if record["action"] == "promote":
            require(not train["rollback"])
            require(record["version"] == train["patch_version"])
            require(all(record[k] == train[k] for k in ("core_sha", "web_sha")))
        else:
            require(record["rolled_back_from"] == train["patch_version"])
            require(set(train["rollback"]) == set(COMPONENTS))
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ReleaseError("train_evidence_invalid") from error


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
    backup_tool: Path = Path("/usr/local/libexec/authority-closers/ac-postgres-backup.py")
    sales_xray: Path = Path("/etc/authority-closers/sales-xray")
    engine: Path = Path("/opt/ac-release")
    backups: Path = Path("/srv/authority-closers/backups/application/production")

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

    @property
    def admin(self) -> Path:
        return self.state / "admin"


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
    recovery: dict[str, Any] | None = None


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
        recovered = recovered_core_build(github, sha, run)
        if recovered is not None:
            return Candidate("ready", recovered)
        return Candidate("failed", detail=f"run {run['id']} has no usable {name} artifact")
    return Candidate(
        "ready",
        Build(sha, int(run["id"]), int(artifact["id"]), name, str(artifact["digest"])),
    )


def recovered_core_build(github: Any, sha: str, validation: Mapping[str, Any]) -> Build | None:
    """Admit CI repackaging only with a digest-bound proof of the original push."""

    name = f"ac-application-recovered-{sha}"
    proof_name = f"ac-application-recovery-proof-{sha}"
    data = github.get_json(
        f"/repos/{REPOSITORY}/actions/workflows/{CORE_RECOVERY_WORKFLOW}/runs",
        {"branch": "main", "event": "workflow_dispatch", "per_page": "100"},
    )
    runs = sorted(
        data.get("workflow_runs", []),
        key=lambda run: (run.get("run_number", 0), run.get("run_attempt", 0)),
        reverse=True,
    )
    for run in runs:
        if not (
            run.get("event") == "workflow_dispatch"
            and run.get("head_branch") == "main"
            and SHA_RE.fullmatch(str(run.get("head_sha", "")))
            and run.get("path") == f".github/workflows/{CORE_RECOVERY_WORKFLOW}"
            and run.get("repository", {}).get("full_name") == REPOSITORY
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
        ):
            continue
        # A recovery run executes reviewed main code, while its bundle contains
        # an older release. GitHub's workflow SHA must remain the real run SHA.
        artifact = find_artifact(github, run, name, run["head_sha"])
        proof_artifact = find_artifact(github, run, proof_name, run["head_sha"])
        if artifact is None or proof_artifact is None:
            continue
        if proof_artifact["size_in_bytes"] > RECOVERY_PROOF_MAX_BYTES:
            raise ReleaseError("core recovery proof exceeds its size ceiling")
        with tempfile.TemporaryDirectory(prefix="ac-core-recovery-") as work:
            path = Path(work) / "proof.zip"
            github.download_artifact(proof_artifact["id"], path, proof_artifact["digest"])
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.infolist()
                    if (
                        len(entries) != 1
                        or entries[0].filename != "recovery-proof.json"
                        or entries[0].file_size > RECOVERY_PROOF_MAX_BYTES
                        or entries[0].flag_bits & 1
                    ):
                        raise ReleaseError("core recovery proof archive is invalid")
                    try:
                        proof = json.loads(archive.read(entries[0]))
                    except (ValueError, UnicodeError) as error:
                        raise ReleaseError("core recovery proof is not valid JSON") from error
            except (zipfile.BadZipFile, NotImplementedError) as error:
                raise ReleaseError("core recovery proof archive is invalid") from error
        fields = {
            "schema",
            "repository",
            "release_sha",
            "validation_run_id",
            "recovery_run_id",
            "recovery_head_sha",
            "artifact_id",
            "artifact_name",
            "artifact_digest",
            "manifest_sha256",
            "registry_digests",
            "original_package_job_id",
            "publication_log_sha256",
        }
        if not isinstance(proof, dict) or set(proof) != fields:
            raise ReleaseError("core recovery proof has unexpected fields")
        expected = {
            "schema": "ac.application-recovery/1",
            "repository": REPOSITORY,
            "release_sha": sha,
            "validation_run_id": validation["id"],
            "recovery_run_id": run["id"],
            "recovery_head_sha": run["head_sha"],
            "artifact_id": artifact["id"],
            "artifact_name": name,
            "artifact_digest": artifact["digest"],
        }
        if any(proof.get(key) != value for key, value in expected.items()) or any(
            type(proof[key]) is not int or proof[key] <= 0
            for key in (
                "validation_run_id",
                "recovery_run_id",
                "artifact_id",
                "original_package_job_id",
            )
        ):
            raise ReleaseError(
                "core recovery proof does not match validation/run/artifact identity"
            )
        digests = proof["registry_digests"]
        repositories = dict(
            zip(
                ("api", "learner", "admin", "coach"),
                (
                    f"ghcr.io/authorityclosers/authority-closers-{image}"
                    for image in ("api", "learner-web", "admin-web", "coach-web")
                ),
                strict=True,
            )
        )
        if (
            not DIGEST_RE.fullmatch(str(proof["manifest_sha256"]))
            or not DIGEST_RE.fullmatch(str(proof["publication_log_sha256"]))
            or not isinstance(digests, dict)
            or set(digests) != set(repositories)
            or any(
                not re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", str(digests[key]))
                for key, repository in repositories.items()
            )
        ):
            raise ReleaseError("core recovery proof manifest/image digests are invalid")
        proof["proof_artifact_id"] = proof_artifact["id"]
        proof["proof_artifact_digest"] = proof_artifact["digest"]
        return Build(sha, run["id"], artifact["id"], name, artifact["digest"], proof)
    return None


def verify_recovery_manifest(build: Build, bundle: Path) -> None:
    if build.recovery is None:
        return
    manifest = bundle / "release-images.env"
    if f"sha256:{_sha256_file(manifest)}" != build.recovery["manifest_sha256"]:
        raise ReleaseError("recovered core manifest does not match its CI proof")
    values = read_env_file(manifest)
    if values.get("AC_RELEASE_ID") != build.sha or any(
        values.get(f"AC_{key.upper()}_REGISTRY_DIGEST") != digest
        for key, digest in build.recovery["registry_digests"].items()
    ):
        raise ReleaseError("recovered core manifest does not match its release/image proof")


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


def _safe_text(value: Any, limit: int = 200) -> str | None:
    return None if value is None else UNSAFE_TEXT_RE.sub("[redacted]", str(value))[:limit]


def _release_notes(git_dir: Path, from_ref: str, to_sha: str) -> list[str]:
    """Merged pull-request subjects, newest first, from the installed release_notes.py."""

    spec = importlib.util.spec_from_file_location(
        "ac_release_notes", Path(__file__).resolve().with_name("release_notes.py")
    )
    if spec is None or spec.loader is None:
        raise OSError("release_notes.py is not installed beside the engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.release_notes(git_dir, from_ref, to_sha))


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
    _lock_depth: int = field(default=0, init=False)
    _read_only: bool = field(default=False, init=False)

    # -- state ---------------------------------------------------------------

    def is_paused(self, environment: str) -> bool:
        return self.paths.paused_flag(environment).exists()

    def set_paused(self, environment: str, paused: bool, reason: str = "") -> None:
        flag = self.paths.paused_flag(environment)
        if paused:
            flag.write_text(json.dumps({"at": _now(), "reason": reason}) + "\n", encoding="utf-8")
        else:
            if environment == "production" and (self.paths.state / "train-inflight.json").exists():
                interrupted = self.paths.state / "train-inflight.json"
                pair = json.loads(interrupted.read_text(encoding="utf-8"))["pair"]
                if len(pair) != 2 or any(not SHA_RE.fullmatch(sha) for sha in pair):
                    raise ReleaseError("invalid interrupted train pair")
                self.train_state(
                    f"train-failed/{'-'.join(pair)}.json",
                    {"reason": "interrupted_train_acknowledged", "at": _now()},
                )
                interrupted.unlink()
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

        records = self.release_events()
        current = records[-1] if records else None
        previous = records[-2] if len(records) > 1 else None
        return current, previous

    def release_events(self) -> list[dict[str, Any]]:
        """Production releases in event order, one entry per promote or rollback."""

        # A completed smoke record supersedes the initial promote event, append-only.
        records: list[dict[str, Any]] = []
        for entry in self.release_records():
            if (
                records
                and entry["action"] == records[-1]["action"] == "promote"
                and entry["version"] == records[-1]["version"]
            ):
                records[-1] = entry
            else:
                records.append(entry)
        return records

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
        if self._read_only:
            return sha
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

        if bump not in BUMPS:
            raise ReleaseError("version bump must be patch, minor, or major")
        return self.next_versions()[bump]

    def next_versions(self, *, refresh: bool = True) -> dict[str, str]:
        """Every bump's next version from one tag and ledger read."""

        if refresh:
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
        return {
            "patch": f"v{major}.{minor}.{patch + 1}",
            "minor": f"v{major}.{minor + 1}.0",
            "major": f"v{major + 1}.0.0",
        }

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

    def staging_pair(self, *, refresh: bool = True) -> tuple[str, str]:
        """The exact running, successful staging pair accepted by promote."""
        core_sha = self.current_core("staging")
        web_sha, _ = self.current_web("staging")
        if core_sha is None or web_sha is None:
            raise ReleaseError("staging does not have a complete core and web pair")
        head = (
            self.main_head()
            if refresh
            else self.run(
                ["git", f"--git-dir={self.paths.mirror}", "rev-parse", "refs/heads/main"]
            ).stdout.strip()
        )
        if not self.is_ancestor(core_sha, head) or not self.is_ancestor(web_sha, head):
            raise ReleaseError("both staging commits must be on main")
        if not self.passed_staging(core_sha, "core") or not self.passed_staging(web_sha, "web"):
            raise ReleaseError("both staging components must have a successful staging deploy")
        if any(self.paths.failed_flag("staging", component).exists() for component in COMPONENTS):
            raise ReleaseError("staging has a failed deploy that must be cleared first")
        core_build = self.stored_build(core_sha, "core")
        web_build = self.stored_build(web_sha, "web")
        if core_build is None or web_build is None:
            raise ReleaseError("the stored builds for the staging pair are incomplete")
        return core_sha, web_sha

    def promote(
        self,
        bump: str,
        version: str,
        *,
        requested_by: str,
        trigger: str,
        expected_sha: str | None = None,
        pair: tuple[str, str] | None = None,
        smoke: dict[str, Any] | None = None,
        train: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """Promote the tested staging pair, recording a release only on success.

        ``dry_run`` runs every guard and rehearses each attempt, and changes nothing.
        """

        with self.locked(wait=True):
            if not self.paths.production_enabled.exists():
                raise ReleaseError("production deploys are not enabled on this server yet")
            core_sha, web_sha = self.staging_pair()
            if pair is not None and pair != (core_sha, web_sha):
                raise ReleaseError("staging_moved")
            core_build = self.stored_build(core_sha, "core")
            web_build = self.stored_build(web_sha, "web")
            assert core_build is not None and web_build is not None
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

            record = {
                "version": version,
                "core_sha": core_sha,
                "web_sha": web_sha,
                "requested_by": requested_by,
                "at": _now(),
                "action": "promote",
                "rolled_back_from": None,
                **({"smoke": smoke} if smoke is not None else {}),
                **({"train": train} if train is not None else {}),
            }
            _validate_release_record(record)  # Before any production mutation.
            if dry_run:
                if trigger == "train":
                    raise ReleaseError("the train does not rehearse through promote")
                rehearsal = [(core_build, "core")] if production_core != core_sha else []
                return [
                    self.attempt("production", component, build, dry_run=True, trigger=trigger)
                    for build, component in [*rehearsal, (web_build, "web")]
                ]
            if trigger == "train":
                if (
                    train is None
                    or bump != "patch"
                    or pair is None
                    or train["artifacts"]
                    != {"core": core_build.artifact_digest, "web": web_build.artifact_digest}
                    or train["promotion_outcome"] != "promoted"
                    or train["production_smoke"] != "pending"
                    or train["paused"]
                ):
                    raise ReleaseError("train_evidence_invalid")
                self.train_state("train-inflight.json", {"pair": list(pair), "at": _now()})
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
            self.append_release(record)
            return attempts

    # -- release train -------------------------------------------------------

    def restore_check_ok(self) -> bool:
        return self.restore_check_evidence() is not None

    def restore_check_evidence(self) -> dict[str, str] | None:
        """Latest production off-host proof, not a local backup or staging drill."""
        try:
            result = self.run(
                [
                    "systemctl",
                    "show",
                    "ac-restic-postgres-restore-proof@production.service",
                    "--property=LoadState,ActiveState,Result,ExecMainCode,ExecMainStatus,ExecMainExitTimestamp",
                ],
                env={"TZ": "UTC"},
                check=False,
                timeout=15,
            )
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            exited = dt.datetime.strptime(
                values.get("ExecMainExitTimestamp", ""), "%a %Y-%m-%d %H:%M:%S %Z"
            ).replace(tzinfo=dt.UTC)
            valid = (
                result.returncode == 0
                and values.get("LoadState") == "loaded"
                and values.get("ActiveState") == "inactive"
                and values.get("Result") == "success"
                and values.get("ExecMainCode") == "1"
                and values.get("ExecMainStatus") == "0"
                and 0 <= self.clock() - exited.timestamp() < 8 * 86400
            )
            return (
                {
                    "unit": "ac-restic-postgres-restore-proof@production.service",
                    "exit_timestamp": values["ExecMainExitTimestamp"],
                }
                if valid
                else None
            )
        except (OSError, ValueError, ReleaseError, subprocess.SubprocessError):
            return None

    def migration_head(self, sha: str | None) -> str:
        if sha is None or not SHA_RE.fullmatch(sha):
            raise ReleaseError("migration_head_missing")
        manifest = self.paths.application / "releases" / sha / "release-images.env"
        value = read_env_file(manifest).get("AC_MIGRATION_HEAD", "")
        if not re.fullmatch(r"[0-9]{8}_[0-9]{4}", value):
            raise ReleaseError("migration_head_missing")
        return value

    @contextlib.contextmanager
    def train_source(self, sha: str) -> Iterator[Path]:
        # Only the selected core commit supplies executable smoke/classifier code.
        with self.stage(sha) as stage:
            source = stage / "source"
            for prefix in ("scripts/ops", "db/migrations"):
                archive, _ = self.source_archive(sha, stage, prefix)
                self.extract_source(archive, source, prefix)
            yield source

    def train_state(self, name: str, value: Mapping[str, Any]) -> None:
        path = self.paths.state / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(value), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def train_event(self, kind: str, text: str, **fields: Any) -> bool:
        # Use the installed notifier's redaction and spool deduplication contract.
        argv = [
            "ac-train-notify",
            kind,
            "--spool",
            str(self.paths.state / "notify"),
            "--key",
            f"train:{kind}:{text}:{fields.get('pair', '')}",
            "--text",
            text,
        ]
        for key, value in fields.items():
            argv.extend(["--field", f"{key}={value}"])
        try:
            return self.run(argv, timeout=30, check=False).returncode == 0
        except Exception:
            # Notification delivery must never change the canonical release outcome.
            return False

    def train_result(
        self,
        reason: str,
        *,
        result: str,
        alert: bool = False,
        critical: bool = False,
        pair: tuple[str, str] | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        entry = {
            "at": _now(),
            "action": "train",
            "result": result,
            "reason": reason,
            "pair": list(pair) if pair else None,
            **details,
        }
        self.train_state("last-train.json", entry)
        self.record(entry)
        notify_failed = []
        if alert:
            delivered = self.train_event(
                "alert",
                reason,
                severity="critical" if critical or result == "rolled_back" else "error",
                pair="-".join(pair) if pair else "none",
                **details,
            )
            if not delivered:
                notify_failed.append("alert")
        if result in ("promoted", "rolled_back", "failed"):
            # Unknown components are explicit fields; zeros are only display placeholders.
            dev = self.current_core("development")
            staging = self.current_core("staging")
            production = self.current_core("production")
            icon = "✅" if result == "promoted" else "❌"
            line = (
                f"dev {(dev or '0000000')[:7]} · staging {(staging or '0000000')[:7]} · "
                f"prod {(production or '0000000')[:7]} · smoke {icon}"
            )
            delivered = self.train_event(
                "status",
                line,
                result=result,
                reason=reason,
                pair="-".join(pair) if pair else "none",
                unknown=",".join(
                    k
                    for k, v in (("dev", dev), ("staging", staging), ("prod", production))
                    if not v
                ),
            )
            if not delivered:
                notify_failed.append("status")
        if notify_failed:
            entry["notify_failed"] = notify_failed
            self.train_state("last-train.json", entry)
            self.record(entry)  # Append delivery outcome; preserve the release result.
        return entry

    def train_smoke(
        self, environment: str, pair: tuple[str, str], source: Path, *, reuse: bool = False
    ) -> dict[str, str]:
        path = self.paths.state / "smoke" / environment / ("-".join(pair) + ".json")

        def read_record(max_age: int) -> dict[str, str] | None:
            try:
                if not 0 <= self.clock() - path.stat().st_mtime < max_age:
                    return None
                record = json.loads(path.read_text(encoding="utf-8"))
                claimed = str(record.pop("digest"))
                digest = (
                    "sha256:"
                    + hashlib.sha256(
                        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest()
                )
                if claimed.removeprefix("sha256:") != digest.removeprefix("sha256:"):
                    return None
                if record.get("result") not in ("pass", "fail", "skipped"):
                    return None
                if record.get("environment") != environment:
                    return None
                for key, value in zip(("core_sha", "web_sha"), pair, strict=True):
                    if record.get(key) != value:
                        return None
                # Preserve the full original record before T3 replaces its pair cache.
                evidence = self.paths.state / "train-smoke" / (digest[7:] + ".json")
                if not evidence.exists():
                    self.train_state(
                        str(evidence.relative_to(self.paths.state)), {**record, "digest": claimed}
                    )
                return {"result": record["result"], "digest": digest}
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                return None

        cached = read_record(6 * 3600) if reuse else None
        if cached is not None and cached["result"] == "pass":
            return cached
        started = self.clock()
        try:
            result = self.run(
                [
                    "python3",
                    str(source / "scripts/ops/ac_smoke.py"),
                    environment,
                    "--core",
                    pair[0],
                    "--web",
                    pair[1],
                    "--state-dir",
                    str(self.paths.state / "smoke"),
                ],
                cwd=source,
                check=False,
                timeout=1560,
            )
            record = read_record(1800)
            if (
                record
                and path.stat().st_mtime >= started
                and (result.returncode == 0 or record["result"] != "pass")
            ):
                return record
        except (OSError, ValueError, ReleaseError, subprocess.SubprocessError):
            pass
        return self.failed_smoke(environment, pair)

    def failed_smoke(self, environment: str, pair: tuple[str, str]) -> dict[str, str]:
        record = {
            "result": "fail",
            "reason": "smoke_execution_or_record_failed",
            "environment": environment,
            "core_sha": pair[0],
            "web_sha": pair[1],
            "at": self.clock(),
        }
        digest = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )
        self.train_state(f"train-smoke/{digest[7:]}.json", {**record, "digest": digest})
        return {"result": "fail", "digest": digest}

    def train_disk_check(self) -> None:
        previous = sorted(
            (self.paths.backups / "train").glob("*/backup.dump"),
            key=lambda path: path.stat().st_mtime,
        )
        if not previous:
            previous = sorted(
                (self.paths.backups / "logical").glob("*/backup.dump"),
                key=lambda path: path.stat().st_mtime,
            )
        if not previous or previous[-1].stat().st_size <= 0:
            raise ReleaseError("dump_baseline_missing")
        if shutil.disk_usage(self.paths.backups).free < 2 * previous[-1].stat().st_size:
            raise ReleaseError("dump_disk_low")

    def train_dump(self) -> str:
        self.train_disk_check()
        logical = self.paths.backups / "logical"
        before = set(logical.glob("*/backup.dump"))
        started = self.clock()
        self.run(
            ["ac-postgres-backup", "--environment", "production", "--capture-only"], timeout=900
        )
        candidates = set(logical.glob("*/backup.dump")) - before
        if len(candidates) != 1:
            raise ReleaseError("dump_capture_missing")
        dump = candidates.pop()
        if (
            not started <= dump.stat().st_mtime <= self.clock()
            or self.clock() - dump.stat().st_mtime >= 1800
        ):
            raise ReleaseError("dump_stale")
        metadata = json.loads(dump.with_name("metadata.json").read_text(encoding="utf-8"))
        if (
            metadata.get("environment") != "production"
            or metadata.get("release_id") != self.current_core("production")
            or metadata.get("dump_sha256") != _sha256_file(dump)
            or metadata.get("dump_bytes") != dump.stat().st_size
        ):
            raise ReleaseError("dump_provenance_invalid")
        # pg_restore is supplied by the running PostgreSQL container, not a host package.
        self.run(
            [
                "bash",
                "-c",
                "docker exec -i ac-application-production-postgres-1 "
                'pg_restore --list < "$1" > /dev/null',
                "train-verify",
                str(dump),
            ],
            timeout=60,
        )
        if self.clock() - dump.stat().st_mtime >= 1800:
            raise ReleaseError("dump_stale")
        ring = self.paths.backups / "train"
        ring.mkdir(mode=0o700, exist_ok=True)
        destination = ring / dump.parent.name
        with tempfile.TemporaryDirectory(prefix=".capture-", dir=ring) as temporary:
            for name in ("backup.dump", "metadata.json"):
                shutil.copy2(dump.parent / name, Path(temporary) / name)
            os.rename(temporary, destination)
        for old in sorted(ring.glob("*-production"), key=lambda path: path.name)[:-3]:
            if (
                old.is_dir()
                and not old.is_symlink()
                and re.fullmatch(r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-[0-9]+-production", old.name)
            ):
                shutil.rmtree(old)
        return str(destination / "backup.dump")

    def rollback_core(self, environment: str, *, record_release: bool = True) -> dict[str, Any]:
        with self.locked(wait=True):
            current_sha = self.current_core(environment)
            current, previous = (
                self.production_releases() if environment == "production" else (None, None)
            )
            if environment == "production":
                if current is None or previous is None or current["core_sha"] != current_sha:
                    raise ReleaseError("core_rollback_history_missing")
                target = previous["core_sha"]
                records = self.release_records()
                departed = {
                    before["core_sha"]
                    for before, after in zip(records[:-1], records[1:], strict=True)
                    if after["action"] == "rollback" and before["core_sha"] != after["core_sha"]
                }
                # The spec limits production to the previous release record.
                # Never interpret a second rollback as permission to restore a departed core.
                if target != current_sha and target in departed:
                    raise ReleaseError("core_rollback_target_departed")
            else:
                history = [
                    entry
                    for entry in self.history(10_000)
                    if entry.get("environment") == environment
                    and entry.get("component") == "core"
                    and entry.get("result") == "success"
                ]
                departed = {
                    entry.get("previous") for entry in history if entry.get("action") == "rollback"
                }
                successes = [
                    entry["sha"] for entry in history if entry.get("action") in (None, "deploy")
                ]
                if current_sha not in successes:
                    raise ReleaseError("core_rollback_history_missing")
                index = len(successes) - 1 - successes[::-1].index(current_sha)
                target = next(
                    (
                        sha
                        for sha in reversed(successes[:index])
                        if sha != current_sha and sha not in departed
                    ),
                    None,
                )
            if target is None or self.migration_head(target) != self.migration_head(current_sha):
                raise ReleaseError("core_rollback_schema_changed")
            if target == current_sha:
                return {"restored_sha": target, "result": "unchanged"}
            build = self.stored_build(target, "core")
            if build is None:
                raise ReleaseError("core_rollback_build_missing")
            try:
                result = self.deploy_core(environment, build, rollback_only=True)
            except (ReleaseError, OSError, ValueError, subprocess.SubprocessError):
                self.set_paused(
                    environment, True, "core rollback failed; supervised recovery required"
                )
                raise
            self.record(
                {
                    "at": _now(),
                    "environment": environment,
                    "component": "core",
                    "action": "rollback",
                    "sha": target,
                    "previous": current_sha,
                    "result": "success",
                }
            )
            if environment == "production" and record_release:
                self.record_rollback(current, previous, {})
            return {**result, "restored_sha": target, "result": "success"}

    def record_rollback(
        self,
        current: dict[str, Any] | None,
        previous: dict[str, Any] | None,
        smoke: dict[str, Any],
        train: dict[str, Any] | None = None,
        requested_by: str | None = None,
    ) -> None:
        if current is None:
            raise ReleaseError("core_rollback_history_missing")
        core, web = self.current_core("production"), self.current_web("production")[0]
        complete = previous is not None and (core, web) == (
            previous["core_sha"],
            previous["web_sha"],
        )
        self.append_release(
            {
                "version": previous["version"]
                if complete and previous is not None
                else current["version"],
                "core_sha": core,
                "web_sha": web,
                "requested_by": requested_by
                or (current["requested_by"] if train is not None else "rollback:train-or-cli"),
                "at": _now(),
                "action": "rollback",
                "rolled_back_from": current["version"],
                **({"smoke": smoke} if smoke else {}),
                **({"train": train} if train is not None else {}),
            }
        )

    def rollback_target(self) -> dict[str, Any]:
        """The release a production rollback restores; never changes anything."""

        return self._rollback_plan()[1]

    def _rollback_plan(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.paths.production_enabled.exists():
            raise ReleaseError("production deploys are not enabled on this server yet")
        current, target = self.production_releases()
        if current is None or target is None:
            raise ReleaseError("Rollback not available: there is no earlier production release.")
        if current["action"] == "rollback":
            raise ReleaseError("Rollback not available: the current release is already a rollback.")
        running_web = self.current_web("production")[0]
        # The target core with the current web is a failed web step: retrying is allowed.
        if (self.current_core("production"), running_web) not in (
            (current["core_sha"], current["web_sha"]),
            (target["core_sha"], current["web_sha"]),
        ):
            raise ReleaseError(
                f"Rollback not available: production does not run {current['version']}."
            )
        if any(self.stored_build(target[f"{c}_sha"], c) is None for c in COMPONENTS):
            raise ReleaseError(
                f"Rollback not available: the builds of {target['version']} are no longer stored."
            )
        try:
            heads = {self.migration_head(record["core_sha"]) for record in (current, target)}
        except ReleaseError:
            raise ReleaseError(
                "Rollback not available: the database version of a release is unknown."
            ) from None
        if len(heads) != 1:
            raise ReleaseError(
                f"Rollback not available: the database changed in {current['version']}."
            )
        if running_web != target["web_sha"]:
            entry = self.web_rollback_entry("production")
            if entry is None or entry.get("previous") != target["web_sha"]:
                raise ReleaseError(
                    f"Rollback not available: the web release of {target['version']} "
                    "cannot be restored."
                )
        return current, target

    def rollback_production(
        self,
        *,
        requested_by: str,
        trigger: str,
        expected_sha: str | None = None,
        expected_version: str | None = None,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """Restore the previous production pair; record one release only on success."""

        with self.locked(wait=True):
            current, target = self._rollback_plan()
            production_core = self.current_core("production")
            if expected_sha is not None and expected_sha != production_core:
                raise ReleaseError("production core changed since this rollback was requested")
            if expected_version is not None and expected_version != current["version"]:
                raise ReleaseError("production version changed since this rollback was requested")
            needed = {
                "core": production_core != target["core_sha"],
                "web": self.current_web("production")[0] != target["web_sha"],
            }
            steps: list[dict[str, Any]] = []
            for component in COMPONENTS:
                step: dict[str, Any] = {"component": component, "result": "skipped", "error": None}
                steps.append(step)
                if not needed[component]:
                    continue
                if dry_run:
                    step["result"] = "dry-run"
                    continue
                try:
                    if component == "core":
                        self.rollback_core("production", record_release=False)
                    else:
                        restored = self.rollback_web("production")
                        matches = self.current_web("production")[0] == target["web_sha"]
                        self.record(
                            {
                                "at": _now(),
                                "environment": "production",
                                "component": "web",
                                "action": "rollback",
                                "result": "success" if matches else "failed",
                                "trigger": trigger,
                                **restored,
                            }
                        )
                        if not matches:
                            raise ReleaseError("the restored web release is not the target release")
                    step["result"] = "success"
                except (ReleaseError, OSError, ValueError, subprocess.SubprocessError) as error:
                    step["result"] = "failed"
                    step["error"] = _safe_text(error)
                    if component == "web":
                        self.set_paused(
                            "production", True, "web rollback failed; supervised recovery required"
                        )
                    return steps
            if not dry_run:
                self.record_rollback(current, target, {}, requested_by=requested_by)
            return steps

    def train_gate(self) -> tuple[str | None, bool]:
        for refuse, reason, alert in (
            (not self.paths.production_enabled.exists(), "production_disabled", False),
            (not (self.paths.config / "train.enabled").exists(), "train_disabled", False),
            (self.is_paused("production"), "production_paused", True),
            (
                any(self.paths.failed_flag("production", c).exists() for c in COMPONENTS),
                "production_failed",
                True,
            ),
        ):
            if refuse:
                return reason, alert
        return (None, False) if self.restore_check_ok() else ("restore_check_failed", True)

    def train(self, *, now: bool = False, dry_run: bool = False) -> dict[str, Any]:
        """--now is an operator entry point; it never bypasses any gate."""
        with self.locked(wait=True):
            self._read_only = dry_run
            pair = None
            try:
                interrupted = self.paths.state / "train-inflight.json"
                if interrupted.exists():
                    if not dry_run:
                        self.set_paused(
                            "production", True, "interrupted train requires Root recovery"
                        )
                    raise ReleaseError("train_interrupted")
                reason, alert = self.train_gate()
                if reason:
                    return (
                        {"result": "refused", "reason": reason}
                        if dry_run
                        else self.train_result(reason, result="refused", alert=alert)
                    )
                pair = self.staging_pair(refresh=not dry_run)
                production_pair = (
                    self.current_core("production"),
                    self.current_web("production")[0],
                )
                if pair == production_pair:
                    return {"result": "nothing_to_ship"}
                failed = f"train-failed/{'-'.join(pair)}.json"
                if (self.paths.state / failed).exists():
                    return {"result": "refused", "reason": "train_failed", "pair": list(pair)}
                with self.train_source(pair[0]) as source:
                    if not dry_run:
                        try:
                            staging = self.train_smoke("staging", pair, source, reuse=True)
                        except (OSError, ValueError, ReleaseError, subprocess.SubprocessError):
                            staging = self.failed_smoke("staging", pair)
                        if staging["result"] != "pass":
                            self.train_state(
                                failed, {"reason": "staging_smoke_failed", "at": _now()}
                            )
                            raise ReleaseError("staging_smoke_failed")
                    classification = self.run(
                        [
                            "python3",
                            str(source / "scripts/ops/migration_safety.py"),
                            "--versions",
                            str(source / "db/migrations/versions"),
                            "--from",
                            self.migration_head(self.current_core("production")),
                            "--to",
                            self.migration_head(pair[0]),
                            "--json",
                        ],
                        check=False,
                        timeout=60,
                    )
                    try:
                        verdict = json.loads(classification.stdout)
                    except ValueError:
                        verdict = None
                    if (
                        classification.returncode != 0
                        or not isinstance(verdict, dict)
                        or verdict.get("verdict") != "additive"
                    ):
                        raise ReleaseError("needs supervised promote")
                    self.train_disk_check()
                    if dry_run:
                        return {
                            "result": "dry-run",
                            "pair": list(pair),
                            "would": [
                                "staging_smoke_or_reuse",
                                "verified_production_dump",
                                "patch_promote",
                                "production_smoke_or_rollback",
                            ],
                        }
                    dump = self.train_dump()
                    reason, _ = self.train_gate()
                    if reason:
                        raise ReleaseError(reason)
                    # Validate the pair before arming interruption containment.
                    if self.staging_pair() != pair:
                        raise ReleaseError("staging_moved")
                    if production_pair != (
                        self.current_core("production"),
                        self.current_web("production")[0],
                    ):
                        raise ReleaseError("production_moved")
                    smoke = {"staging": staging["digest"], "production": None}
                    version = self.next_version("patch")
                    evidence = {
                        "core_sha": pair[0],
                        "web_sha": pair[1],
                        "patch_version": version,
                        "artifacts": {
                            component: self.stored_build(sha, component).artifact_digest
                            for component, sha in zip(COMPONENTS, pair, strict=True)
                        },
                        "migration": {
                            "from": self.migration_head(production_pair[0]),
                            "to": self.migration_head(pair[0]),
                            "classification": verdict["verdict"],
                        },
                        "dump": {
                            "path": dump,
                            "sha256": _sha256_file(Path(dump)),
                            "bytes": Path(dump).stat().st_size,
                        },
                        "restore": self.restore_check_evidence(),
                        "promotion_outcome": "promoted",
                        "production_smoke": "pending",
                        "rollback": {},
                        "paused": self.is_paused("production"),
                    }
                    attempts = self.promote(
                        "patch",
                        version,
                        pair=pair,
                        expected_sha=production_pair[0],
                        requested_by="standing-approval:AUT-72@2026-09-29T19:05Z",
                        trigger="train",
                        smoke=smoke,
                        train=evidence,
                    )
                    if any(entry.get("result") != "success" for entry in attempts):
                        self.train_state(failed, {"reason": "promotion_failed", "at": _now()})
                        self.set_paused("production", True, "train promotion failed")
                        raise ReleaseError("promotion_failed")
                    current, previous = self.production_releases()
                    try:
                        production = self.train_smoke("production", pair, source)
                    except (OSError, ValueError, ReleaseError, subprocess.SubprocessError):
                        production = self.failed_smoke("production", pair)
                    smoke["production"] = production["digest"] or None
                    assert current is not None
                    if production["result"] != "pass":
                        # Persist pause first even if writing smoke evidence or the ledger fails.
                        self.set_paused(
                            "production", True, "production smoke failed; Root resume required"
                        )
                    evidence = {
                        **evidence,
                        "production_smoke": production["result"],
                        "paused": self.is_paused("production"),
                    }
                    self.append_release(
                        {**current, "at": _now(), "smoke": smoke, "train": evidence}
                    )
                    if production["result"] == "pass":
                        interrupted.unlink()
                        return self.train_result(
                            "promoted", result="promoted", pair=pair, dump=dump
                        )
                    # Persist containment before rollback: a crash cannot retry this pair.
                    self.train_state(failed, {"reason": "production_smoke_failed", "at": _now()})
                    self.set_paused(
                        "production", True, "train production smoke failed; Root resume required"
                    )
                    rollback: dict[str, str] = {}
                    for component, operation in (
                        ("web", self.rollback_web),
                        ("core", self.rollback_core),
                    ):
                        # A core-only promote must not undo an earlier unrelated web release.
                        if component == "web" and production_pair[1] == pair[1]:
                            rollback[component] = "unchanged"
                            continue
                        try:
                            operation(
                                "production",
                                **({"record_release": False} if component == "core" else {}),
                            )
                            rollback[component] = "restored"
                        except (
                            OSError,
                            ValueError,
                            ReleaseError,
                            subprocess.SubprocessError,
                        ) as error:
                            rollback[component] = (
                                "skipped: migration head changed"
                                if str(error) == "core_rollback_schema_changed"
                                else "failed; supervised recovery required"
                            )
                    self.record_rollback(
                        current,
                        previous,
                        smoke,
                        {**evidence, "rollback": rollback, "paused": self.is_paused("production")},
                    )
                    interrupted.unlink()
                    return self.train_result(
                        "production_smoke_failed",
                        result="rolled_back",
                        alert=True,
                        pair=pair,
                        **rollback,
                    )
            except (OSError, ValueError, ReleaseError, subprocess.SubprocessError) as error:
                # Never copy raw subprocess output or filesystem diagnostics to the spool.
                safe = str(error) if isinstance(error, ReleaseError) else "train_check_failed"
                if dry_run:
                    return {"result": "refused", "reason": safe}
                if (self.paths.state / "train-inflight.json").exists():
                    self.set_paused(
                        "production", True, "train interrupted or failed; Root recovery required"
                    )
                return self.train_result(
                    safe,
                    result="failed",
                    alert=True,
                    pair=pair,
                    critical=(self.paths.state / "train-inflight.json").exists(),
                )
            finally:
                self._read_only = False

    # -- artifacts -------------------------------------------------------------

    def store_bundle(self, build: Build, component: str, expected: frozenset[str]) -> Path:
        """Download once into the immutable local store and return its path."""

        target = self.paths.store / build.sha / component
        # Provenance sits beside the bundle: verifiers require exact file sets.
        provenance = self.paths.store / build.sha / f"{component}.provenance.json"
        if provenance.exists():
            if build.recovery is not None and self.stored_build(build.sha, component) != build:
                raise ReleaseError("stored core provenance differs from recovered artifact")
            verify_checksums(target, expected - {"SHA256SUMS"})
            verify_recovery_manifest(build, target)
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
            verify_recovery_manifest(build, unpacked)
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
                        **({"recovery": build.recovery} if build.recovery is not None else {}),
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
        self, environment: str, build: Build, *, dry_run: bool = False, rollback_only: bool = False
    ) -> dict[str, Any]:
        log = self.new_log(environment, "core", build.sha)
        bundle = self.store_bundle(build, "core", CORE_FILES)
        blockers: list[str] = []
        planned: dict[str, str] = {}
        previous = self.current_core(environment)
        native_plan: dict[str, Any] | None = None
        with self.stage(build.sha) as stage:
            try:
                try:
                    self.require_backup_support(bundle)
                except ReleaseError:
                    if rollback_only:
                        raise
                    planned = self.install_backup_foundation(
                        environment, build, bundle, stage, log, dry_run=dry_run
                    )
            except ReleaseError as error:
                if not dry_run:
                    raise
                # A rehearsal reports every blocker instead of stopping at the first.
                blockers.append(str(error))
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
            if rollback_only:
                # Old target releases lack the no-database rollback mode. Use the
                # installed engine's reviewed controller against the old artifacts.
                controller_sha = self.installed_engine()
                if controller_sha is None:
                    raise ReleaseError("rollback controller provenance is missing")
                controller_archive, controller_digest = self.source_archive(
                    controller_sha, stage, "infra/application"
                )
                controller = stage / "controller"
                self.extract_source(controller_archive, controller, "infra/application")
                installer = controller / "infra/application/scripts/install-application-release.sh"
                self.run(
                    [
                        "python3",
                        str(installer.with_name("verify-release-archive.py")),
                        str(controller_archive),
                        controller_digest,
                        controller_sha,
                    ],
                    log=log,
                )
                if "AC_CORE_ROLLBACK_ONLY" not in installer.read_text(encoding="utf-8"):
                    raise ReleaseError(
                        "rollback controller does not support application-only rollback"
                    )
            env = {
                "AC_TARGET_ENVIRONMENT": environment,
                "AC_RELEASE_ID": build.sha,
                "AC_RELEASE_ARCHIVE": str(archive),
                "AC_RELEASE_ARCHIVE_SHA256": archive_sha,
                "AC_IMAGE_BUNDLE_DIR": str(bundle_dir),
                **(
                    {
                        "AC_CORE_ROLLBACK_ONLY": "1",
                        "AC_ROLLBACK_FROM": previous or "",
                        "AC_ROLLBACK_CONTROLLER_SHA256": _sha256_file(installer),
                    }
                    if rollback_only
                    else {}
                ),
            }
            activation: dict[str, Any] = {}
            if not rollback_only:
                # Rollback uses the target's historical activation (including absence).
                # Forward carry-over must never create or widen an older worker's scope.
                try:
                    self.keep_native_build(build.sha)
                    if (
                        environment == "staging"
                        and self.native_preparation_path(build.sha).exists()
                    ):
                        native_plan = self.native_deployment_plan(build.sha, source, stage)
                        activation = {
                            "sales_xray_activation": "prepared native transition",
                            "sales_xray_native": build.sha,
                            "sales_xray_previous_native": native_plan["previous_native"],
                            "sales_xray_approval_sha256": native_plan["approval_sha256"],
                        }
                    else:
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
                    **planned,
                    **activation,
                }
            try:
                if native_plan is not None:
                    self.install_native_transition(build.sha, native_plan, source, log)
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
                if native_plan is not None:
                    self.record(
                        {
                            "at": _now(),
                            "action": "native-transition",
                            "target": build.sha,
                            "previous_core": previous,
                            "result": "success",
                            "approval_sha256": native_plan["approval_sha256"],
                            "provider_calls": 0,
                        }
                    )
            except Exception as error:
                if native_plan is not None and native_plan.get("armed"):
                    # Persist containment first. A failed recovery cannot restart the train.
                    self.set_paused("staging", True, "native/core transition failed")
                    self.paths.failed_flag("staging", "core").write_text(
                        build.sha + "\n", encoding="utf-8"
                    )
                    try:
                        self.restore_native_transition(build.sha, native_plan, log)
                    except Exception as recovery_error:
                        self.record(
                            {
                                "at": _now(),
                                "action": "native-transition",
                                "target": build.sha,
                                "previous_core": previous,
                                "result": "recovery-failed",
                            }
                        )
                        raise ReleaseError(
                            "native/core recovery could not be verified; containment retained"
                        ) from recovery_error
                    raise ReleaseError(
                        "native/core transition failed; pinned predecessor restored"
                    ) from error
                raise
        return {"previous": previous, "log": str(log), **activation}

    @staticmethod
    def bundle_migration_head(bundle: Path) -> str:
        head = ""
        for line in (bundle / "release-images.env").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key == "AC_MIGRATION_HEAD":
                head = value.strip()
        if not re.fullmatch(r"[0-9]{8}_[0-9]{4}", head):
            raise ReleaseError("release bundle has no valid AC_MIGRATION_HEAD")
        return head

    @staticmethod
    def backup_recognises(tool: Path, head: str) -> bool:
        try:
            return f'"{head}"' in tool.read_text(encoding="utf-8")
        except OSError:
            return False

    def require_backup_support(self, bundle: Path) -> None:
        """Check the installed tool the backup wrapper actually executes."""
        head = self.bundle_migration_head(bundle)
        if not self.backup_recognises(self.paths.backup_tool, head):
            raise ReleaseError(
                f"the installed foundation backup tools do not recognise migration {head}; "
                "backups for every environment would stop"
            )

    def install_backup_foundation(
        self, environment: str, build: Build, bundle: Path, stage: Path, log: Path, *, dry_run: bool
    ) -> dict[str, str]:
        head = self.bundle_migration_head(bundle)
        entry: dict[str, Any] = {
            "at": _now(),
            "action": "foundation-backup-install",
            "environment": environment,
            "sha": build.sha,
            "migration": head,
            "log": str(log),
        }
        try:
            prefix = "infra/vps-foundation"
            archive, digest = self.source_archive(build.sha, stage, prefix)
            source = stage / "foundation-source"
            self.extract_source(archive, source, prefix)
            scripts = source / prefix / "scripts"
            heads = {head}
            for running_environment in ENVIRONMENTS:
                running = self.current_core(running_environment)
                if running is not None:
                    heads.add(self.migration_head(running))
            for required in sorted(heads):
                if not self.backup_recognises(scripts / "ac-postgres-backup.py", required):
                    raise ReleaseError(
                        f"candidate foundation backup tool does not recognise migration {required}"
                    )
            if dry_run:
                return {"foundation_backup_install": head}
            completed = self.run(
                ["bash", str(scripts / "install-foundation-release.sh")],
                env={
                    "AC_RELEASE_ID": f"foundation-{build.sha}",
                    "AC_RELEASE_ARCHIVE": str(archive),
                    "AC_RELEASE_ARCHIVE_SHA256": digest,
                    "AC_INSTALL_SCOPE": "backup",
                },
                timeout=900,
                log=log,
                check=False,
            )
            if completed.returncode != 0:
                raise ReleaseError(
                    f"foundation backup installer exited with {completed.returncode}; see {log}"
                )
            self.require_backup_support(bundle)
        except (ReleaseError, OSError, subprocess.SubprocessError, ValueError) as error:
            if not dry_run:
                self.record({**entry, "result": "failed", "error": str(error)[:500]})
            raise ReleaseError(str(error)) from error
        self.record({**entry, "result": "success"})
        return {}

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

    def native_controller(self, stage: Path) -> tuple[Any, Any]:
        """Load only the installed, reviewed engine's native operators."""
        sha = self.installed_engine()
        if sha is None:
            raise ReleaseError("native transition controller provenance is missing")
        archive, _ = self.source_archive(sha, stage, "infra/application")
        root = stage / "native-controller"
        self.extract_source(archive, root, "infra/application")
        modules = []
        for name in ("install-sales-xray-native", "native_artifact_compatibility"):
            spec = importlib.util.spec_from_file_location(
                "ac_release_" + name.replace("-", "_"),
                root / "infra/application/scripts" / (name + ".py"),
            )
            if spec is None or spec.loader is None:
                raise ReleaseError("native transition controller unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            modules.append(module)
        return modules[0], modules[1]

    def verify_native_target(self, sha: str, stage: Path, verifier: Any, installer: Any) -> Path:
        """Admit an ordinary exact-source CI bundle without loading its image."""
        stored = self.paths.native_store / sha
        try:
            record = verifier.parse(verifier.read(stored / "artifact-metadata.json"))
            run = verifier.parse(verifier.read(stored / "workflow-run.json"))
            expires = dt.datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
            if not (
                run["repository"]["full_name"] == REPOSITORY
                and run["path"] == f".github/workflows/{NATIVE_WORKFLOW}"
                and run["head_sha"] == sha
                and run["head_branch"] == "main"
                and run["event"] == "push"
                and run["run_attempt"] == 1
                and run["status"] == "completed"
                and run["conclusion"] == "success"
                and record["name"] == f"ac-sales-xray-native-{sha}"
                and record["workflow_run"]["id"] == run["id"]
                and record["workflow_run"]["head_sha"] == sha
                and record["workflow_run"]["repository_id"] == run["repository"]["id"]
                and record["workflow_run"]["head_repository_id"] == run["repository"]["id"]
                and record["expired"] is False
                and expires.tzinfo is not None
                and expires.timestamp() > self.clock()
                and type(record["id"]) is int
                and record["id"] > 0
            ):
                raise ReleaseError("native target CI provenance is invalid or expired")
            archive = stored / "native-artifact.zip"
            if (
                archive.is_symlink()
                or not archive.is_file()
                or not 0 < archive.stat().st_size == record["size_in_bytes"] <= MAX_ARTIFACT_BYTES
                or record["digest"] != "sha256:" + _sha256_file(archive)
            ):
                raise ReleaseError("native target archive identity mismatch")
            with zipfile.ZipFile(archive) as bundle:
                if sum(m.file_size for m in bundle.infolist()) > MAX_ARTIFACT_BYTES:
                    raise ReleaseError("native target expanded archive exceeds ceiling")
            target = stage / "native-target"
            target.mkdir()
            extract_exact(archive, target, NATIVE_FILES)
            manifest = verifier.parse(verifier.read(target / "native-image.json"))
            tree, inputs = verifier.source_inputs(self.paths.mirror, sha)
            blobs = {name: raw.split(b"\x00", 1)[1] for name, raw in inputs.items()}
            if (
                manifest["source_commit"] != sha
                or manifest["context"] != "."
                or manifest["context_tree_id"] != tree
                or manifest["dockerfile_sha256"] != verifier.RECIPE_SHA256
                or verifier.sha(blobs[verifier.DOCKERFILE]) != verifier.RECIPE_SHA256
                or manifest["native_source_sha256"]
                != verifier.sha(blobs["native/audioatlas/atlas_dsp.cpp"])
                or any(
                    verifier.sha(blobs[name]) != digest
                    for name, digest in verifier.HELPER_RECIPES.items()
                )
            ):
                raise ReleaseError("native target source binding mismatch")
            helper_sums = verifier._checksums(
                verifier.read(target / "native-helper-files.sha256"), set(verifier.HELPER_FILES)
            )
            with tarfile.open(target / "native-helper.tar.gz", "r:gz") as helper:
                members = helper.getmembers()
                if len(members) != len(verifier.HELPER_FILES) or {m.name for m in members} != set(
                    verifier.HELPER_FILES
                ):
                    raise ReleaseError("native helper inventory mismatch")
                for member in members:
                    if not member.isfile() or not 0 <= member.size <= 2_000_000:
                        raise ReleaseError("native helper entry invalid")
                    stream = helper.extractfile(member)
                    assert stream is not None
                    with stream:
                        raw = stream.read(2_000_001)
                    if raw != blobs[member.name] or verifier.sha(raw) != helper_sums[member.name]:
                        raise ReleaseError("native helper source mismatch")
                    path = target / "helper" / member.name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            binding = installer._artifact_binding(
                target / "native-image.json",
                _sha256_file(target / "native-image.json"),
                require_root=False,
                canonical_paths=False,
            )
            for section, name in (
                (manifest["transport"], "native-image.tar.gz"),
                (manifest["helper_source"], "native-helper.tar.gz"),
            ):
                if (
                    section["filename"] != name
                    or section["bytes"] != (target / name).stat().st_size
                    or section["sha256"] != _sha256_file(target / name)
                ):
                    raise ReleaseError("native transport binding mismatch")
            env = read_env_file(target / "native-image.env")
            for key, value in {
                "AC_NATIVE_IMAGE": binding.image_ref,
                "AC_NATIVE_IMAGE_ID": binding.image_config_id,
                "AC_NATIVE_SOURCE_COMMIT": sha,
                "AC_NATIVE_IMAGE_TYPE": "oci_transport_manifest",
                "AC_NATIVE_TRANSPORT_MANIFEST_DIGEST": binding.image_ref,
                "AC_NATIVE_TRANSPORT_CONFIG_DIGEST": binding.image_config_id,
                "AC_NATIVE_TRANSPORT_SHA256": manifest["transport"]["sha256"],
                "AC_NATIVE_HELPER_SHA256": manifest["helper_source"]["sha256"],
            }.items():
                if env.get(key) != value:
                    raise ReleaseError("native environment binding mismatch")
            self.verify_native_transport(target / "native-image.tar.gz", binding)
            return target
        except ReleaseError:
            raise
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            tarfile.TarError,
            zipfile.BadZipFile,
            installer.InstallerError,
        ) as error:
            raise ReleaseError("native target admission failed") from error

    @staticmethod
    def verify_native_transport(archive: Path, binding: Any) -> None:
        """Check the offline OCI manifest/config pair before any docker load."""
        with tarfile.open(archive, "r:gz") as image:
            members = image.getmembers()
            if len(members) > 512 or len({m.name for m in members}) != len(members):
                raise ReleaseError("native OCI inventory invalid")
            if any(
                m.name.startswith("/")
                or ".." in Path(m.name).parts
                or not (m.isfile() or m.isdir())
                for m in members
            ):
                raise ReleaseError("native OCI member invalid")
            if sum(m.size for m in members) > 2_000_000_000:
                raise ReleaseError("native OCI expanded size invalid")

            def blob(identity: str, limit: int) -> dict[str, Any]:
                member = image.getmember("blobs/sha256/" + identity.removeprefix("sha256:"))
                if not member.isfile() or not 0 < member.size <= limit:
                    raise ReleaseError("native OCI metadata size invalid")
                stream = image.extractfile(member)
                assert stream is not None
                with stream:
                    raw = stream.read(limit + 1)
                if "sha256:" + hashlib.sha256(raw).hexdigest() != identity:
                    raise ReleaseError("native OCI digest mismatch")
                return json.loads(raw)

            manifest = blob(binding.image_ref, 1_000_000)
            if manifest["config"]["digest"] != binding.image_config_id:
                raise ReleaseError("native OCI config mismatch")
            config = blob(binding.image_config_id, 8_000_000)
            runtime = config["config"]
            if (
                config["os"] != "linux"
                or config["architecture"] != "amd64"
                or runtime["User"] != "10001:10001"
                or runtime["WorkingDir"] != "/app"
                or runtime["Entrypoint"]
                != ["python", "-m", "ac_platform.conversation_intelligence"]
                or runtime["Cmd"] != ["doctor"]
            ):
                raise ReleaseError("native OCI runtime config mismatch")

    def native_preparation_path(self, sha: str) -> Path:
        return self.paths.state / "native-preparations" / f"staging-{sha}.json"

    def prepare_native(
        self, sha: str, previous_units: Path, previous_digest: str, *, dry_run: bool
    ) -> dict[str, Any]:
        """Prepare an exact staging transition; this operation never starts a helper."""
        with self.locked(wait=True):
            head = self.main_head()
            if not SHA_RE.fullmatch(sha) or not self.is_ancestor(sha, head):
                raise ReleaseError("native transition target must be on main")
            build = self.stored_build(sha, "core")
            if build is None:
                raise ReleaseError("native transition needs the admitted core build")
            with self.stage(sha) as stage:
                archive, _ = self.source_archive(sha, stage, "infra/application")
                source = stage / "source"
                self.extract_source(archive, source, "infra/application")
                plan = self.prepare_native_transition(
                    sha, previous_units, previous_digest, source, stage
                )
                receipt = {
                    "schema": "ac.release.native-preparation/1",
                    "target": sha,
                    "previous_core": plan["previous_core"],
                    "previous_native_units": str(previous_units),
                    "previous_native_units_sha256": previous_digest,
                    "approval_sha256": plan["approval_sha256"],
                    "source_activation_sha256": plan["source_activation_sha256"],
                    "controller": self.installed_engine(),
                    "artifact_pins": {
                        name: _sha256_file(self.paths.native_store / sha / name)
                        for name in NATIVE_STORE_FILES
                    },
                    "provider_calls": 0,
                    "runtime_mutation": False,
                    "dry_run": dry_run,
                }
                if not dry_run:
                    path = self.native_preparation_path(sha)
                    path.parent.mkdir(mode=0o700, exist_ok=True)
                    temporary = path.with_suffix(".next")
                    temporary.write_text(
                        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
                    )
                    temporary.chmod(0o400)
                    os.replace(temporary, path)
                    self.record({"at": _now(), "action": "native-prepare", **receipt})
                return receipt

    def native_deployment_plan(self, sha: str, source: Path, stage: Path) -> dict[str, Any]:
        path = self.native_preparation_path(sha)
        if path.is_symlink():
            raise ReleaseError("native preparation must be a regular engine-owned receipt")
        prepared = json.loads(path.read_text(encoding="utf-8"))
        if (
            prepared.get("schema") != "ac.release.native-preparation/1"
            or prepared.get("target") != sha
            or prepared.get("previous_core") != self.current_core("staging")
            or prepared.get("controller") != self.installed_engine()
            or prepared.get("dry_run") is not False
            or prepared.get("runtime_mutation") is not False
            or prepared.get("provider_calls") != 0
            or prepared.get("artifact_pins")
            != {
                name: _sha256_file(self.paths.native_store / sha / name)
                for name in NATIVE_STORE_FILES
            }
        ):
            raise ReleaseError("native preparation identities changed; prepare again")
        plan = self.prepare_native_transition(
            sha,
            Path(prepared["previous_native_units"]),
            prepared["previous_native_units_sha256"],
            source,
            stage,
        )
        if any(
            prepared.get(key) != plan[key]
            for key in ("approval_sha256", "source_activation_sha256")
        ):
            raise ReleaseError("native preparation authority changed; prepare again")
        return plan

    def install_native_transition(
        self, sha: str, plan: dict[str, Any], source: Path, log: Path
    ) -> None:
        """Switch the admitted helper under engine control, retaining both directions."""
        installer = plan["installer"]
        target = self.paths.application / "artifacts" / f"sales-xray-native-{sha}"
        if target.exists():
            for name in NATIVE_FILES:
                if (target / name).is_symlink() or _sha256_file(target / name) != _sha256_file(
                    plan["target"] / name
                ):
                    raise ReleaseError("loaded native target differs from admitted CI artifact")
            installer._artifact_binding(
                target / "native-image.json",
                _sha256_file(target / "native-image.json"),
                require_root=True,
                canonical_paths=True,
            )
        else:
            os.replace(plan["target"], target)
            self.seal_native_tree(target)
        home = (
            self.paths.application
            / "operator-inputs/staging"
            / (f"native-{sha}-" + secrets.token_hex(8))
        )
        home.mkdir(mode=0o750)
        inputs = home / "inputs"
        inputs.mkdir()
        previous = inputs / "previous-native-units.json"
        shutil.copyfile(plan["previous_units"], previous)
        units = inputs / "native-units.json"
        units.write_text(json.dumps(plan["units"], sort_keys=True) + "\n", encoding="utf-8")
        self.seal_native_tree(home)
        plan.update({"home": home, "installed_units": units, "saved_previous_units": previous})
        if (
            self.current_core("staging") != plan["previous_core"]
            or _sha256_file(plan["source_activation"]) != plan["source_activation_sha256"]
        ):
            raise ReleaseError("native transition predecessor changed before install")
        # Record durable rollback pins before a Docker load or supervisor change.
        self.record(
            {
                "at": _now(),
                "action": "native-transition",
                "target": sha,
                "previous_core": plan["previous_core"],
                "result": "armed",
                "previous_native": plan["previous_native"],
                "previous_native_units": str(previous),
                "previous_native_units_sha256": plan["previous_digest"],
                "source_activation_sha256": plan["source_activation_sha256"],
                "approval_sha256": plan["approval_sha256"],
                "provider_calls": 0,
            }
        )
        plan["armed"] = True
        self.run(
            ["docker", "load", "--input", str(target / "native-image.tar.gz")], log=log, timeout=900
        )
        result = installer.install(
            environment="staging",
            native_units=units,
            native_units_sha256=_sha256_file(units),
            renderer=plan["renderer"],
            renderer_python=Path("/usr/bin/python3"),
            native_image_config_id=plan["binding"].image_config_id,
            receipt=self.paths.application
            / "deployments/staging"
            / f"native-{sha}-{home.name[-16:]}.json",
            start=True,
            native_artifact_manifest=target / "native-image.json",
            native_artifact_sha256=_sha256_file(target / "native-image.json"),
            previous_native_units=previous,
            previous_native_units_sha256=plan["previous_digest"],
            supervisor_source=plan["supervisor"],
            previous_supervisor_source=json.loads(previous.read_text(encoding="utf-8"))[
                "supervisor_source"
            ],
        )
        if (
            result.get("status") != "installed"
            or result.get("provider_calls") != 0
            or result.get("database_writes") != 0
        ):
            raise ReleaseError("native installer did not prove the requested transition")
        # Re-prepare into the permanent directory: activation references must not
        # retain paths inside the engine's disposable source stage.
        output = home / "activation-bundle"
        self.run(
            [
                "python3",
                str(source / "infra/application/scripts/prepare-sales-xray-native-activation.py"),
                "--source-activation",
                str(plan["source_activation"]),
                "--target-release-id",
                sha,
                "--native-artifact-manifest",
                str(target / "native-image.json"),
                "--native-artifact-sha256",
                _sha256_file(target / "native-image.json"),
                "--output-dir",
                str(output),
            ],
            log=log,
            timeout=900,
        )
        prepared = json.loads((output / f"activation-{sha}.json").read_text(encoding="utf-8"))
        if (
            prepared["approval_sha256"] != plan["approval_sha256"]
            or _sha256_file(Path(prepared["approval_file"])) != plan["approval_sha256"]
            or prepared["native_image_ref"] != plan["binding"].image_ref
            or prepared["native_image_config_id"] != plan["binding"].image_config_id
        ):
            raise ReleaseError("native activation changed after preflight")
        self._seal_activation(home, output)
        self._publish_activation("staging", sha, output)

    def seal_native_tree(self, root: Path) -> None:
        import grp

        group = grp.getgrnam(self.operator_group).gr_gid
        for path in [root, *root.rglob("*")]:
            if path.is_symlink():
                raise ReleaseError("native admission contains a symlink")
            if os.geteuid() == 0:
                os.chown(path, 0, group)
            path.chmod(0o750 if path.is_dir() else 0o440)

    def restore_native_transition(self, sha: str, plan: dict[str, Any], log: Path) -> None:
        """Restore the pinned helper first, then the healthy application source."""
        installer = plan["installer"]
        previous = plan["saved_previous_units"]
        old = json.loads(previous.read_text(encoding="utf-8"))
        renderer = Path(old["supervisor_source"])
        result = installer.install(
            environment="staging",
            native_units=previous,
            native_units_sha256=plan["previous_digest"],
            renderer=renderer,
            renderer_python=Path("/usr/bin/python3"),
            native_image_config_id=plan["previous_binding"].image_config_id,
            receipt=self.paths.application
            / "deployments/staging"
            / f"native-restore-{sha}-{secrets.token_hex(8)}.json",
            start=True,
            native_artifact_manifest=plan["previous_manifest"],
            native_artifact_sha256=_sha256_file(plan["previous_manifest"]),
            previous_native_units=plan["installed_units"],
            previous_native_units_sha256=_sha256_file(plan["installed_units"]),
            previous_supervisor_source=plan["supervisor"],
            supervisor_source=old["supervisor_source"],
        )
        if (
            result.get("status") != "installed"
            or result.get("native_image_ref") != plan["previous_binding"].image_ref
        ):
            raise ReleaseError("native rollback readback failed")
        if _sha256_file(plan["source_activation"]) != plan["source_activation_sha256"]:
            raise ReleaseError("native rollback activation pin changed")
        # The canonical application-only installer also repairs a partial install
        # which left the current link on the predecessor but changed its services.
        self.deploy_core("staging", plan["rollback_build"], rollback_only=True)
        self.check_core("staging", plan["previous_core"], log)
        self.record(
            {
                "at": _now(),
                "environment": "staging",
                "component": "core",
                "action": "rollback",
                "sha": plan["previous_core"],
                "previous": sha,
                "result": "success",
                "trigger": "native-transition",
            }
        )
        for path in (
            self.activation_path("staging", sha),
            self.activation_path("staging", sha).with_suffix(".json.sha256"),
        ):
            if path.exists():
                path.unlink()
        self.record(
            {
                "at": _now(),
                "action": "native-transition",
                "target": sha,
                "previous_core": plan["previous_core"],
                "result": "restored",
                "previous_native": plan["previous_native"],
                "provider_calls": 0,
            }
        )

    def prepare_native_transition(
        self, sha: str, previous_units: Path, previous_digest: str, source: Path, stage: Path
    ) -> dict[str, Any]:
        """Prove both directions and prepare policy before the first runtime mutation."""
        installer, verifier = self.native_controller(stage)
        current = self.current_core("staging")
        if current is None or not self.is_ancestor(current, sha):
            raise ReleaseError("native transition predecessor is not an ancestor")
        activation = self.activation_path("staging", current)
        descriptor = verifier.parse(verifier.read(activation))
        if self.approval_expiry(descriptor) - self.clock() < APPROVAL_MIN_REMAINING_SECONDS:
            raise ReleaseError("native transition approval expires within one day")
        approval = Path(descriptor["approval_file"])
        approval_hash = _sha256_file(approval)
        if descriptor["approval_sha256"] != approval_hash:
            raise ReleaseError("native transition approval digest mismatch")
        old_sha, old_manifest = self.native_for_image(descriptor["native_image_ref"])
        old_binding = installer._artifact_binding(
            old_manifest, _sha256_file(old_manifest), require_root=True, canonical_paths=True
        )
        if descriptor["native_image_config_id"] != old_binding.image_config_id:
            raise ReleaseError("native transition predecessor config mismatch")
        if previous_units.is_symlink() or not previous_units.is_relative_to(
            self.paths.application / "operator-inputs/staging"
        ):
            raise ReleaseError("native transition predecessor pin path invalid")
        installer._ensure_existing_parents(
            previous_units, "native_previous_parent_invalid", require_root=True
        )
        installer._ensure_owner(previous_units, group="acops", code="native_previous_owner_invalid")
        previous, raw = installer._safe_json(previous_units)
        old_supervisor = previous["supervisor_source"]
        installer._validate_descriptor(
            previous,
            raw,
            environment="staging",
            supplied_sha256=previous_digest,
            binding=old_binding,
            supervisor_source=old_supervisor,
        )
        renderer = (
            self.paths.application / "releases" / current / "scripts/render-sales-xray-native.py"
        )
        supervisor = str(renderer)
        installer._validate_renderer_binding(
            previous,
            renderer=renderer,
            renderer_python=Path("/usr/bin/python3"),
            environment="staging",
            canonical_paths=True,
            binding=old_binding,
            enforce_path_binding=False,
            supervisor_source=old_supervisor,
        )
        old_renderer = Path(old_supervisor)
        old_renderer_hash = _sha256_file(old_renderer)
        if "staging" not in installer.REVIEWED_RENDERERS.get(old_renderer_hash, ()):
            raise ReleaseError("native rollback renderer is not reviewed")
        installer._verify_reference_renderer(old_renderer, old_renderer_hash, trusted_owner=True)
        names = tuple(previous["units"])
        systemd = installer.SubprocessSystemd()
        unit_root = installer.SYSTEMD_UNIT_ROOT
        installer._reject_existing_drift(
            unit_root=unit_root, units=previous["units"], require_root=True
        )
        if any(
            installer._safe_existing_unit(installer._unit_path(unit_root, name), require_root=True)
            != text.encode("utf-8")
            for name, text in previous["units"].items()
        ):
            raise ReleaseError("native transition predecessor units are missing or changed")
        states = installer._capture_states(systemd, names)
        if not all(state["active"] and state["enabled"] for state in states.values()):
            raise ReleaseError("native transition predecessor units are not healthy and enabled")
        installer._readback(systemd, names, unit_root, "staging")
        if installer.SubprocessGroup().ensure(dry_run=True)["status"] != "present":
            raise ReleaseError("native transition rollback group is missing")
        if installer.SubprocessDocker(old_binding).inspect_identity() not in old_binding.identities:
            raise ReleaseError("native transition rollback image is missing")
        rollback = self.stored_build(current, "core")
        if rollback is None:
            raise ReleaseError("native transition rollback core build is missing")
        old_bundle = self.store_bundle(rollback, "core", CORE_FILES)
        self.require_backup_support(old_bundle)
        build = self.stored_build(sha, "core")
        if build is None or self.bundle_migration_head(
            self.store_bundle(build, "core", CORE_FILES)
        ) != self.bundle_migration_head(old_bundle):
            raise ReleaseError("native transition cannot prove application-only core rollback")
        self.check_core("staging", current, self.new_log("staging", "native-preflight", sha))
        controller = (
            stage / "native-controller/infra/application/scripts/install-application-release.sh"
        )
        if "AC_CORE_ROLLBACK_ONLY" not in controller.read_text(encoding="utf-8"):
            raise ReleaseError(
                "native transition controller cannot restore the core without database writes"
            )
        target = self.verify_native_target(sha, stage, verifier, installer)
        if self.activation_path("staging", sha).exists():
            raise ReleaseError(
                "native transition target activation already exists; do not overwrite"
            )
        manifest = target / "native-image.json"
        binding = installer._artifact_binding(
            manifest, _sha256_file(manifest), require_root=False, canonical_paths=False
        )
        rendered, _ = installer._rendered_descriptor(
            renderer=renderer,
            renderer_python=Path("/usr/bin/python3"),
            environment="staging",
            canonical_paths=True,
            binding=binding,
            supervisor_source=supervisor,
        )
        installer._validate_descriptor(
            rendered,
            json.dumps(rendered).encode(),
            environment="staging",
            supplied_sha256=hashlib.sha256(json.dumps(rendered).encode()).hexdigest(),
            binding=binding,
            supervisor_source=supervisor,
        )
        staged, units = installer._stage_units(
            unit_root=unit_root, units=rendered["units"], require_root=True
        )
        try:
            systemd.verify(tuple(units.values()))
        finally:
            installer._remove_tree(staged)
        output = stage / "native-activation"
        completed = self.run(
            [
                "python3",
                str(source / "infra/application/scripts/prepare-sales-xray-native-activation.py"),
                "--source-activation",
                str(activation),
                "--target-release-id",
                sha,
                "--native-artifact-manifest",
                str(manifest),
                "--native-artifact-sha256",
                _sha256_file(manifest),
                "--output-dir",
                str(output),
            ],
            check=False,
            timeout=900,
        )
        if completed.returncode != 0:
            raise ReleaseError("native transition activation preparation failed")
        result = json.loads(completed.stdout)
        prepared = json.loads((output / f"activation-{sha}.json").read_text(encoding="utf-8"))
        if (
            result.get("provider_calls") != 0
            or result.get("approval_replaced") is not False
            or result.get("release_id") != sha
            or prepared["approval_file"] != str(approval)
            or prepared["approval_sha256"] != approval_hash
            or prepared["native_image_ref"] != binding.image_ref
            or prepared["native_image_config_id"] != binding.image_config_id
            or _sha256_file(approval) != approval_hash
        ):
            raise ReleaseError("native transition changed authority or identity")
        return {
            "installer": installer,
            "target": target,
            "binding": binding,
            "previous_binding": old_binding,
            "previous_manifest": old_manifest,
            "previous_units": previous_units,
            "previous_digest": previous_digest,
            "units": rendered,
            "renderer": renderer,
            "supervisor": supervisor,
            "activation": output,
            "source_activation": activation,
            "source_activation_sha256": _sha256_file(activation),
            "approval_sha256": approval_hash,
            "previous_core": current,
            "rollback_build": rollback,
            "previous_native": old_sha,
        }

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

    def web_rollback_entry(self, environment: str) -> dict[str, Any] | None:
        """The recorded web deploy whose previous image a web rollback restores."""

        _, image = self.current_web(environment)
        return next(
            (
                entry
                for entry in reversed(self.history(10_000))
                if entry.get("environment") == environment
                and entry.get("component") == "web"
                and entry.get("result") == "success"
                and entry.get("previous_image")
                and entry.get("runtime_ref") == image
            ),
            None,
        )

    def rollback_web(self, environment: str) -> dict[str, Any]:
        entry = self.web_rollback_entry(environment)
        if entry is None:
            raise ReleaseError("no recorded web deploy with a previous image to restore")
        inputs = self.paths.application / "operator-inputs" / f"sales-xray-web-{entry['sha']}"
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

    # -- orchestration -------------------------------------------------------

    @contextlib.contextmanager
    def locked(self, *, wait: bool) -> Iterator[bool]:
        if self._lock_depth:
            yield True
            return
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
                self._lock_depth += 1
                yield True
            finally:
                self._lock_depth -= 1
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
            update = self.update_engine(head)
            if update is not None:
                # The next tick runs the new engine; this one stops here.
                return [update]
            results = self.advance(environment, head)
            try:
                # main_head() just fetched the mirror. Admin's snapshot never fails the tick.
                self.publish_status(refresh=False)
            except Exception as error:
                results.append({"status_publish_error": _safe_text(error) or type(error).__name__})
            return results

    def advance(self, environment: str, head: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        if self.current_core(environment) != head and self.failed_sha(environment, "core") != head:
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
            data.get("recovery"),
        )

    # -- Admin snapshot (ADR 0034) -------------------------------------------

    def snapshot(self, *, refresh: bool = True) -> dict[str, Any]:
        """Contract v1 status for Admin: local state and the mirror, no GitHub calls."""

        history = self.history(10_000)
        current, _ = self.production_releases()
        environments: dict[str, Any] = {}
        for environment in ENVIRONMENTS:
            expires = self.approval_expires(environment)
            deployed = {
                component: next(
                    (
                        entry.get("at")
                        for entry in reversed(history)
                        if entry.get("environment") == environment
                        and entry.get("component") == component
                        and entry.get("result") == "success"
                    ),
                    None,
                )
                for component in COMPONENTS
            }
            environments[environment] = {
                "version": current["version"] if environment == "production" and current else None,
                "core_sha": self.current_core(environment),
                "web_sha": self.current_web(environment)[0],
                "core_deployed_at": deployed["core"],
                "web_deployed_at": deployed["web"],
                "paused": self.is_paused(environment),
                "failed_core": self.failed_sha(environment, "core"),
                "failed_web": self.failed_sha(environment, "web"),
                "approval_days_left": int((expires - self.clock()) // 86400) if expires else None,
            }
        staging_history = [
            {
                "at": entry.get("at"),
                "component": entry["component"],
                "sha": entry.get("sha"),
                "result": entry.get("result"),
                "trigger": entry.get("trigger") or entry.get("action") or "deploy",
                "error": _safe_text(entry.get("error")),
            }
            for entry in reversed(history)
            if entry.get("environment") == "staging"
            and entry.get("component") in COMPONENTS
            and entry.get("result")
        ][:STATUS_LIST_LIMIT]
        try:
            rollback = {"available": True, "reason": None, **self._target_fields()}
        except (ReleaseError, OSError, ValueError, KeyError) as error:
            reason = str(error) if isinstance(error, ReleaseError) else None
            rollback = {
                "available": False,
                "reason": _safe_text(reason or "Rollback not available: release state unreadable."),
                "target_version": None,
                "core_sha": None,
                "web_sha": None,
            }
        return {
            "v": 1,
            "generated_at": _now(),
            "engine": {
                "commit": self.installed_engine(),
                "production_enabled": self.paths.production_enabled.exists(),
                "restore_check_ok": self.restore_check_ok(),
                "train_enabled": (self.paths.config / "train.enabled").exists(),
            },
            "environments": environments,
            "releases": [
                {
                    "version": record["version"],
                    "action": record["action"],
                    "core_sha": record["core_sha"],
                    "web_sha": record["web_sha"],
                    "at": record["at"],
                    "requested_by": _safe_text(record["requested_by"]),
                    "rolled_back_from": record["rolled_back_from"],
                }
                for record in reversed(self.release_events())
            ][:STATUS_LIST_LIMIT],
            "staging_history": staging_history,
            "promote": self._promote_status(environments["production"], refresh=refresh),
            "rollback": rollback,
            "busy": self._busy(),
        }

    def _target_fields(self) -> dict[str, Any]:
        target = self.rollback_target()
        return {
            "target_version": target["version"],
            "core_sha": target["core_sha"],
            "web_sha": target["web_sha"],
        }

    def _promote_status(self, production: Mapping[str, Any], *, refresh: bool) -> dict[str, Any]:
        status: dict[str, Any] = {
            "available": False,
            "reason": None,
            "core_sha": None,
            "web_sha": None,
            "commits_behind": None,
            "next": dict.fromkeys(BUMPS),
            "notes": [],
        }
        reasons: list[str] = []
        if not self.paths.production_enabled.exists():
            reasons.append("production deploys are not enabled on this server yet")
        try:
            status["next"] = self.next_versions(refresh=refresh)  # The only mirror fetch.
        except (ReleaseError, OSError, ValueError, subprocess.SubprocessError):
            reasons.append("the next release versions could not be read")
        try:
            core_sha, web_sha = self.staging_pair(refresh=False)
        except (ReleaseError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            reasons.append(str(error) if isinstance(error, ReleaseError) else "staging unreadable")
        else:
            status.update(core_sha=core_sha, web_sha=web_sha)
            production_core = production["core_sha"]
            if production_core and not self.is_ancestor(production_core, core_sha):
                reasons.append("production core is not an ancestor of the staging core")
            if (production_core, production["web_sha"]) == (core_sha, web_sha):
                reasons.append("production already runs this staging pair")
            if production_core:
                with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
                    notes = _release_notes(self.paths.mirror, production_core, core_sha)
                    status["commits_behind"] = len(notes)
                    status["notes"] = [_safe_text(note) for note in notes[:STATUS_NOTES_LIMIT]]
        status["available"] = not reasons
        status["reason"] = _safe_text(reasons[0]) if reasons else None
        return status

    def _busy(self) -> dict[str, Any] | None:
        """E2 writes ``admin/busy.json`` while a request runs; E1 only reads it."""

        with contextlib.suppress(OSError, ValueError):
            busy = json.loads((self.paths.admin / "busy.json").read_text(encoding="utf-8"))
            if isinstance(busy, dict) and set(busy) == {"request_id", "action", "since"}:
                return {key: _safe_text(value) for key, value in busy.items()}
        return None

    def publish_status(self, *, refresh: bool = True) -> Path:
        """Atomically write ``admin/outbox/status.json`` (0644, at most 256 KB)."""

        with self.locked(wait=True):
            return self._write_status(refresh=refresh)

    def _write_status(self, *, refresh: bool) -> Path:
        data = (json.dumps(self.snapshot(refresh=refresh), sort_keys=True) + "\n").encode()
        if len(data) > STATUS_MAX_BYTES:
            raise ReleaseError("the status snapshot is larger than 256 KB")
        outbox = self.paths.admin / "outbox"
        self.paths.state.mkdir(parents=True, exist_ok=True)
        for directory in (self.paths.admin, outbox):
            if not directory.is_dir():
                directory.mkdir(mode=0o755)
                directory.chmod(0o755)
        handle, name = tempfile.mkstemp(prefix=".status.", suffix=".tmp", dir=outbox)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o644)
                os.fsync(stream.fileno())
            os.replace(name, outbox / "status.json")
        except BaseException:
            Path(name).unlink(missing_ok=True)
            raise
        return outbox / "status.json"

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
        last_train = self.paths.state / "last-train.json"
        report["train"] = {"enabled": (self.paths.config / "train.enabled").exists()}
        report["restore_check_ok"] = self.restore_check_ok()
        report["last_train"] = json.loads(last_train.read_text()) if last_train.exists() else None
        # The next staging core target is the latest ready main build, falling
        # back to the current release when its build is not yet available.
        pick = {"core": self.current_core("staging"), "web": self.current_web("staging")[0]}
        if self.github is not None and not self.is_paused("staging"):
            try:
                head = self.github.get_json(f"/repos/{REPOSITORY}/commits/main").get("sha", "")
                if SHA_RE.fullmatch(head):
                    candidate = core_candidate(self.github, head)
                    if candidate.state == "ready" and self.failed_sha("staging", "core") != head:
                        pick["core"] = head
                    web = self.web_target("staging", head)
                    if web is not None and self.failed_sha("staging", "web") != web.sha:
                        pick["web"] = web.sha
            except (ReleaseError, OSError, ValueError, subprocess.SubprocessError):
                report["staging_pick_error"] = "discovery_unavailable"
        report["staging_pick"] = pick
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
    train = sub.add_parser("train")
    train.add_argument("--now", action="store_true")
    train.add_argument("--dry-run", action="store_true")
    deploy = sub.add_parser("deploy")
    deploy.add_argument("environment", choices=ENVIRONMENTS)
    deploy.add_argument("sha", nargs="?")
    deploy.add_argument("--component", choices=("core", "web", "all"), default="all")
    deploy.add_argument("--dry-run", action="store_true")
    promote = sub.add_parser("promote")
    promote.add_argument("--bump", choices=("patch", "minor", "major"), required=True)
    promote.add_argument("--version", required=True, metavar="vX.Y.Z")
    promote.add_argument("--dry-run", action="store_true")
    for name in ("pause", "resume"):
        sub.add_parser(name).add_argument("environment", choices=ENVIRONMENTS)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("environment", choices=ENVIRONMENTS)
    rollback.add_argument("--component", choices=COMPONENTS)
    rollback.add_argument("--dry-run", action="store_true", help="production pair only")
    sub.add_parser("publish-status")
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
    preparation = sub.add_parser("prepare-native")
    preparation.add_argument("environment", choices=("staging",))
    preparation.add_argument("sha")
    preparation.add_argument("--previous-native-units", type=Path, required=True)
    preparation.add_argument("--previous-native-units-sha256", required=True)
    preparation.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    paths = Paths()
    engine = Engine(paths=paths)
    try:
        if args.command == "status":
            engine.github = _load_github(paths, required=False)
            _print(engine.status(), args.json)
        elif args.command == "history":
            _print(engine.history(args.n), True)
        elif args.command in ("pause", "resume"):
            with engine.locked(wait=True):
                engine.set_paused(args.environment, args.command == "pause", "paused by operator")
            engine.record({"at": _now(), "environment": args.environment, "action": args.command})
            print(f"{args.environment}: {args.command}d")
        elif args.command == "rollback" and args.component is None:
            if args.environment != "production":
                raise ReleaseError("rollback staging needs --component core or web")
            user = os.environ.get("SUDO_USER") or getpass.getuser()
            steps = engine.rollback_production(
                requested_by=f"cli:{user}", trigger="cli", dry_run=args.dry_run
            )
            _print(steps, True)
            if any(step["result"] == "failed" for step in steps):
                return 1
        elif args.command == "rollback":
            if args.dry_run:
                raise ReleaseError("--dry-run applies to the production pair rollback only")
            with engine.locked(wait=True):
                operation = (
                    engine.rollback_core if args.component == "core" else engine.rollback_web
                )
                result = operation(args.environment)
            if args.component == "web":  # Core rollback owns its history entry.
                engine.record(
                    {
                        "at": _now(),
                        "environment": args.environment,
                        "component": args.component,
                        "action": "rollback",
                        **result,
                    }
                )
            _print(result, True)
        elif args.command == "train":
            result = engine.train(now=args.now, dry_run=args.dry_run)
            _print(result, True)
            if result["result"] in ("failed", "rolled_back", "refused"):
                return 1
        elif args.command == "promote":
            user = os.environ.get("SUDO_USER") or getpass.getuser()
            results = engine.promote(
                args.bump,
                args.version,
                requested_by=f"cli:{user}",
                trigger="cli",
                dry_run=args.dry_run,
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
        elif args.command == "publish-status":
            print(engine.publish_status())
        elif args.command == "store-native":
            engine.github = _load_github(paths, required=True)
            with engine.locked(wait=True):
                print(engine.store_native(args.sha, local_zip=args.local_zip))
        elif args.command == "prepare-native":
            _print(
                engine.prepare_native(
                    args.sha,
                    args.previous_native_units,
                    args.previous_native_units_sha256,
                    dry_run=args.dry_run,
                ),
                True,
            )
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
