#!/usr/bin/env python3
"""Bounded schema-only publication; no database restore, pointer writes or deletion."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import importlib.util
import io
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import zipfile
import zlib
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ci import migration_schema_gate as gate  # noqa: E402

REPOSITORY = "authorityclosers/authority-closers-platform"
WORKFLOW = ".github/workflows/migration-schema-publish.yml"
PREFIX = "ac-migration-schema-"
MAX_PAYLOAD = 60_000
MAX_ZIP = MAX_PAYLOAD // 4 * 3
LIMITS = {"schema.dump": gate.MAX_DUMP_BYTES, "manifest.json": 8192}
MAX_PAIR = sum(LIMITS.values())
MAX_PUBLICATIONS = 4
MAX_PUBLICATION_BYTES = 128 * 1024 * 1024
ADMISSION_AGE = timedelta(minutes=15)
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
REQUEST = re.compile(r"[0-9a-f]{32}")
NAME = re.compile(PREFIX + r"(fictional|staging)-([0-9a-f]{32})-([0-9a-f]{40})-r([1-9][0-9]*)-a1")


class PublicationError(RuntimeError):
    """Only fixed, non-payload diagnostics may leave the helper."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationError(message)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def json_object(raw: bytes, limit: int) -> dict:
    require(0 < len(raw) <= limit, "JSON size exceeds its bound")
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(value, dict), "JSON object required")
    return value


def read_file(path: Path, limit: int) -> bytes:
    # O_NOFOLLOW and fstat bind validation to the opened regular file.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit, "invalid file size/type")
        raw = stream.read(limit + 1)
        require(len(raw) == info.st_size and len(raw) <= limit, "file changed or exceeded bound")
        return raw


def private_write(path: Path, raw: bytes) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(raw)


def temporary_root() -> str | None:
    return (
        os.environ.get("PAPERCLIP_RUN_SCRATCH_DIR")
        or os.environ.get("PAPERCLIP_SCRATCH_DIR")
        or os.environ.get("RUNNER_TEMP")
    )


def command(argv: list[str], data: bytes | None = None) -> bytes:
    process = None
    timer = None
    try:
        with tempfile.TemporaryFile(dir=temporary_root()) as source:
            source.write(data or b"")
            source.seek(0)
            process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell or token argv
                argv,
                stdin=source,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

            def stop() -> None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)

            timer = threading.Timer(60, stop)
            timer.start()
            assert process.stdout is not None
            size = 0
            chunks = []
            while chunk := process.stdout.read(65536):
                size += len(chunk)
                require(size <= 4 * 1024 * 1024, "bounded command output exceeded limit")
                chunks.append(chunk)
            require(process.wait(timeout=5) == 0, "bounded command failed")
            return b"".join(chunks)
    except (OSError, subprocess.SubprocessError):
        raise PublicationError(
            "bounded command failed; no dispatch retry or paid fallback"
        ) from None
    finally:
        if timer:
            timer.cancel()
        if process:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()


def api(path: str, *, data: dict | None = None, binary: bool = False):
    require(path.startswith(f"repos/{REPOSITORY}/") or path == "user", "fixed repository required")
    argv = ["gh", "api", path]
    if data is not None:
        argv += ["--method", "POST", "--input", "-"]
    raw = command(argv, json.dumps(data).encode() if data is not None else None)
    if binary:
        require(len(raw) <= MAX_ZIP, "download exceeded transport bound")
        return raw
    return json_object(raw, 4 * 1024 * 1024) if raw else None


def baseline() -> str:
    return gate.head(gate.load_migrations(ROOT / "db/migrations/versions"))


def inspect_dump(data: bytes, version: int) -> None:
    # This is TOC inspection only. Submitted schema SQL is never executed.
    tool_version = (
        command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                gate.POSTGRES_IMAGE,
                "pg_restore",
                "--version",
            ]
        )
        .decode()
        .strip()
    )
    match = re.fullmatch(r"pg_restore \(PostgreSQL\) ([0-9]+)\.[0-9]+.*", tool_version)
    require(match is not None and int(match[1]) == version // 10000, "PostgreSQL tooling mismatch")
    name = "ac-schema-toc-" + uuid4().hex
    try:
        listing = command(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--interactive",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "128m",
                "--pids-limit",
                "32",
                "--user",
                "postgres",
                gate.POSTGRES_IMAGE,
                "pg_restore",
                "--list",
            ],
            data,
        )
        require(len(listing) <= 4 * 1024 * 1024, "archive TOC exceeded bound")
        gate.validate_archive_listing(listing.decode())
    finally:
        # The only removable object is this run's random disposable tool container.
        subprocess.run(  # noqa: S603 - fixed argv, no service state
            ["docker", "rm", "--force", name],  # noqa: S607 - controlled executable
            capture_output=True,
            check=False,
            timeout=30,
        )


