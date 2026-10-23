#!/usr/bin/env python3
"""Publish signed Ubuntu prerequisites once; verify and install GitHub bundles offline.

Only the producer can reach package/browser servers. Consumers accept an exact
artifact digest and producer reference, then solve against a complete local apt
repository. A runner image is recorded, not assumed to have the producer's dpkg
state. No production image or installed host tool is changed by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

if __package__:
    from .ci_prerequisites import APT_OPTIONS, COMPONENTS, PrerequisiteError, Prerequisites
else:
    from ci_prerequisites import APT_OPTIONS, COMPONENTS, PrerequisiteError, Prerequisites

SCHEMA = "ac.ci.prerequisite-bundle/1"
POLICY = "ubuntu-24.04-amd64-complete-local-solve/1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DEB = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.+_:%~-]*\.deb$")
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
# Conservative admission, not a claim about GitHub's billing quota. The repository is public, so
# GitHub does not charge for or cap its artifact storage (22 Oct: 5.4 GB retained, uploads still
# accepted). The total ceiling only guards against runaway growth; the bundle ceiling below stops
# duplicate bundles. Reserve a full upload before acquisition.
MAX_PUBLICATION_BYTES = 512 * 1024 * 1024
MAX_RETAINED_BUNDLE_BYTES = 1024 * 1024 * 1024
MAX_RETAINED_ARTIFACT_BYTES = 4096 * 1024 * 1024
MAX_IDENTITY_PUBLICATIONS = 2  # bootstrap plus one baseline/age recovery
BOOTSTRAP_FILE = Path(__file__).with_name("ci-prerequisite-bootstrap.json")
PUBLICATION_OWNER = "ci-prerequisite-publication-v3"
IDENTITY_FILES = (
    "uv.lock",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "package.json",
    "pnpm-workspace.yaml",
    "scripts/ci/ci_prerequisites.py",
    "scripts/ci/ci_prerequisite_bundle.py",
    ".github/actions/ci-prerequisite-bundle/action.yml",
)
ORIGINS = (
    "https://archive.ubuntu.com/ubuntu",
    "https://security.ubuntu.com/ubuntu",
)


class BundleError(PrerequisiteError):
    """A bounded, credential-free bundle diagnostic."""


class IntegrityError(BundleError):
    """A published bundle or reference was altered or did not match its identity."""


class PublisherUnavailable(BundleError):
    """Missing/expired/transient publisher data can be rebuilt by the producer."""


class PublicationDeclined(BundleError):
    """Publication cannot proceed within the retained byte/duplicate bounds."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized_digest(value: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError("invalid artifact SHA-256")
    value = value.removeprefix("sha256:")
    if not SHA256.fullmatch(value):
        raise IntegrityError("invalid artifact SHA-256")
    return value


def identity(root: Path) -> str:
    records = {name: digest(root / name) for name in IDENTITY_FILES}
    if (root / ".npmrc").exists():
        records[".npmrc"] = digest(root / ".npmrc")
    return hashlib.sha256(
        json.dumps([SCHEMA, POLICY, records], sort_keys=True).encode()
    ).hexdigest()


def baseline() -> dict[str, str]:
    release = platform.freedesktop_os_release()
    return {
        "id": release.get("ID", ""),
        "version": release.get("VERSION_ID", ""),
        "architecture": {"x86_64": "amd64"}.get(platform.machine(), platform.machine()),
    }


def require_runner() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise BundleError("package operations are restricted to disposable GitHub Actions runners")
    if baseline() != {"id": "ubuntu", "version": "24.04", "architecture": "amd64"}:
        raise BundleError("incompatible prerequisite baseline: Ubuntu 24.04 amd64 required")


def reference(artifact_id: str, artifact_digest: str, key: str) -> dict:
    return {
        "artifact_id": int(artifact_id),
        "digest": normalized_digest(artifact_digest),
        "identity": key,
        "repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "source_sha": os.environ["GITHUB_SHA"],
    }


def validate_reference(value: dict, key: str, repository: str) -> None:
    if not isinstance(value, dict):
        raise IntegrityError("invalid prerequisite producer reference")
    if (
        value.get("identity") != key
        or value.get("repository") != repository
        or not COMMIT.fullmatch(str(value.get("source_sha", "")))
        or any(
            type(value.get(name)) is not int or value[name] <= 0
            for name in ("run_id", "artifact_id")
        )
    ):
        raise IntegrityError("foreign or invalid prerequisite producer reference")
    normalized_digest(value.get("digest", ""))


