"""Opt-in production transport and durable, fixed-command host executor.

No AWS API, network download, build, shell command or caller-selected executable
is used on the host. The trusted coordinator admits sources and CI artifacts;
the host repeats transport, predecessor, backup and installer checks.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any, BinaryIO

VERBS = frozenset({"prepare", "install", "status", "backup", "canary", "rollback-app"})
ID = re.compile(r"[0-9a-f]{32}")
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
HOST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}")
ROOT = Path("/var/lib/ac-release-executor")
MAX_PAYLOAD = 4_000_000_000
MAX_JSON = 1_000_000


class RemoteError(RuntimeError):
    """Fixed errors only: transport output and secrets never enter the ledger."""


def encoded(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    parent_fd = os.open(path.parent.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    temporary = path.with_name("." + path.name + secrets.token_hex(6))
    with temporary.open("xb") as stream:
        stream.write(encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load(path: Path) -> Any:
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise RemoteError("remote JSON limit")
    return json.loads(raw)


def target(engine: Any, environment: str) -> Client | None:
    config = engine.paths.config / "targets.json"
    if not config.exists():
        return None
    value = load(config)
    if set(value) - {"staging", "production", "ssh"}:
        raise RemoteError("invalid release target map")
    if value.get("staging", "local") != "local":
        raise RemoteError("staging must stay local")
    selected = value.get(environment, "local")
    if selected == "local":
        return None
    if environment != "production" or not isinstance(selected, str):
        raise RemoteError("invalid release target")
    host = selected.removeprefix("remote:")
    if selected != "remote:" + host or not HOST.fullmatch(host):
        raise RemoteError("invalid release host")
    ssh = value.get("ssh", {})
    if set(ssh) != {"identity_file", "known_hosts_file"}:
        raise RemoteError("remote key and pinned known_hosts are required")
    for name in ssh.values():
        if not isinstance(name, str) or not name.startswith("/"):
            raise RemoteError("SSH paths must be absolute")
    return Client(engine, host, SSH(host, **ssh))


class SSH:
    def __init__(self, host: str, identity_file: str, known_hosts_file: str):
        self.host = host
        self.options = [
            "-F",
            "/dev/null",
            "-i",
            identity_file,
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={known_hosts_file}",
            "-o",
            "GlobalKnownHostsFile=/dev/null",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ForwardAgent=no",
            "-o",
            "RequestTTY=no",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ]

    def call(self, verb: str, request: dict[str, Any]) -> dict[str, Any]:
        if verb not in VERBS:
            raise RemoteError("remote verb refused")
        try:
            result = subprocess.run(  # noqa: S603 - fixed SSH command, validated host
                ["/usr/bin/ssh", *self.options, "root@" + self.host, "ac-release-executor", verb],
                input=encoded(request),
                capture_output=True,
                timeout=4200,
                check=False,
            )
            if result.returncode or len(result.stdout) > MAX_JSON:
                raise RemoteError("remote transport failed; outcome requires readback")
            return json.loads(result.stdout)
        except (ValueError, OSError, subprocess.SubprocessError):
            raise RemoteError("remote transport interrupted; outcome requires readback") from None

    def upload(self, request_id: str, path: Path) -> None:
        if not ID.fullmatch(request_id):
            raise RemoteError("invalid upload id")
        result = subprocess.run(  # noqa: S603 - legacy SCP to exact forced-command receiver
            [
                "/usr/bin/scp",
                "-O",
                *self.options,
                str(path),
                f"root@{self.host}:{ROOT}/incoming/{request_id}.tar",
            ],
            capture_output=True,
            timeout=1800,
            check=False,
        )
        if result.returncode:
            raise RemoteError("remote artifact upload failed")


class Client:
    def __init__(self, engine: Any, host: str, transport: Any):
        self.engine, self.host, self.transport = engine, host, transport

    def call(self, verb: str, **fields: Any) -> dict[str, Any]:
        request = {"target": self.host, "request_id": secrets.token_hex(16), **fields}
        response = self.transport.call(verb, request)
        if (
            response.get("target") != self.host
            or response.get("request_id") != request["request_id"]
        ):
            raise RemoteError("remote receipt identity mismatch")
        return response

    def status(self) -> dict[str, Any]:
        return self.call("status")["data"]

    def operation(self, verb: str, **fields: Any) -> Any:
        response = self.call(verb, **fields)
        if response.get("result") != "committed":
            raise RemoteError("remote operation refused or unknown")
        return response["data"]

    def deploy(
        self,
        component: str,
        build: Any,
        *,
        dry_run: bool,
        rollback: bool = False,
        native: bool = False,
        units_digest: str | None = None,
    ) -> dict[str, Any]:
        e = self.engine
        before = self.status()
        admitted = getattr(e, "_remote_expected_pair", before["pair"])
        if before["pair"] != admitted:
            raise RemoteError("stale production predecessor at coordinator")
        intent = {
            "target": self.host,
            "component": component,
            "sha": build.sha,
            "artifact_digest": build.artifact_digest,
            "backup_receipt": before.get("backup_receipt"),
            "expected": before["pair"],
            "dry_run": dry_run,
            "rollback": rollback,
            "native": native,
            "units_digest": units_digest,
            "controller": e.installed_engine(),
        }
        request_id = hashlib.sha256(encoded(intent)).hexdigest()[:32]
        home = e.paths.state / "remote-requests" / request_id
        manifest = home / "request.json"
        payload = home / "payload.tar"
        if not manifest.exists():
            home.mkdir(parents=True, mode=0o700, exist_ok=True)
            files: dict[str, Path] = {}
            bundle_files = (
                ("SHA256SUMS", "application-images.tar.gz", "release-images.env")
                if component == "core"
                else ("SHA256SUMS", "web-image.env", "web-image.json", "web-image.tar.gz")
            )
            bundle = e.store_bundle(build, component, frozenset(bundle_files))
            for name in bundle_files:
                files[f"store/{build.sha}/{component}/{name}"] = bundle / name
            provenance = e.paths.store / build.sha / f"{component}.provenance.json"
            if load(provenance).get("artifact_digest") != build.artifact_digest:
                raise RemoteError("admitted artifact differs from stored provenance")
            files[f"store/{build.sha}/{provenance.name}"] = provenance
            if component == "core":
                e.keep_native_build(build.sha)
                native_shas = {build.sha, before.get("native_sha")}
                for sha in sorted(s for s in native_shas if s):
                    directory = e.paths.native_store / sha
                    if directory.exists():
                        for name in (
                            "native-artifact.zip",
                            "artifact-metadata.json",
                            "workflow-run.json",
                        ):
                            files[f"store/native/{sha}/{name}"] = directory / name
            repository = home / "repository.bundle"
            e.run(
                [
                    "git",
                    f"--git-dir={e.paths.mirror}",
                    "bundle",
                    "create",
                    str(repository),
                    "--all",
                ],
                timeout=300,
            )
            files["repository.bundle"] = repository
            hashes = {name: digest(path) for name, path in files.items()}
            with tarfile.open(payload, "w") as archive:
                for name, path in sorted(files.items()):
                    archive.add(path, arcname=name, recursive=False)
            save(
                manifest,
                {
                    **intent,
                    "request_id": request_id,
                    "digests": hashes,
                    "payload_sha256": digest(payload),
                },
            )
        request = load(manifest)
        # Always query the same durable ID before any retry, including coordinator restart.
        found = self.call("status", lookup=request_id)["data"]["receipt"]
        if found is None:
            self.transport.upload(request_id, payload)
            prepared = self.transport.call("prepare", request)
            if prepared.get("result") != "prepared":
                raise RemoteError("remote preparation refused")
            found = prepared
        if found.get("result") == "prepared":
            try:
                found = self.transport.call("rollback-app" if rollback else "install", request)
            except (RemoteError, OSError, subprocess.SubprocessError):
                found = self.call("status", lookup=request_id)["data"]["receipt"]
        if not found or found.get("request_digest") != hashlib.sha256(encoded(request)).hexdigest():
            raise RemoteError("remote receipt does not bind the request")
        if (
            found.get("target") != self.host
            or found.get("request_id") != request_id
            or found.get("digests") != request["digests"]
            or found.get("result") != "committed"
        ):
            raise RemoteError("remote outcome unknown or refused; inspect receipt before recovery")
        after = self.status()
        wanted = dict(before["pair"])
        if not dry_run and not native:
            wanted[component] = build.sha
        if after["pair"] != wanted:
            raise RemoteError("remote final tuple differs; promotion refused")
        if hasattr(e, "_remote_expected_pair"):
            e._remote_expected_pair = wanted
        return {
            **found["data"],
            "remote_request_id": request_id,
            "remote_receipt_sha256": hashlib.sha256(encoded(found)).hexdigest(),
        }


class Executor:
    """Host lock plus write-ahead receipts. A running/unknown ID is never replayed."""

    def __init__(self, backend: Any, host: str, root: Path = ROOT):
        self.backend, self.host, self.root = backend, host, root

    def receipt_path(self, request_id: str) -> Path:
        return self.root / "receipts" / (request_id + ".json")

    def handle(self, verb: str, request: dict[str, Any]) -> dict[str, Any]:
        if (
            verb not in VERBS
            or request.get("target") != self.host
            or not ID.fullmatch(str(request.get("request_id", "")))
        ):
            raise RemoteError("executor identity or verb refused")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        with (self.root / "host.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            request_id = request["request_id"]
            receipt_path = self.receipt_path(request_id)
            previous = load(receipt_path) if receipt_path.exists() else None
            request_digest = hashlib.sha256(encoded(request)).hexdigest()
            if previous:
                if previous["request_digest"] != request_digest:
                    raise RemoteError("request id reused with different content")
                if verb != "install" and verb != "rollback-app" or previous["result"] != "prepared":
                    return previous
            started = time.time()
            receipt = {
                "schema": "ac.release.executor/1",
                "target": self.host,
                "request_id": request_id,
                "request_digest": request_digest,
                "verb": verb,
                "digests": request.get("digests", {}),
                "expected": request.get("expected"),
                "started_at": started,
                "boot_id": self.backend.boot_id(),
                "result": "running",
            }
            if verb == "status":
                lookup = request.get("lookup")
                if lookup is not None and not ID.fullmatch(str(lookup)):
                    raise RemoteError("invalid receipt lookup")
                path = self.receipt_path(lookup) if lookup else None
                old = load(path) if path and path.exists() else None
                if old and old["result"] == "running":
                    old = {**old, "result": "unknown"}
                return {
                    **receipt,
                    "result": "committed",
                    "data": {**self.backend.status(), "receipt": old},
                    "finished_at": time.time(),
                }
            save(receipt_path, receipt)
            mutation_started = False
            try:
                if verb in {"prepare", "install", "rollback-app"}:
                    for other in (self.root / "receipts").glob("*.json"):
                        old = load(other)
                        if other != receipt_path and old["result"] in {"running", "unknown"}:
                            raise RemoteError(
                                "unresolved host operation requires operator recovery"
                            )
                    self.validate_request(request)
                    if self.backend.status()["pair"] != request["expected"]:
                        raise RemoteError("stale production predecessor")
                    if verb == "prepare":
                        directory = self.unpack(request)
                        data = self.backend.prepare(request, directory)
                        receipt["result"] = "prepared"
                    else:
                        if not previous or previous["result"] != "prepared":
                            raise RemoteError("install requires a prepared request")
                        if request["rollback"] != (verb == "rollback-app"):
                            raise RemoteError("rollback verb mismatch")
                        if (
                            not request["dry_run"]
                            and not request["native"]
                            and not request["rollback"]
                        ):
                            # A fresh verified backup for this predecessor is mandatory.
                            if (
                                self.backend.status().get("backup_receipt")
                                != request["backup_receipt"]
                            ):
                                raise RemoteError("backup receipt changed since preparation")
                            receipt["backup"] = self.backend.require_backup(request["expected"])
                        mutation_started = not request["dry_run"] and not request["native"]
                        data = self.backend.install(request)
                        wanted = dict(request["expected"])
                        if not request["dry_run"] and not request["native"]:
                            wanted[request["component"]] = request["sha"]
                        final = self.backend.status()
                        if final["pair"] != wanted:
                            raise RemoteError("installer final tuple mismatch")
                        receipt["observed"] = {
                            key: final.get(key)
                            for key in ("pair", "images", "schema_head", "web_image")
                        }
                        receipt["result"] = "committed"
                else:
                    data = getattr(self.backend, verb)(request)
                    receipt["result"] = "committed"
                receipt["data"] = data
            except Exception:
                # The installer may have committed before it lost its response.
                receipt["result"] = "unknown" if mutation_started else "failed"
                receipt["error"] = "executor refused or interrupted; readback required"
            receipt["finished_at"] = time.time()
            receipt["duration_s"] = receipt["finished_at"] - started
            save(receipt_path, receipt)
            return receipt

    def validate_request(self, request: dict[str, Any]) -> None:
        fields = {
            "target",
            "request_id",
            "component",
            "sha",
            "artifact_digest",
            "backup_receipt",
            "expected",
            "dry_run",
            "rollback",
            "native",
            "units_digest",
            "controller",
            "digests",
            "payload_sha256",
        }
        if set(request) != fields or request["component"] not in {"core", "web"}:
            raise RemoteError("invalid install manifest")
        if not SHA.fullmatch(str(request["sha"])) or not SHA.fullmatch(str(request["controller"])):
            raise RemoteError("invalid source pin")
        if request["backup_receipt"] is not None and not HASH.fullmatch(
            str(request["backup_receipt"])
        ):
            raise RemoteError("invalid backup receipt pin")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(request["artifact_digest"])):
            raise RemoteError("invalid admitted artifact digest")
        if set(request["expected"]) != {"core", "web"} or any(
            sha is not None and not SHA.fullmatch(str(sha)) for sha in request["expected"].values()
        ):
            raise RemoteError("invalid predecessor tuple")
        if any(type(request[key]) is not bool for key in ("dry_run", "native", "rollback")):
            raise RemoteError("invalid operation flags")
        if request["native"] and (request["component"] != "core" or request["rollback"]):
            raise RemoteError("invalid native operation")
        if request["native"] and not HASH.fullmatch(str(request["units_digest"])):
            raise RemoteError("native predecessor digest missing")

    def unpack(self, request: dict[str, Any]) -> Path:
        archive_path = self.root / "incoming" / (request["request_id"] + ".tar")
        if (
            archive_path.is_symlink()
            or not archive_path.is_file()
            or archive_path.stat().st_size > MAX_PAYLOAD
        ):
            raise RemoteError("missing or excessive artifact")
        if digest(archive_path) != request["payload_sha256"]:
            raise RemoteError("artifact hash mismatch")
        directory = self.root / "requests" / request["request_id"]
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        digests = request["digests"]
        if not isinstance(digests, dict) or not 1 <= len(digests) <= 32:
            raise RemoteError("invalid artifact inventory")
        seen = set()
        total = 0
        with tarfile.open(archive_path) as archive:
            for member in archive:
                name = member.name
                allowed = name == "repository.bundle" or re.fullmatch(
                    r"store/(?:[0-9a-f]{40}/(?:core/(?:SHA256SUMS|application-images.tar.gz|release-images.env)|web/(?:SHA256SUMS|web-image.env|web-image.json|web-image.tar.gz)|(?:core|web).provenance.json)|native/[0-9a-f]{40}/(?:native-artifact.zip|artifact-metadata.json|workflow-run.json))",
                    name,
                )
                total += member.size
                if (
                    not allowed
                    or not member.isfile()
                    or name in seen
                    or total > MAX_PAYLOAD
                    or name not in digests
                ):
                    raise RemoteError("artifact member refused")
                seen.add(name)
                output = directory / name
                output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise RemoteError("artifact member missing")
                with output.open("xb") as destination:
                    shutil.copyfileobj(stream, destination, length=1024 * 1024)
                if digest(output) != digests[name]:
                    raise RemoteError("artifact hash mismatch")
                output.chmod(0o400)
        if seen != set(digests):
            raise RemoteError("artifact inventory mismatch")
        return directory


class HostBackend:
    """Use installed reviewed Engine methods, never an uploaded engine module."""

    def __init__(self, engine: Any, root: Path = ROOT):
        self.engine, self.root = engine, root

    def boot_id(self) -> str:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    def units(self) -> Path | None:
        candidates = sorted(
            (self.engine.paths.application / "operator-inputs/production").glob(
                "native-*-*/inputs/native-units.json"
            ),
            key=lambda path: path.stat().st_mtime,
        )
        return candidates[-1] if candidates else None

    def status(self) -> dict[str, Any]:
        e = self.engine
        core, web = e.current_core("production"), e.current_web("production")
        native = None
        activation = e.activation_path("production", core) if core else None
        if activation and activation.exists():
            native = e.native_for_image(load(activation)["native_image_ref"])[0]
        units = self.units()
        heads = {}
        for release in {core, *(p.name for p in (e.paths.application / "releases").glob("*"))} - {
            None
        }:
            with contextlib.suppress(Exception):
                heads[release] = e.migration_head(release)
        images = {}
        if core:
            manifest = e.paths.application / "releases" / core / "release-images.env"
            if manifest.is_file():
                for line in manifest.read_text().splitlines():
                    key, _, value = line.partition("=")
                    if key in {
                        "AC_API_IMAGE",
                        "AC_LEARNER_IMAGE",
                        "AC_ADMIN_IMAGE",
                        "AC_COACH_IMAGE",
                    }:
                        images[key] = value
        return {
            "pair": {"core": core, "web": web[0]},
            "images": images,
            "schema_head": heads.get(core),
            "backup_receipt": digest(self.root / "backup.json")
            if (self.root / "backup.json").exists()
            else None,
            "web_image": web[1],
            "native_sha": native,
            "units_path": str(units) if units else None,
            "units_digest": digest(units) if units else None,
            "migration_heads": heads,
            "approval_expires": e.approval_expires("production"),
            "restore_evidence": e.restore_check_evidence(),
            "web_rollback": e.web_rollback_entry("production"),
        }

    def prepare(self, request: dict[str, Any], directory: Path) -> dict[str, Any]:
        e = self.engine
        if request["controller"] != e.installed_engine():
            raise RemoteError("installed executor controller differs from coordinator")
        # Git bundles contain objects and refs, never local config/hooks/worktrees.
        if not e.paths.mirror.exists():
            e.run(["git", "init", "--bare", str(e.paths.mirror)])
        e.run(
            [
                "git",
                f"--git-dir={e.paths.mirror}",
                "fetch",
                str(directory / "repository.bundle"),
                "+refs/heads/*:refs/heads/*",
                "+refs/tags/*:refs/tags/*",
            ],
            timeout=300,
        )
        for path in (directory / "store").rglob("*"):
            if not path.is_file():
                continue
            output = e.paths.store / path.relative_to(directory / "store")
            output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if output.exists():
                if digest(output) != digest(path):
                    raise RemoteError("immutable host artifact differs")
            else:
                shutil.copyfile(path, output)
                output.chmod(0o400)
        return {"verified": True, "runtime_mutation": False}

    def require_backup(self, pair: dict[str, Any]) -> dict[str, Any]:
        receipt = self.root / "backup.json"
        if not receipt.exists():
            raise RemoteError("missing production backup")
        backup = load(receipt)
        # Web follows core in a promotion; the captured pre-core backup remains valid.
        if not 0 <= time.time() - backup["at"] < 1800:
            raise RemoteError("production backup stale")
        path = Path(backup["path"])
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size <= 0
            or digest(path) != backup["sha256"]
        ):
            raise RemoteError("production backup missing or corrupt")
        if pair["core"] not in backup["cores"]:
            raise RemoteError("backup predecessor mismatch")
        return {
            "sha256": backup["sha256"],
            "captured_at": backup["at"],
            "bytes": path.stat().st_size,
        }

    def backup(self, request: dict[str, Any]) -> dict[str, Any]:
        if set(request) == {"target", "request_id", "check_only"} and request["check_only"] is True:
            self.engine.train_disk_check()
            return {"verified": True}
        supervised = request.get("supervised") is True
        if set(request) != (
            {"target", "request_id", "supervised"} if supervised else {"target", "request_id"}
        ):
            raise RemoteError("backup arguments refused")
        e = self.engine
        try:
            path = Path(e.train_dump())
        except Exception:
            if not supervised:
                raise
            # The supervised ship path may use the approved full Drive snapshot.
            # Require the reviewed JSON/metadata contract; refuse older opaque output.
            started = time.time()
            result = e.run(
                ["/usr/local/sbin/ac-db-snapshot", "production", "before-remote", "--execute"],
                timeout=3600,
            )
            proof = json.loads(result.stdout)
            if (
                proof.get("upload_download_decrypt") != "passed"
                or proof.get("environment") != "production"
                or proof.get("metadata") != "same_exported_snapshot"
            ):
                raise RemoteError("verified snapshot receipt missing") from None
            directory = Path(proof["local_snapshot"])
            allowed = e.paths.backups.parents[1] / "production-snapshots"
            if directory.is_symlink() or directory.resolve().parent != allowed.resolve():
                raise RemoteError("snapshot path refused") from None
            path = directory / "backup.dump"
            metadata = load(directory / "metadata.json")
            if (
                metadata.get("release_id") != e.current_core("production")
                or metadata.get("environment") != "production"
                or metadata.get("dump_sha256") != digest(path)
                or metadata.get("dump_bytes") != path.stat().st_size
                or metadata.get("verification") != "pg_restore --list"
                or not started <= path.stat().st_mtime <= time.time()
            ):
                raise RemoteError("snapshot provenance mismatch") from None
        data = {
            "path": str(path),
            "sha256": digest(path),
            "at": time.time(),
            "cores": [self.engine.current_core("production")],
        }
        save(self.root / "backup.json", data)
        return {
            "sha256": data["sha256"],
            "verified": True,
            "path": str(path),
            "bytes": path.stat().st_size,
        }

    def install(self, request: dict[str, Any]) -> dict[str, Any]:
        e = self.engine
        build = e.stored_build(request["sha"], request["component"])
        if build is None or build.artifact_digest != request["artifact_digest"]:
            raise RemoteError("admitted build missing or artifact differs")
        if request["native"]:
            units = self.units()
            if units is None or digest(units) != request["units_digest"]:
                raise RemoteError("native predecessor changed")
            return e.prepare_native(
                "production", build.sha, units, request["units_digest"], dry_run=request["dry_run"]
            )
        if (
            request["rollback"]
            and request["component"] == "core"
            and e.migration_head(build.sha) != e.migration_head(request["expected"]["core"])
        ):
            raise RemoteError("application rollback schema changed")
        if request["component"] == "core":
            result = e.deploy_core(
                "production", build, dry_run=request["dry_run"], rollback_only=request["rollback"]
            )
        else:
            result = e.deploy_web("production", build, dry_run=request["dry_run"])
        if not request["dry_run"]:
            e.record(
                {
                    "environment": "production",
                    "component": request["component"],
                    "sha": build.sha,
                    "result": "success",
                    **result,
                }
            )
            if request["component"] == "core" and not request["rollback"]:
                path = self.root / "backup.json"
                backup = load(path)
                backup["cores"].append(build.sha)
                save(path, backup)
        return result

    def canary(self, request: dict[str, Any]) -> dict[str, Any]:
        smoke = request.get("mode") == "smoke"
        fields = (
            {"target", "request_id", "pair", "mode", "reuse"}
            if smoke
            else {"target", "request_id", "pair"}
        )
        if set(request) != fields or self.status()["pair"] != request["pair"]:
            raise RemoteError("canary tuple changed")
        e = self.engine
        if smoke:
            pair = tuple(request["pair"][key] for key in ("core", "web"))
            with e.train_source(pair[0]) as source:
                result = e.train_smoke("production", pair, source, reuse=request["reuse"])
            if self.status()["pair"] != request["pair"]:
                raise RemoteError("smoke tuple changed")
            return result
        e.run(["systemctl", "start", "ac-canary@production.service"], timeout=1800)
        result = e.run(
            ["systemctl", "show", "ac-canary@production.service", "-p", "Result", "--value"]
        )
        if result.stdout.strip() != "success" or self.status()["pair"] != request["pair"]:
            raise RemoteError("production canary failed")
        return {"result": "pass", "pair": request["pair"]}


def receive_scp(command: str, root: Path, source: BinaryIO, output: BinaryIO) -> None:
    """Single-file legacy SCP sink, no shell/scp subprocess, paths or timestamps."""
    match = re.fullmatch(
        r"scp -t " + re.escape(str(root)) + r"/incoming/([0-9a-f]{32})\.tar", command
    )
    if match is None:
        raise RemoteError("forced command refused")
    directory = root / "incoming"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    destination = directory / (match[1] + ".tar")
    output.write(b"\0")
    output.flush()
    header = source.readline(256)
    parsed = re.fullmatch(rb"C0[0-7]{3} ([0-9]{1,10}) [A-Za-z0-9._-]{1,100}\n", header)
    if parsed is None or not 0 < int(parsed[1]) <= MAX_PAYLOAD:
        raise RemoteError("SCP artifact header refused")
    remaining = int(parsed[1])
    temporary = directory / ("." + match[1] + secrets.token_hex(6))
    try:
        with temporary.open("xb") as handle:
            output.write(b"\0")
            output.flush()
            while remaining:
                block = source.read(min(remaining, 1024 * 1024))
                if not block:
                    raise RemoteError("SCP artifact interrupted")
                handle.write(block)
                remaining -= len(block)
            if source.read(1) != b"\0":
                raise RemoteError("SCP artifact terminator refused")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        # A lost SCP acknowledgement can be retried, but never replace admitted bytes.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if (
                destination.is_symlink()
                or not destination.is_file()
                or digest(destination) != digest(temporary)
            ):
                raise RemoteError("SCP request id reused with different bytes") from None
        output.write(b"\0")
        output.flush()
    finally:
        temporary.unlink(missing_ok=True)