def validate_pair(pair: dict[str, bytes], manifest_sha: str, expected_baseline: str) -> dict:
    require(set(pair) == set(LIMITS), "exact two-file schema root required")
    # Reject duplicate fields before reusing the existing evidence API.
    json_object(pair["manifest.json"], LIMITS["manifest.json"])
    with tempfile.TemporaryDirectory(
        prefix="schema-validation-", dir=temporary_root()
    ) as directory:
        location = Path(directory)
        for name, raw in pair.items():
            require(0 < len(raw) <= LIMITS[name], "schema pair exceeded bound")
            private_write(location / name, raw)
        metadata, data = gate.load_evidence(location, manifest_sha, expected_baseline)
    inspect_dump(data, metadata["postgres_version_num"])
    return metadata


def read_pair(directory: Path) -> dict[str, bytes]:
    require(not directory.is_symlink() and directory.is_dir(), "regular schema directory required")
    require(
        {p.name for p in directory.iterdir()} == set(LIMITS), "exact two-file schema root required"
    )
    return {name: read_file(directory / name, limit) for name, limit in LIMITS.items()}


def unpack(raw: bytes) -> dict[str, bytes]:
    require(0 < len(raw) <= MAX_ZIP, "ZIP exceeded transport bound")
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(len(entries) == 2, "exact two-file schema root required")
        for entry in entries:
            mode = entry.external_attr >> 16
            require(
                entry.filename in LIMITS
                and entry.filename not in result
                and entry.orig_filename == entry.filename
                and not entry.is_dir()
                and not entry.flag_bits & 1
                and entry.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                and (stat.S_IFMT(mode) in {0, stat.S_IFREG})
                and 0 < entry.file_size <= LIMITS.get(entry.filename, 0)
                and 0 <= entry.compress_size <= len(raw),
                "invalid ZIP entry",
            )
            chunks = []
            size = 0
            with archive.open(entry) as stream:
                while chunk := stream.read(min(65536, LIMITS[entry.filename] - size + 1)):
                    size += len(chunk)
                    require(size <= LIMITS[entry.filename], "inflated ZIP exceeded bound")
                    chunks.append(chunk)
            require(size == entry.file_size, "ZIP size mismatch")
            result[entry.filename] = b"".join(chunks)
    return result


def pack(pair: dict[str, bytes]) -> str:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in LIMITS:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, pair[name])
    payload = base64.b64encode(stream.getvalue()).decode("ascii")
    require(len(payload) <= MAX_PAYLOAD, "schema exceeds dispatch input limit; no chunking")
    require(unpack(stream.getvalue()) == pair, "packed bytes differ")
    return payload


def identity(inputs: dict) -> None:
    require(
        set(inputs)
        == {"payload", "manifest_sha256", "publisher_sha", "mode", "request_id", "admission"},
        "invalid dispatch fields",
    )
    require(all(isinstance(v, str) for v in inputs.values()), "dispatch strings required")
    require(bool(SHA.fullmatch(inputs["publisher_sha"])), "full publisher SHA required")
    require(bool(HASH.fullmatch(inputs["manifest_sha256"])), "independent manifest SHA required")
    require(bool(REQUEST.fullmatch(inputs["request_id"])), "UUID hex request ID required")
    require(inputs["mode"] in {"fictional", "staging"}, "invalid publication mode")
    require(0 < len(inputs["payload"]) <= MAX_PAYLOAD, "payload exceeded transport bound")