def github(path: str, *, output: Path | None = None) -> dict | None:
    # gh handles authenticated GitHub redirects; credentials never enter argv.
    command = ["gh", "api", "--allow-escape-sequences", path]
    try:
        if output is not None:
            with output.open("wb") as stream:
                result = subprocess.run(  # noqa: S603 - fixed gh executable, no shell
                    command, stdout=stream, stderr=subprocess.PIPE, timeout=180
                )
        else:
            result = subprocess.run(  # noqa: S603 - fixed gh executable, no shell
                command, capture_output=True, timeout=30
            )
    except subprocess.TimeoutExpired as error:
        raise PublisherUnavailable(
            "GitHub prerequisite request exceeded its bounded timeout"
        ) from error
    if result.returncode:
        diagnostic = result.stderr.decode(errors="replace")
        if any(f"HTTP {code}" in diagnostic for code in (404, 410, 502, 503, 504)):
            raise PublisherUnavailable("GitHub prerequisite publisher is unavailable")
        raise BundleError("GitHub prerequisite request failed; no consumer mirror fallback")
    if output is not None:
        return None
    try:
        return json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise IntegrityError("invalid GitHub prerequisite metadata") from error


def find_published(key: str, repository: str, now: datetime | None = None) -> dict | None:
    """Reuse only a successful trusted main workflow, never a sibling/PR producer."""
    now = now or datetime.now(UTC)
    runs = github(
        f"repos/{repository}/actions/workflows/application.yml/runs"
        "?branch=main&event=push&status=success&per_page=5"
    )
    for run in runs.get("workflow_runs", []):
        if (
            run.get("event") != "push"
            or run.get("head_branch") != "main"
            or run.get("conclusion") != "success"
            or run.get("path") != ".github/workflows/application.yml"
        ):
            continue
        artifacts = github(f"repos/{repository}/actions/runs/{run['id']}/artifacts?per_page=100")
        for artifact in reversed(artifacts.get("artifacts", [])):
            if not artifact.get("name", "").startswith(f"ci-prerequisites-v2-{key}-"):
                continue
            created = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
            expires = datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
            if artifact.get("expired") or expires < now + timedelta(hours=2):
                continue
            if not timedelta(0) <= now - created <= timedelta(hours=36):
                continue
            return {
                "artifact_id": artifact["id"],
                "digest": normalized_digest(artifact.get("digest", "")),
                "identity": key,
                "repository": repository,
                "run_id": run["id"],
                "source_sha": run["head_sha"],
            }
    return find_bootstrap(key, repository, now)