def admission(inputs: dict, actor: int, pool: int) -> dict:
    value = json_object(inputs["admission"].encode(), 4096)
    require(
        set(value)
        == {
            "schema",
            "repository",
            "publisher_sha",
            "request_id",
            "mode",
            "operator_id",
            "admitted_at",
            "included_storage_headroom_bytes",
            "included_minutes_remaining",
            "repository_pool_bytes",
            "evidence_ref",
        },
        "invalid Root admission fields",
    )
    require(
        value["schema"] == "ac.schema_publication_admission/1"
        and value["repository"] == REPOSITORY,
        "Root admission identity mismatch",
    )
    require(
        all(value[k] == inputs[k] for k in ["publisher_sha", "request_id", "mode"]),
        "Root admission source/request mismatch",
    )
    require(
        type(value["operator_id"]) is int and actor > 0 and value["operator_id"] == actor,
        "Root operator mismatch",
    )
    require(
        isinstance(value["evidence_ref"], str)
        and bool(re.fullmatch(r"AUT-63/[0-9a-f-]{36}", value["evidence_ref"])),
        "governed admission receipt required",
    )
    stamp = datetime.fromisoformat(value["admitted_at"].replace("Z", "+00:00"))
    require(
        stamp.tzinfo is not None and timedelta(0) <= datetime.now(UTC) - stamp <= ADMISSION_AGE,
        "Root admission stale or future-dated",
    )
    require(
        type(pool) is int
        and 450_000_000 <= pool <= 4_000_000_000
        and type(value["repository_pool_bytes"]) is int
        and value["repository_pool_bytes"] == pool,
        "unknown repository pool",
    )
    require(
        type(value["included_storage_headroom_bytes"]) is int
        and value["included_storage_headroom_bytes"] >= MAX_PAIR,
        "unknown or exhausted included storage",
    )
    require(
        type(value["included_minutes_remaining"]) is int
        and value["included_minutes_remaining"] >= 10,
        "unknown or exhausted included minutes",
    )
    return value


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def inventory() -> list[dict]:
    reader = module(
        "schema_publication_inventory", ROOT / "infra/release/read-artifact-inventory.py"
    )
    return reader.read_inventory("gh", REPOSITORY, "admission")


def storage(artifacts: list[dict], pool: int, request_id: str, candidate_bytes: int) -> None:
    require(0 < candidate_bytes <= MAX_PAIR, "candidate size unknown")
    require(
        sum(a["size_in_bytes"] for a in artifacts) + MAX_PAIR <= pool,
        "repository artifact pool exhausted",
    )
    publications = [a for a in artifacts if a["name"].startswith(PREFIX)]
    require(
        all(NAME.fullmatch(a["name"]) for a in publications), "unknown schema artifact identity"
    )
    require(
        not any(NAME.fullmatch(a["name"])[2] == request_id for a in publications),
        "request already published; no overwrite",
    )
    live = [a for a in publications if not a["expired"]]
    require(len(live) < MAX_PUBLICATIONS, "four live schema artifact limit")
    # Reserve the maximum uncompressed pair for each prior artifact. This cannot
    # underestimate inflated bytes and requires no download/execution of old data.
    require(
        len(live) * MAX_PAIR + candidate_bytes <= MAX_PUBLICATION_BYTES,
        "aggregate schema publication bound",
    )


def assert_main(source: str) -> dict:
    main = api(f"repos/{REPOSITORY}/commits/main")
    require(main["sha"] == source, "main moved; readmit reviewed source")
    workflow = api(f"repos/{REPOSITORY}/actions/workflows/{Path(WORKFLOW).name}")
    require(
        workflow["path"] == WORKFLOW and workflow["state"] == "active",
        "publisher not registered on main",
    )
    require(
        command(["git", "rev-parse", "HEAD"]).decode().strip() == source,
        "local source differs from admitted main",
    )
    return workflow


def permission(actor: dict) -> None:
    require(
        type(actor.get("id")) is int
        and actor["id"] > 0
        and isinstance(actor.get("login"), str)
        and bool(re.fullmatch(r"[A-Za-z0-9-]+", actor["login"])),
        "invalid operator identity",
    )
    access = api(f"repos/{REPOSITORY}/collaborators/{actor['login']}/permission")
    require(
        access.get("permission") == "admin" or access.get("role_name") == "maintain",
        "dispatch requires existing governed admin/maintainer identity",
    )


def decode_inputs(inputs: dict) -> tuple[dict[str, bytes], dict]:
    identity(inputs)
    pair = unpack(base64.b64decode(inputs["payload"], validate=True))
    metadata = validate_pair(pair, inputs["manifest_sha256"], baseline())
    return pair, metadata


def prepare(event: dict, environment: dict, destination: Path) -> dict:
    require(
        environment.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
        and environment.get("GITHUB_REPOSITORY") == REPOSITORY
        and event.get("repository", {}).get("full_name") == REPOSITORY
        and event.get("ref") in {"main", "refs/heads/main"},
        "publisher event identity mismatch",
    )
    inputs = event["inputs"]
    identity(inputs)
    source = inputs["publisher_sha"]
    require(
        environment.get("GITHUB_REF") == "refs/heads/main"
        and environment.get("GITHUB_SHA") == source
        and environment.get("GITHUB_WORKFLOW_SHA") == source
        and environment.get("GITHUB_WORKFLOW_REF") == f"{REPOSITORY}/{WORKFLOW}@refs/heads/main"
        and command(["git", "rev-parse", "HEAD"]).decode().strip() == source,
        "event/workflow/checkout source mismatch",
    )
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "rerun is not an admitted publication")
    run_id = environment.get("GITHUB_RUN_ID", "")
    require(bool(re.fullmatch(r"[1-9][0-9]*", run_id)), "invalid source run")
    actor = event["sender"]
    require(
        environment.get("GITHUB_ACTOR") == actor["login"]
        and environment.get("GITHUB_TRIGGERING_ACTOR") == actor["login"],
        "dispatch actor mismatch",
    )
    permission(actor)
    pool_raw = environment.get("AC_RELEASE_ARTIFACT_POOL_BYTES", "")
    require(bool(re.fullmatch(r"[0-9]{9,10}", pool_raw)), "unknown repository pool")
    pool = int(pool_raw)
    admission(inputs, actor["id"], pool)
    pair, _ = decode_inputs(inputs)
    storage(inventory(), pool, inputs["request_id"], sum(map(len, pair.values())))
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, raw in pair.items():
        private_write(destination / name, raw)
    return {
        "artifact_name": f"{PREFIX}{inputs['mode']}-{inputs['request_id']}-{source}-r{run_id}-a1",
        "repository": REPOSITORY,
        "workflow_path": WORKFLOW,
        "source_sha": source,
        "run_id": int(run_id),
        "run_attempt": 1,
        "request_id": inputs["request_id"],
        "mode": inputs["mode"],
        "manifest_sha256": inputs["manifest_sha256"],
        "dump_sha256": hashlib.sha256(pair["schema.dump"]).hexdigest(),
    }


def run_identity(run: dict, state: dict, run_id: int, workflow_id: int) -> None:
    require(
        run.get("id") == run_id
        and run.get("run_attempt") == 1
        and run.get("workflow_id") == workflow_id
        and run.get("path", "").split("@", 1)[0] == WORKFLOW
        and run.get("head_sha") == state["publisher_sha"]
        and run.get("head_branch") == "main"
        and run.get("event") == "workflow_dispatch"
        and run.get("repository", {}).get("full_name") == REPOSITORY
        and run.get("actor", {}).get("id") == state["operator_id"]
        and run.get("triggering_actor", {}).get("id") == state["operator_id"]
        and run.get("status") == "completed"
        and run.get("conclusion") == "success",
        "source run/workflow identity mismatch or run incomplete",
    )


def read_back(state: dict, original: dict[str, bytes], run_id: int) -> dict:
    workflow = api(f"repos/{REPOSITORY}/actions/workflows/{Path(WORKFLOW).name}")
    require(workflow["path"] == WORKFLOW, "workflow identity mismatch")
    run_path = f"repos/{REPOSITORY}/actions/runs/{run_id}"
    run_identity(api(run_path), state, run_id, workflow["id"])
    listing = api(run_path + "/artifacts?per_page=100")
    name = f"{PREFIX}{state['mode']}-{state['request_id']}-{state['publisher_sha']}-r{run_id}-a1"
    require(
        listing.get("total_count") == 1 and len(listing.get("artifacts", [])) == 1,
        "ambiguous publication artifact",
    )
    artifact = listing["artifacts"][0]
    require(
        artifact.get("name") == name
        and artifact.get("expired") is False
        and type(artifact.get("id")) is int
        and artifact["id"] > 0
        and type(artifact.get("size_in_bytes")) is int
        and 0 < artifact["size_in_bytes"] <= MAX_ZIP,
        "expired or mismatched artifact",
    )
    artifact_path = f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}"
    exact = api(artifact_path)
    require(
        exact.get("id") == artifact["id"]
        and exact.get("name") == name
        and exact.get("expired") is False
        and exact.get("workflow_run", {}).get("id") == run_id
        and exact.get("workflow_run", {}).get("head_sha") == state["publisher_sha"],
        "artifact source run mismatch",
    )
    downloaded = unpack(api(artifact_path + "/zip", binary=True))
    require(downloaded == original, "independent downloaded bytes differ from original pair")
    metadata = validate_pair(downloaded, state["manifest_sha256"], baseline())
    # A rerun or expiry during download invalidates the candidate, never pointers.
    run_identity(api(run_path), state, run_id, workflow["id"])
    require(api(artifact_path).get("expired") is False, "artifact expired during verification")
    return {
        "schema": "ac.schema_publication_receipt/1",
        "artifact_id": artifact["id"],
        "repository": REPOSITORY,
        "workflow_path": WORKFLOW,
        "workflow_id": workflow["id"],
        "run_id": run_id,
        "run_attempt": 1,
        "source_sha": state["publisher_sha"],
        "request_id": state["request_id"],
        "mode": state["mode"],
        "manifest_sha256": state["manifest_sha256"],
        "dump_sha256": metadata["dump_sha256"],
        "exact_root_and_original_bytes": True,
    }