def fresh(artifact: dict, now: datetime) -> bool:
    created = datetime.fromisoformat(artifact["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(artifact["expires_at"].replace("Z", "+00:00"))
    return (
        not artifact.get("expired")
        and expires >= now + timedelta(hours=2)
        and timedelta(0) <= now - created <= timedelta(hours=36)
    )


def find_bootstrap(key: str, repository: str, now: datetime) -> dict | None:
    """Pins are reviewed source data, never inferred from sibling artifact names.

    The pin file is outside the identity inputs: recording a reviewed run/digest
    must not change the locked identity it pins. Producer code/locks stay bound.
    """
    pins = json.loads(BOOTSTRAP_FILE.read_text())
    if not isinstance(pins, list) or len(pins) > 10:
        raise IntegrityError("invalid reviewed bootstrap references")
    for pin in pins:
        if not isinstance(pin, dict):
            raise IntegrityError("invalid reviewed bootstrap reference")
        if pin.get("identity") != key or pin.get("repository") != repository:
            continue
        validate_reference(pin, key, repository)
        if not COMMIT.fullmatch(str(pin.get("reviewed_source_sha", ""))):
            raise IntegrityError("bootstrap reference lacks reviewed source")
        run = github(f"repos/{repository}/actions/runs/{pin['run_id']}")
        if (
            run.get("id") != pin["run_id"]
            or run.get("head_sha") != pin["source_sha"]
            or run.get("repository", {}).get("full_name") != repository
            or run.get("head_repository", {}).get("full_name") != repository
            or run.get("event") != "push"
            or run.get("path") != ".github/workflows/workbench-checks.yml"
            or run.get("conclusion") != "success"
        ):
            raise IntegrityError("bootstrap run does not match reviewed producer")
        # wb-ci creates exactly one request commit on the reviewed source. Check
        # that relationship instead of trusting a source label inside the request.
        commit = github(f"repos/{repository}/commits/{pin['source_sha']}?per_page=2")
        if (
            commit.get("sha") != pin["source_sha"]
            or [p.get("sha") for p in commit.get("parents", [])] != [pin["reviewed_source_sha"]]
            or [f.get("filename") for f in commit.get("files", [])] != [".wb-ci/request.json"]
        ):
            raise IntegrityError("bootstrap producer differs from the reviewed source")
        artifact = github(f"repos/{repository}/actions/artifacts/{pin['artifact_id']}")
        validate_artifact(artifact, pin)
        if fresh(artifact, now):
            return pin
    return None


def validate_artifact(artifact: dict, ref: dict) -> None:
    if (
        artifact.get("id") != ref["artifact_id"]
        or artifact.get("workflow_run", {}).get("id") != ref["run_id"]
        or artifact.get("workflow_run", {}).get("head_sha") != ref["source_sha"]
        or normalized_digest(artifact.get("digest", "")) != ref["digest"]
    ):
        raise IntegrityError("GitHub artifact does not match the pinned producer")


def admit_publication(key: str, repository: str, recovery: dict | None = None) -> dict:
    """Read fresh inventory under the shared job lock; never delete to make room.

    Pagination is bounded and complete before allowing publication. Stop early
    when the cap is already exceeded. All live artifacts count, not just bundles.
    """
    if os.environ.get("PREREQ_PUBLICATION_OWNER") != PUBLICATION_OWNER:
        raise PublicationDeclined("publication ownership missing; use the serialized producer job")
    retained = bundle_bytes = 0
    same = []
    now = datetime.now(UTC)
    for page in range(1, 101):
        data = github(f"repos/{repository}/actions/artifacts?per_page=100&page={page}")
        artifacts = data["artifacts"]
        for artifact in artifacts:
            if artifact.get("expired"):
                continue
            size = artifact.get("size_in_bytes")
            if type(size) is not int or size < 0:
                raise IntegrityError("invalid artifact inventory size")
            retained += size
            name = artifact.get("name", "")
            if name.startswith("ci-prerequisites-v2-"):
                bundle_bytes += size
            if name.startswith(f"ci-prerequisites-v2-{key}-"):
                same.append(artifact)
        if (
            retained + MAX_PUBLICATION_BYTES > MAX_RETAINED_ARTIFACT_BYTES
            or bundle_bytes + MAX_PUBLICATION_BYTES > MAX_RETAINED_BUNDLE_BYTES
        ):
            raise PublicationDeclined(
                f"storage admission declined: retained_artifact_bytes={retained}, "
                f"retained_bundle_bytes={bundle_bytes}, reserve_bytes={MAX_PUBLICATION_BYTES}; "
                "wait for expiry or use the approved storage path; no upload or deletion"
            )
        if page * 100 >= data["total_count"]:
            break
    else:
        raise PublicationDeclined("artifact inventory exceeds 100 pages; publication declined")
    if len(same) >= MAX_IDENTITY_PUBLICATIONS:
        raise PublicationDeclined("identity publication bound reached; wait for expiry")
    for artifact in same:
        if fresh(artifact, now) and (recovery is None or artifact["id"] != recovery["artifact_id"]):
            raise PublicationDeclined(
                f"duplicate publication declined: artifact {artifact['id']} already exists; "
                "pin its reviewed producer/run/identity/digest for bootstrap reuse"
            )
    result = {
        "retained_artifact_bytes": retained,
        "retained_bundle_bytes": bundle_bytes,
        "reserved_upload_bytes": MAX_PUBLICATION_BYTES,
        "artifact_byte_ceiling": MAX_RETAINED_ARTIFACT_BYTES,
        "bundle_byte_ceiling": MAX_RETAINED_BUNDLE_BYTES,
        "retained_identity_publications": len(same),
    }
    print("Publication admission: " + json.dumps(result, sort_keys=True), flush=True)
    return result


def validate_manifest(manifest: dict, ref: dict, host: dict[str, str]) -> None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("producer"), dict):
        raise IntegrityError("invalid prerequisite manifest")
    if (
        manifest.get("schema") != SCHEMA
        or manifest.get("policy") != POLICY
        or manifest.get("baseline") != host
        or host != {"id": "ubuntu", "version": "24.04", "architecture": "amd64"}
        or manifest.get("identity") != ref["identity"]
        or manifest.get("repository") != ref["repository"]
        or manifest.get("producer", {}).get("run_id") != ref["run_id"]
        or manifest.get("producer", {}).get("source_sha") != ref["source_sha"]
        or not manifest.get("producer", {}).get("image")
        or manifest.get("origins") != list(ORIGINS)
        or manifest.get("closure") != "empty-status-offline-solve"
    ):
        raise IntegrityError("incompatible, incomplete or foreign prerequisite manifest")
    normalized_digest(manifest.get("archive_sha256", ""))
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or not 1 <= len(packages) <= 1000:
        raise IntegrityError("missing complete Debian package closure")
    for name, checksum in packages.items():
        if not DEB.fullmatch(name):
            raise IntegrityError("unsafe Debian archive name")
        normalized_digest(checksum)
    requested = manifest.get("requested_packages")
    if not isinstance(requested, list) or not 1 <= len(requested) <= 200:
        raise IntegrityError("invalid required package list")
    if any(
        not isinstance(p, str) or not re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", p) for p in requested
    ):
        raise IntegrityError("invalid required package list")


def unpack_artifact(zip_path: Path, ref: dict, destination: Path, host: dict[str, str]) -> dict:
    if zip_path.stat().st_size > MAX_ARCHIVE_BYTES or digest(zip_path) != ref["digest"]:
        raise IntegrityError("GitHub prerequisite artifact digest mismatch or size limit")
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(zip_path) as archive:
        if sorted(archive.namelist()) != ["bundle.json", "bundle.tar.gz"]:
            raise IntegrityError("unexpected prerequisite artifact contents")
        if archive.getinfo("bundle.json").file_size > 1024 * 1024:
            raise IntegrityError("oversized prerequisite manifest")
        if archive.getinfo("bundle.tar.gz").file_size > MAX_ARCHIVE_BYTES:
            raise IntegrityError("oversized prerequisite payload")
        manifest = json.loads(archive.read("bundle.json"))
        validate_manifest(manifest, ref, host)
        payload = destination / "bundle.tar.gz"
        with archive.open("bundle.tar.gz") as source, payload.open("wb") as target:
            shutil.copyfileobj(source, target)
    if digest(payload) != manifest["archive_sha256"]:
        raise IntegrityError("prerequisite payload digest mismatch")
    with tarfile.open(payload) as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > 2 * MAX_ARCHIVE_BYTES:
            raise IntegrityError("oversized unpacked prerequisite bundle")
        if any(
            m.name.split("/", 1)[0] not in {"debs", "browsers"} or ".." in Path(m.name).parts
            for m in members
        ):
            raise IntegrityError("unexpected prerequisite payload path")
        archive.extractall(destination, filter="data")
    archives = list((destination / "debs").glob("*.deb"))
    if any(p.is_symlink() or not p.is_file() for p in archives):
        raise IntegrityError("Debian archives must be regular files")
    actual = {p.name: digest(p) for p in archives}
    if actual != manifest["packages"]:
        raise IntegrityError("Debian closure archives missing, altered or unexpected")
    (destination / "bundle.json").write_text(json.dumps(manifest))
    return manifest


def download(ref: dict, key: str, directory: Path) -> tuple[Path, dict]:
    repository = os.environ["GITHUB_REPOSITORY"]
    validate_reference(ref, key, repository)
    artifact = github(f"repos/{repository}/actions/artifacts/{ref['artifact_id']}")
    validate_artifact(artifact, ref)
    if artifact.get("expired"):
        raise PublisherUnavailable("pinned prerequisite artifact expired")
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "artifact.zip"
    github(f"repos/{repository}/actions/artifacts/{ref['artifact_id']}/zip", output=path)
    target = directory / "contents"
    return target, unpack_artifact(path, ref, target, baseline())


def official_options(directory: Path) -> list[str]:
    """An isolated, signed Ubuntu source list; runner Azure/mirror lists are unused."""
    sources = directory / "official.list"
    sources.write_text(
        "\n".join(
            "deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] "
            f"{origin} {suite} main universe restricted multiverse"
            for origin, suite in (
                (ORIGINS[0], "noble"),
                (ORIGINS[0], "noble-updates"),
                (ORIGINS[1], "noble-security"),
            )
        )
        + "\n"
    )
    (directory / "official-lists/partial").mkdir(parents=True)
    return [
        "-o",
        f"Dir::Etc::sourcelist={sources}",
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        f"Dir::State::lists={directory}/official-lists",
        "-o",
        "Acquire::AllowInsecureRepositories=false",
        "-o",
        "APT::Get::AllowUnauthenticated=false",
    ]


def local_options(directory: Path) -> list[str]:
    sources = directory / "offline.list"
    sources.write_text(f"deb [trusted=yes] file:{directory}/debs ./\n")
    (directory / "local-lists/partial").mkdir(parents=True, exist_ok=True)
    return [
        "-o",
        f"Dir::Etc::sourcelist={sources}",
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        f"Dir::State::lists={directory}/local-lists",
        "-o",
        f"Dir::Cache={directory}/local-cache",
        "-o",
        f"Dir::Cache::archives={directory}/debs/",
        "-o",
        "APT::Sandbox::User=root",
        "-o",
        "APT::Get::allow-Downgrades=false",
    ]


def apt(
    tool: Prerequisites, label: str, options: list[str], arguments: list[str], seconds=300
) -> None:
    tool._attempt(
        label,
        lambda limit: tool._sudo(limit, "apt-get", *APT_OPTIONS, *options, *arguments),
        seconds,
    )


def install_offline(tool: Prerequisites, directory: Path, packages: list[str]) -> None:
    options = local_options(directory)
    apt(tool, "verified local apt index (file only)", options, ["update"], 60)
    empty = directory / "empty-status"
    empty.write_text("")
    install = ["install", "--yes", "--no-install-recommends", "--no-download", "--no-remove"]
    # A simulation with empty status proves the repository is a complete closure,
    # not a transaction that secretly relies on the producer's installed packages.
    apt(
        tool,
        "complete offline dependency closure",
        [*options, "-o", f"Dir::State::status={empty}"],
        [*install, "--simulate", *packages],
        60,
    )
    missing = [p for p in packages if not tool.installed(p)]
    if missing:
        apt(
            tool, "compatible runner offline solve", options, [*install, "--simulate", *missing], 60
        )
        apt(tool, "verified offline package install", options, [*install, *missing])
    if any(not tool.installed(p) for p in packages):
        raise BundleError("verified offline installation left required packages missing")


def prove(tool: Prerequisites, components: list[str]) -> None:
    from_commands = {
        "codec": ("ffmpeg", "ffprobe"),
        "filesystem": ("mkfs.ext4", "losetup", "mount", "umount", "findmnt"),
    }
    for component, commands in from_commands.items():
        if component in components:
            tool.require_commands(commands)
            if component == "codec":
                for command in commands:
                    tool.prove_version(command)
    if "browser" in components:
        tool.prove_browser()


def consume(ref: dict, key: str, directory: Path, components: list[str], node: bool) -> None:
    require_runner()
    payload, manifest = download(ref, key, directory)
    tool = Prerequisites(node_browser=node, offline=True)
    packages = manifest["requested_packages"]
    if (
        not isinstance(packages, list)
        or not packages
        or not all(re.fullmatch(r"[a-z0-9][a-z0-9.+-]*", p) for p in packages)
    ):
        raise IntegrityError("invalid required package list")
    install_offline(tool, payload, packages)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(payload / "browsers")
    prove(tool, components)
    with open(os.environ["GITHUB_ENV"], "a") as output:
        output.write(f"PLAYWRIGHT_BROWSERS_PATH={payload / 'browsers'}\n")
    print(
        f"Verified bundle from producer {ref['run_id']} / {ref['source_sha']}; "
        "consumer apt/browser downloads: 0",
        flush=True,
    )


def build(directory: Path, key: str) -> None:
    require_runner()
    directory.mkdir(parents=True, exist_ok=False)
    tool = Prerequisites(deadline_seconds=1200)
    node = Prerequisites(node_browser=True, deadline_seconds=1200)
    node._deadline = tool._deadline
    packages = sorted(set(tool.packages(list(COMPONENTS)) + node.browser_packages()))
    options = official_options(directory)
    (directory / "debs/partial").mkdir(parents=True)
    empty = directory / "producer-empty-status"
    empty.touch()
    apt(tool, "signed non-Azure Ubuntu indexes", options, ["update"], 120)
    apt(
        tool,
        "signed complete Debian closure download",
        [
            *options,
            "-o",
            f"Dir::State::status={empty}",
            "-o",
            f"Dir::Cache::archives={directory}/debs/",
        ],
        ["install", "--yes", "--no-install-recommends", "--download-only", *packages],
    )
    archives = sorted((directory / "debs").glob("*.deb"))
    if not archives:
        raise BundleError("producer obtained no complete Debian closure")
    records = []
    for path in archives:
        result = tool.runner(["dpkg-deb", "--field", str(path)], 30, None)
        if result.returncode:
            raise BundleError("producer could not inspect a Debian archive")
        records.append(
            result.stdout.rstrip()
            + f"\nFilename: {path.name}\nSize: {path.stat().st_size}\nSHA256: {digest(path)}\n"
        )
    (directory / "debs/Packages").write_text("\n".join(records))
    install_offline(tool, directory, packages)
    browsers = directory / "browsers"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)
    tool.install_browser()
    node.install_browser()
    prove(tool, list(COMPONENTS))
    prove(node, ["browser"])
    payload = directory / "bundle.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        for path in [*archives, directory / "debs/Packages"]:
            archive.add(path, arcname=f"debs/{path.name}")
        for path in sorted(browsers.iterdir()):
            if re.fullmatch(r"(?:chromium|chromium_headless_shell|ffmpeg)-[0-9]+", path.name):
                archive.add(path, arcname=f"browsers/{path.name}")
    manifest = {
        "schema": SCHEMA,
        "policy": POLICY,
        "identity": key,
        "baseline": baseline(),
        "origins": list(ORIGINS),
        "closure": "empty-status-offline-solve",
        "requested_packages": packages,
        "repository": os.environ["GITHUB_REPOSITORY"],
        "producer": {
            "run_id": int(os.environ["GITHUB_RUN_ID"]),
            "source_sha": os.environ["GITHUB_SHA"],
            "image": os.environ.get("ImageVersion"),  # noqa: SIM112 - GitHub's mixed-case variable
            "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        },
        "archive_sha256": digest(payload),
        "packages": {p.name: digest(p) for p in archives},
    }
    (directory / "bundle.json").write_text(json.dumps(manifest, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "admit", "reference", "consume"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--components", nargs="+", choices=COMPONENTS, default=list(COMPONENTS))
    parser.add_argument("--node-browser", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    try:
        key = identity(root)
        if args.command == "reference":
            ref = reference(
                os.environ["PREREQ_ARTIFACT_ID"], os.environ["PREREQ_ARTIFACT_DIGEST"], key
            )
            emit("reference", json.dumps(ref, separators=(",", ":")))
        elif args.command == "consume":
            consume(
                json.loads(os.environ["PREREQ_BUNDLE"]),
                key,
                args.directory,
                args.components,
                args.node_browser,
            )
        elif args.command == "admit":
            state = json.loads((args.directory / "publication.json").read_text())
            if state["identity"] != key:
                raise IntegrityError("publication identity changed during acquisition")
            # upload-artifact uses compression=0; reserve 64 KiB for ZIP headers.
            size = sum(p.stat().st_size for p in (args.directory / "publish").iterdir())
            if size + 65536 > MAX_PUBLICATION_BYTES:
                raise PublicationDeclined(
                    "proved bundle exceeds the reserved upload size; no upload"
                )
            admit_publication(key, os.environ["GITHUB_REPOSITORY"], state["recovery"])
        else:
            require_runner()
            if os.environ.get("PREREQ_PUBLICATION_OWNER") != PUBLICATION_OWNER:
                raise PublicationDeclined(
                    "publication ownership missing; use the serialized producer job"
                )
            print(f"Publication lookup under shared ownership: identity={key}", flush=True)
            recovery = None
            try:
                ref = find_published(key, os.environ["GITHUB_REPOSITORY"])
            except PublisherUnavailable:
                ref = None
            if ref:
                try:
                    consume(ref, key, args.directory / "reuse", list(COMPONENTS), False)
                    node = Prerequisites(node_browser=True, offline=True)
                    prove(node, ["browser"])
                except IntegrityError:
                    raise
                except PublisherUnavailable:
                    ref = None
                except BundleError:
                    raise
                except PrerequisiteError:
                    print(
                        "Published baseline no longer solves offline; rebuilding in producer.",
                        flush=True,
                    )
                    recovery, ref = ref, None
            if ref:
                emit("built", "false")
                emit("reference", json.dumps(ref, separators=(",", ":")))
            else:
                admit_publication(key, os.environ["GITHUB_REPOSITORY"], recovery)
                args.directory.mkdir(parents=True, exist_ok=True)
                (args.directory / "publication.json").write_text(
                    json.dumps({"identity": key, "recovery": recovery})
                )
                build(args.directory / "publish", key)
                emit("built", "true")
                emit("name", "ci-prerequisites-v2-" + key + "-" + os.environ["GITHUB_RUN_ATTEMPT"])
    except (PrerequisiteError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"::error::CI prerequisite bundle: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


def emit(name: str, value: str) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"{name}={value}\n")


if __name__ == "__main__":
    raise SystemExit(main())