def scratch() -> Path:
    raw = os.environ.get("PAPERCLIP_RUN_SCRATCH_DIR") or os.environ.get("PAPERCLIP_SCRATCH_DIR")
    require(bool(raw), "private run-owned scratch directory required")
    path = Path(raw).resolve()
    require(path.is_dir() and path.stat().st_uid == os.geteuid(), "run scratch ownership mismatch")
    path.chmod(0o700)
    return path


def preflight(inputs: dict, pair: dict[str, bytes]) -> dict:
    identity(inputs)
    actor = api("user")
    permission(actor)
    value = json_object(inputs["admission"].encode(), 4096)
    pool = value.get("repository_pool_bytes")
    admission(inputs, actor["id"], pool)
    actual_pool = api(f"repos/{REPOSITORY}/actions/variables/AC_RELEASE_ARTIFACT_POOL_BYTES")
    require(actual_pool.get("value") == str(pool), "admitted pool differs from read-back")
    assert_main(inputs["publisher_sha"])
    storage(inventory(), pool, inputs["request_id"], sum(map(len, pair.values())))
    return actor


def dispatch_saved(request_id: str) -> None:
    require(bool(REQUEST.fullmatch(request_id)), "invalid request ID")
    folder = scratch() / request_id
    request = json_object(read_file(folder / "dispatch.json", 70_000), 70_000)
    require(
        set(request) == {"ref", "inputs"} and request["ref"] == "main", "main dispatch required"
    )
    inputs = request["inputs"]
    require(inputs["request_id"] == request_id, "saved request identity mismatch")
    pair, _ = decode_inputs(inputs)
    actor = preflight(inputs, pair)
    state = json_object(read_file(folder / "state.json", 4096), 4096)
    require(
        all(
            state.get(k) == inputs[k]
            for k in ["publisher_sha", "request_id", "mode", "manifest_sha256"]
        )
        and state.get("operator_id") == actor["id"],
        "saved operator/source mismatch",
    )
    # Persist before the only mutation: an ambiguous transport failure is not retryable.
    private_write(folder / "dispatch-attempted", b"one attempt; never replay\n")
    assert_main(inputs["publisher_sha"])
    api(f"repos/{REPOSITORY}/actions/workflows/{Path(WORKFLOW).name}/dispatches", data=request)


def fictional_fixture(output: Path) -> dict:
    require(
        output.is_relative_to(scratch()) and not output.exists(), "new run-owned fixture required"
    )
    with gate.disposable_postgres() as database:
        with database.connect() as connection:
            connection.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            connection.execute("CREATE TABLE fictional_publication (id integer PRIMARY KEY)")
            connection.execute("INSERT INTO fictional_publication VALUES (1)")
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
        data = database.tool(
            "pg_dump",
            "-U",
            "ac_owner",
            "-d",
            "ac_migration_safety",
            "--format=custom",
            "--schema-only",
            "--no-owner",
            "--no-acl",
        )
    metadata = {
        "schema": "ac.migration_schema/1",
        "environment": "staging",
        "schema_only": True,
        "postgres_version_num": version,
        "alembic_revision": baseline(),
        "exported_at": datetime.now(UTC).isoformat(),
        "dump_sha256": hashlib.sha256(data).hexdigest(),
        "release_id": command(["git", "rev-parse", "HEAD"]).decode().strip(),
    }
    pair = {"schema.dump": data, "manifest.json": json.dumps(metadata, sort_keys=True).encode()}
    checksum = hashlib.sha256(pair["manifest.json"]).hexdigest()
    validate_pair(pair, checksum, baseline())
    output.mkdir(mode=0o700, exist_ok=False)
    for name, raw in pair.items():
        private_write(output / name, raw)
    return {
        "mode": "fictional",
        "manifest_sha256": checksum,
        "dump_sha256": metadata["dump_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    local = sub.add_parser("pack")
    local.add_argument("--pair-dir", type=Path, required=True)
    local.add_argument("--manifest-sha256", required=True)
    local.add_argument("--publisher-sha", required=True)
    local.add_argument("--mode", choices=["fictional", "staging"], required=True)
    local.add_argument("--request-id", required=True)
    local.add_argument("--admission-file", type=Path, required=True)
    local.add_argument(
        "--apply", action="store_true", help="dispatch; default validates and packs only"
    )
    check = sub.add_parser("read-back")
    check.add_argument("--request-id", required=True)
    check.add_argument("--pair-dir", type=Path, required=True)
    check.add_argument("--run-id", type=int, required=True)
    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--request-id", required=True)
    reject = sub.add_parser("reject")
    reject.add_argument("--request-id", required=True)
    reject.add_argument("--candidate-artifact-id", type=int, required=True)
    fixture = sub.add_parser("fictional-fixture")
    fixture.add_argument("--output", type=Path, required=True)
    action = sub.add_parser("prepare-action")
    action.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "fictional-fixture":
            print(json.dumps(fictional_fixture(args.output.resolve()), sort_keys=True))
        elif args.operation == "dispatch":
            dispatch_saved(args.request_id)
            print("schema-publication: dispatch accepted; independent read-back required")
        elif args.operation == "reject":
            require(
                bool(REQUEST.fullmatch(args.request_id)) and args.candidate_artifact_id > 0,
                "invalid rejection identity",
            )
            private_write(
                scratch() / args.request_id / "rejected-candidate.json",
                json.dumps(
                    {
                        "request_id": args.request_id,
                        "rejected_artifact_id": args.candidate_artifact_id,
                        "pointers_unchanged": True,
                        "deletion": False,
                    }
                ).encode(),
            )
            print("schema-publication: rejection recorded; candidate expires, pointers unchanged")
        elif args.operation == "prepare-action":
            event = json_object(read_file(Path(os.environ["GITHUB_EVENT_PATH"]), 80_000), 80_000)
            receipt = prepare(event, dict(os.environ), args.destination)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
                stream.write(f"artifact-name={receipt['artifact_name']}\n")
            private_write(
                args.destination.parent / "publication-candidate.json", json.dumps(receipt).encode()
            )
            print("schema-publication: validated candidate (independent read-back still required)")
        elif args.operation == "pack":
            pair = read_pair(args.pair_dir)
            validate_pair(pair, args.manifest_sha256, baseline())
            inputs = {
                "payload": pack(pair),
                "manifest_sha256": args.manifest_sha256,
                "publisher_sha": args.publisher_sha,
                "mode": args.mode,
                "request_id": args.request_id,
                "admission": read_file(args.admission_file, 4096).decode(),
            }
            actor = preflight(inputs, pair)
            folder = scratch() / args.request_id
            folder.mkdir(mode=0o700, exist_ok=False)
            request = {"ref": "main", "inputs": inputs}
            private_write(folder / "dispatch.json", json.dumps(request).encode())
            state = {
                k: inputs[k] for k in ["publisher_sha", "mode", "request_id", "manifest_sha256"]
            }
            state["operator_id"] = actor["id"]
            private_write(folder / "state.json", json.dumps(state).encode())
            if args.apply:
                dispatch_saved(args.request_id)
                print("schema-publication: dispatch accepted; independent read-back required")
            else:
                print("schema-publication: dry-run PASS (private pack; no dispatch)")
        else:
            require(
                bool(REQUEST.fullmatch(args.request_id)) and args.run_id > 0,
                "invalid read-back identity",
            )
            folder = scratch() / args.request_id
            state = json_object(read_file(folder / "state.json", 4096), 4096)
            require(state.get("request_id") == args.request_id, "local request identity mismatch")
            receipt = read_back(state, read_pair(args.pair_dir), args.run_id)
            private_write(
                folder / "verified-receipt.json",
                json.dumps(receipt, sort_keys=True, indent=2).encode(),
            )
            print(json.dumps(receipt, sort_keys=True))
        return 0
    except (
        PublicationError,
        gate.GateError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        binascii.Error,
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        NotImplementedError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        # Never echo event bytes, API errors, URLs, argv, manifest values or credentials.
        print(
            "schema-publication: FAIL (validation or read-back unavailable; pointers unchanged)",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
