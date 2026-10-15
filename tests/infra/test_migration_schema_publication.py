"""Schema transport failures and fictional byte proof; no live service writes."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import os
import secrets
import stat
import struct
import subprocess
import sys
import warnings
import zipfile
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "migration_schema_publication",
    Path(__file__).resolve().parents[2] / "scripts/ops/publish_migration_schema.py",
)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

SOURCE = "a" * 40
REQUEST = "b" * 32
BASELINE = "20261010_0001"
POOL = 2_000_000_000
ACTOR = {"id": 123, "login": "fictional-root"}
PAYLOADS: dict[str, bytes] = {}
REAL_FETCH = publisher.fetch_blob


def fixture_pair(data=b"PGDMPfictional", **changes):
    metadata = {
        "schema": "ac.migration_schema/1",
        "environment": "staging",
        "schema_only": True,
        "postgres_version_num": 180000,
        "alembic_revision": BASELINE,
        "exported_at": datetime.now(UTC).isoformat(),
        "dump_sha256": hashlib.sha256(data).hexdigest(),
        "release_id": SOURCE,
    }
    metadata.update(changes)
    return {"schema.dump": data, "manifest.json": json.dumps(metadata).encode()}


def admission_value(**changes):
    value = {
        "schema": "ac.schema_publication_admission/1",
        "repository": publisher.REPOSITORY,
        "publisher_sha": SOURCE,
        "request_id": REQUEST,
        "mode": "fictional",
        "operator_id": ACTOR["id"],
        "admitted_at": datetime.now(UTC).isoformat(),
        "included_storage_headroom_bytes": publisher.MAX_PAIR,
        "included_minutes_remaining": 10,
        "repository_pool_bytes": POOL,
        "evidence_ref": "AUT-63/" + "c" * 36,
    }
    value.update(changes)
    return value


def dispatch_inputs(pair=None, **changes):
    pair = pair or fixture_pair()
    raw = publisher.pack(pair)
    PAYLOADS[publisher.blob_sha(raw)] = raw
    inputs = {
        "payload_blob": publisher.blob_sha(raw),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_sha256": hashlib.sha256(pair["manifest.json"]).hexdigest(),
        "publisher_sha": SOURCE,
        "mode": "fictional",
        "request_id": REQUEST,
        "admission": json.dumps(admission_value()),
    }
    inputs.update(changes)
    return inputs


def payload(inputs):
    return PAYLOADS[inputs["payload_blob"]]


def decode(inputs):
    return publisher.decode_inputs(inputs, payload(inputs))


@pytest.fixture
def validation(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPERCLIP_RUN_SCRATCH_DIR", str(tmp_path))
    monkeypatch.setattr(publisher, "baseline", lambda: BASELINE)
    monkeypatch.setattr(publisher, "inspect_dump", lambda *_: None)
    monkeypatch.setattr(publisher, "fetch_blob", payload)


def archive(entries):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in entries:
                bundle.writestr(name, data)
    return stream.getvalue()


def test_transport_preserves_original_bytes_and_private_files(validation, tmp_path):
    pair = fixture_pair()
    unpacked, metadata = decode(dispatch_inputs(pair))
    assert unpacked == pair and metadata["alembic_revision"] == BASELINE
    directory = tmp_path / "pair"
    directory.mkdir(mode=0o700)
    for name, raw in pair.items():
        publisher.private_write(directory / name, raw)
        assert stat.S_IMODE((directory / name).stat().st_mode) == 0o600
    assert publisher.read_pair(directory) == pair
    (directory / "extra").write_bytes(b"forbidden")
    with pytest.raises(publisher.PublicationError, match="two-file"):
        publisher.read_pair(directory)


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [("schema.dump", b"x")],
        [("schema.dump", b"x"), ("schema.dump", b"y")],
        [("../schema.dump", b"x"), ("manifest.json", b"{}")],
        [("/schema.dump", b"x"), ("manifest.json", b"{}")],
        [("folder/schema.dump", b"x"), ("manifest.json", b"{}")],
        [("schema.dump/", b"x"), ("manifest.json", b"{}")],
        [("schema.dump", b"x"), ("manifest.json", b"{}"), ("extra", b"x")],
        [("schema.dump", b""), ("manifest.json", b"{}")],
    ],
)
def test_missing_extra_duplicate_traversal_and_empty_entries_fail(entries):
    with pytest.raises(publisher.PublicationError):
        publisher.unpack(archive(entries))


@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        "fifo",
        "directory",
        "encrypted",
        "unsupported",
        "inflated",
        "crc",
        "corrupt",
        "oversized",
    ],
)
def test_hostile_zip_metadata_and_corruption_fail(kind, monkeypatch):
    pair = fixture_pair()
    if kind in {"symlink", "fifo", "directory"}:
        entry = zipfile.ZipInfo("schema.dump")
        entry.create_system = 3
        file_type = {"symlink": stat.S_IFLNK, "fifo": stat.S_IFIFO, "directory": stat.S_IFDIR}[kind]
        entry.external_attr = (file_type | 0o600) << 16
        raw = archive([(entry, pair["schema.dump"]), ("manifest.json", pair["manifest.json"])])
    else:
        raw = bytearray(publisher.pack(pair))
        central = raw.index(b"PK\x01\x02")
        if kind == "encrypted":
            struct.pack_into("<H", raw, central + 8, 1)
        elif kind == "unsupported":
            struct.pack_into("<H", raw, central + 10, 99)
        elif kind == "inflated":
            struct.pack_into("<I", raw, central + 24, publisher.LIMITS["schema.dump"] + 1)
        elif kind == "crc":
            struct.pack_into("<I", raw, central + 16, 0)
        elif kind == "corrupt":
            raw = raw[:10]
        else:
            monkeypatch.setattr(publisher, "MAX_ZIP", len(raw) - 1)
    with pytest.raises((publisher.PublicationError, zipfile.BadZipFile, NotImplementedError)):
        publisher.unpack(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"exported_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat()},
        {"exported_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
        {"alembic_revision": "20261009_0001"},
        {"postgres_version_num": True},
        {"schema_only": False},
        {"environment": "production"},
        {"unexpected": "x"},
        {"release_id": "not-a-sha"},
        {"dump_sha256": "f" * 64},
    ],
)
def test_manifest_freshness_baseline_and_checksum_reused(validation, changes):
    pair = fixture_pair(**changes)
    with pytest.raises((publisher.PublicationError, publisher.gate.GateError)):
        decode(dispatch_inputs(pair))


def test_duplicate_manifest_keys_and_checksum_mismatch_fail(validation):
    pair = fixture_pair()
    pair["manifest.json"] = b'{"schema_only":true,"schema_only":false}'
    with pytest.raises(publisher.PublicationError, match="duplicate"):
        decode(dispatch_inputs(pair))
    with pytest.raises(publisher.gate.GateError, match="checksum"):
        decode(dispatch_inputs(manifest_sha256="f" * 64))


def test_blob_identity_binds_bytes_and_bound(validation, tmp_path):
    inputs = dispatch_inputs()
    raw = payload(inputs)
    expected = (
        subprocess.run(  # noqa: S603 - fixed argv, fictional bytes
            ["git", "hash-object", "--stdin"],  # noqa: S607 - controlled executable
            input=raw,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    assert publisher.blob_sha(raw) == expected == inputs["payload_blob"]
    with pytest.raises(publisher.PublicationError, match="differ"):
        publisher.decode_inputs(inputs, raw + b"x")
    with pytest.raises(publisher.PublicationError, match="differ"):
        publisher.decode_inputs(dict(inputs, payload_sha256="f" * 64), raw)
    with pytest.raises(publisher.PublicationError, match="differ"):
        publisher.decode_inputs(dict(inputs, payload_blob="f" * 40), raw)
    with pytest.raises(publisher.PublicationError, match="exceeded"):
        publisher.verify_payload(inputs, b"x" * (publisher.MAX_ZIP + 1))
    with pytest.raises(publisher.PublicationError, match="dispatch fields"):
        publisher.identity({k: v for k, v in inputs.items() if k != "payload_sha256"})


def test_bound_pair_fits_blob_transport_without_dispatch_input(validation):
    data = b"PGDMP" + secrets.token_bytes(publisher.LIMITS["schema.dump"] - 5)
    pair = fixture_pair(data)
    raw = publisher.pack(pair)
    assert len(raw) <= publisher.MAX_ZIP < 100 * 1024 * 1024
    inputs = dispatch_inputs(pair)
    assert max(len(v) for v in inputs.values()) < 4096
    assert decode(inputs)[0] == pair
    too_large = fixture_pair(data + b"x")
    with pytest.raises(publisher.PublicationError, match="exceeded bound"):
        publisher.validate_pair(too_large, "f" * 64, BASELINE)


def test_runner_fetches_blob_from_fixed_repository_only(validation, monkeypatch):
    inputs = dispatch_inputs()
    monkeypatch.setattr(publisher, "fetch_blob", REAL_FETCH)
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        return payload(inputs)

    monkeypatch.setattr(publisher, "api", fake_api)
    assert publisher.fetch_blob(inputs) == payload(inputs)
    path, kwargs = calls[0]
    assert path == f"repos/{publisher.REPOSITORY}/git/blobs/{inputs['payload_blob']}"
    assert kwargs == {
        "binary": True,
        "accept": publisher.RAW_BLOB,
        "seconds": publisher.MAX_TRANSFER_SECONDS,
    }
    monkeypatch.setattr(publisher, "api", lambda *a, **k: payload(inputs) + b"x")
    with pytest.raises(publisher.PublicationError, match="differ"):
        publisher.fetch_blob(inputs)
    with pytest.raises(publisher.PublicationError, match="dispatch fields"):
        publisher.fetch_blob({"payload_blob": "../" + "a" * 37})


def test_pair_never_follows_links(validation, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"PGDMPfictional")
    pair = tmp_path / "pair"
    pair.mkdir()
    (pair / "schema.dump").symlink_to(outside)
    (pair / "manifest.json").write_bytes(b"{}")
    with pytest.raises(OSError):
        publisher.read_pair(pair)


@pytest.mark.parametrize(
    "changes",
    [
        {"included_storage_headroom_bytes": None},
        {"included_storage_headroom_bytes": 0},
        {"included_minutes_remaining": None},
        {"included_minutes_remaining": 9},
        {"included_minutes_remaining": True},
        {"repository_pool_bytes": None},
        {"operator_id": 999},
        {"publisher_sha": "d" * 40},
        {"request_id": "d" * 32},
        {"mode": "staging"},
        {"evidence_ref": "not-root-receipt"},
        {"admitted_at": (datetime.now(UTC) - timedelta(minutes=16)).isoformat()},
        # Parameters are built at collection time; a long shard must not age this
        # future stamp into the 15-minute admission window before the case runs.
        {"admitted_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ],
)
def test_unknown_exhausted_stale_or_mismatched_root_admission_fails(changes):
    inputs = dispatch_inputs(admission=json.dumps(admission_value(**changes)))
    with pytest.raises(publisher.PublicationError):
        publisher.admission(inputs, ACTOR["id"], POOL)


def artifact(index, **changes):
    value = {
        "id": index,
        "size_in_bytes": 1000,
        "expired": False,
        "name": f"{publisher.PREFIX}fictional-{index:032x}-{SOURCE}-r{index}-a1",
    }
    value.update(changes)
    return value


def test_inventory_counts_all_repository_bytes_and_reserves_inflated_bytes():
    publisher.storage([], POOL, REQUEST, 1024)
    publisher.storage([artifact(i) for i in range(1, 4)], POOL, REQUEST, 1024)
    with pytest.raises(publisher.PublicationError, match="four live"):
        publisher.storage([artifact(i) for i in range(1, 5)], POOL, REQUEST, 1024)
    with pytest.raises(publisher.PublicationError, match="aggregate"):
        publisher.storage([artifact(i) for i in range(1, 4)], POOL, REQUEST, publisher.MAX_PAIR)
    with pytest.raises(publisher.PublicationError, match="repository.*exhausted"):
        publisher.storage(
            [artifact(1, name="release-image", size_in_bytes=POOL)], POOL, REQUEST, 1024
        )
    with pytest.raises(publisher.PublicationError, match="unknown"):
        publisher.storage([artifact(1, name=publisher.PREFIX + "unknown")], POOL, REQUEST, 1024)
    with pytest.raises(publisher.PublicationError, match="already published"):
        publisher.storage(
            [artifact(1, name=f"{publisher.PREFIX}staging-{REQUEST}-{SOURCE}-r1-a1")],
            POOL,
            REQUEST,
            1024,
        )
    publisher.storage([artifact(1, expired=True)], POOL, REQUEST, 1024)


@pytest.fixture
def action_context(validation, monkeypatch):
    monkeypatch.setattr(publisher, "command", lambda *a, **kw: SOURCE.encode())
    monkeypatch.setattr(publisher, "fetch_blob", payload)
    monkeypatch.setattr(publisher, "permission", lambda _: None)
    monkeypatch.setattr(publisher, "inventory", lambda: [])
    event = {
        "repository": {"full_name": publisher.REPOSITORY},
        "ref": "refs/heads/main",
        "sender": ACTOR,
        "inputs": dispatch_inputs(),
    }
    environment = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": publisher.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": SOURCE,
        "GITHUB_WORKFLOW_SHA": SOURCE,
        "GITHUB_WORKFLOW_REF": f"{publisher.REPOSITORY}/{publisher.WORKFLOW}@refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "321",
        "GITHUB_ACTOR": ACTOR["login"],
        "GITHUB_TRIGGERING_ACTOR": ACTOR["login"],
        "AC_RELEASE_ARTIFACT_POOL_BYTES": str(POOL),
    }
    return event, environment


def test_action_admits_exact_source_and_distinct_fictional_pair(action_context, tmp_path):
    event, environment = action_context
    destination = tmp_path / "candidate"
    receipt = publisher.prepare(event, environment, destination)
    assert publisher.read_pair(destination) == publisher.unpack(payload(event["inputs"]))
    assert receipt["artifact_name"] == f"{publisher.PREFIX}fictional-{REQUEST}-{SOURCE}-r321-a1"
    assert set(p.name for p in destination.iterdir()) == {"schema.dump", "manifest.json"}
    assert "artifact_id" not in receipt


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GITHUB_SHA", "d" * 40),
        ("GITHUB_WORKFLOW_SHA", "d" * 40),
        ("GITHUB_WORKFLOW_REF", "other/workflow@refs/heads/main"),
        ("GITHUB_REF", "refs/heads/task"),
        ("GITHUB_EVENT_NAME", "pull_request"),
        ("GITHUB_REPOSITORY", "foreign/repo"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_TRIGGERING_ACTOR", "foreign-operator"),
        ("AC_RELEASE_ARTIFACT_POOL_BYTES", ""),
    ],
)
def test_source_actor_and_pool_mismatch_fails_before_output(action_context, tmp_path, key, value):
    event, environment = action_context
    environment[key] = value
    with pytest.raises(publisher.PublicationError):
        publisher.prepare(event, environment, tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()


@pytest.fixture
def readback_context(validation, monkeypatch):
    pair = fixture_pair()
    inputs = dispatch_inputs(pair)
    state = {k: inputs[k] for k in ["request_id", "publisher_sha", "manifest_sha256", "mode"]}
    state["operator_id"] = ACTOR["id"]
    run = {
        "id": 321,
        "run_attempt": 1,
        "workflow_id": 654,
        "path": publisher.WORKFLOW + "@main",
        "head_sha": SOURCE,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "repository": {"full_name": publisher.REPOSITORY},
        "actor": ACTOR,
        "triggering_actor": ACTOR,
        "status": "completed",
        "conclusion": "success",
    }
    item = artifact(789, name=f"{publisher.PREFIX}fictional-{REQUEST}-{SOURCE}-r321-a1")
    item["workflow_run"] = {"id": 321, "head_sha": SOURCE}
    values = {
        "run": run,
        "listing": {"total_count": 1, "artifacts": [item]},
        "artifact": item,
        "download": payload(inputs),
    }

    def fake_api(path, **kwargs):
        assert "data" not in kwargs, "read-back attempted mutation"
        if "/workflows/" in path:
            return {"id": 654, "path": publisher.WORKFLOW}
        if path.endswith("/zip"):
            return values["download"]
        if "?per_page=" in path:
            return values["listing"]
        if "/runs/" in path:
            return values["run"]
        return values["artifact"]

    monkeypatch.setattr(publisher, "api", fake_api)
    return state, pair, values


def test_only_independent_download_returns_usable_receipt(readback_context):
    state, pair, _ = readback_context
    result = publisher.read_back(state, pair, 321)
    assert result["artifact_id"] == 789 and result["run_id"] == 321 and result["run_attempt"] == 1
    assert result["source_sha"] == SOURCE and result["exact_root_and_original_bytes"] is True
    assert result["manifest_sha256"] == hashlib.sha256(pair["manifest.json"]).hexdigest()
    assert result["dump_sha256"] == hashlib.sha256(pair["schema.dump"]).hexdigest()


@pytest.mark.parametrize(
    "case",
    [
        "source",
        "attempt",
        "workflow",
        "request",
        "expired",
        "ambiguous",
        "artifact-run",
        "different-bytes",
        "extra-root",
        "incomplete-run",
    ],
)
def test_wrong_run_or_changed_download_cannot_return_receipt(readback_context, case):
    state, pair, values = readback_context
    if case == "source":
        values["run"]["head_sha"] = "d" * 40
    elif case == "attempt":
        values["run"]["run_attempt"] = 2
    elif case == "workflow":
        values["run"]["workflow_id"] = 999
    elif case == "request":
        values["artifact"]["name"] = values["artifact"]["name"].replace(REQUEST, "d" * 32)
    elif case == "expired":
        values["artifact"]["expired"] = True
    elif case == "ambiguous":
        values["listing"]["total_count"] = 2
        values["listing"]["artifacts"].append(copy.deepcopy(values["artifact"]))
    elif case == "artifact-run":
        values["artifact"]["workflow_run"]["id"] = 999
    elif case == "different-bytes":
        values["download"] = publisher.pack(fixture_pair(b"PGDMPdifferent"))
    elif case == "extra-root":
        values["download"] = archive([*pair.items(), ("extra", b"forbidden")])
    else:
        values["run"]["conclusion"] = "failure"
    with pytest.raises(publisher.PublicationError):
        publisher.read_back(state, pair, 321)


def test_logs_never_echo_payload(validation, tmp_path, monkeypatch, capsys):
    event_path = tmp_path / "event.json"
    event_path.write_bytes(b'{"payload":"fictional-sensitive-value"}')
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    assert publisher.main(["prepare-action", "--destination", str(tmp_path / "candidate")]) == 1
    output = capsys.readouterr()
    assert "fictional-sensitive-value" not in output.err + output.out
    assert "pointers unchanged" in output.err


def test_corrupt_deflate_failure_is_suppressed(validation, tmp_path, monkeypatch, capsys):
    path = tmp_path / "event.json"
    path.write_bytes(b"{}")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))

    def broken(*args):
        raise zlib.error("fictional-private-diagnostic")

    monkeypatch.setattr(publisher, "prepare", broken)
    assert publisher.main(["prepare-action", "--destination", str(tmp_path / "candidate")]) == 1
    assert "fictional-private-diagnostic" not in capsys.readouterr().err


def saved_request(tmp_path):
    inputs = dispatch_inputs()
    folder = tmp_path / REQUEST
    folder.mkdir(mode=0o700)
    publisher.private_write(
        folder / "dispatch.json", json.dumps({"ref": "main", "inputs": inputs}).encode()
    )
    publisher.private_write(folder / "payload.zip", payload(inputs))
    state = {k: inputs[k] for k in ["publisher_sha", "request_id", "mode", "manifest_sha256"]}
    state["operator_id"] = ACTOR["id"]
    publisher.private_write(folder / "state.json", json.dumps(state).encode())
    return inputs, folder


def test_blob_is_created_read_back_and_then_dispatched_once(validation, tmp_path, monkeypatch):
    inputs, folder = saved_request(tmp_path)
    monkeypatch.setattr(publisher, "fetch_blob", REAL_FETCH)
    monkeypatch.setattr(publisher, "preflight", lambda *a: ACTOR)
    monkeypatch.setattr(publisher, "assert_main", lambda *a: None)
    calls = []

    def fake_api(path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("/git/blobs"):
            assert kwargs["data"]["encoding"] == "base64"
            assert kwargs["seconds"] == publisher.MAX_TRANSFER_SECONDS
            return {"sha": inputs["payload_blob"]}
        if "/git/blobs/" in path:
            return payload(inputs)
        return None

    monkeypatch.setattr(publisher, "api", fake_api)
    publisher.dispatch_saved(REQUEST)
    assert [p.rsplit("/", 2)[-2:] for p, _ in calls] == [
        ["git", "blobs"],
        ["blobs", inputs["payload_blob"]],
        ["migration-schema-publish.yml", "dispatches"],
    ]
    assert calls[-1][1]["data"]["inputs"] == inputs
    assert (folder / "dispatch-attempted").exists()


@pytest.mark.parametrize("failure", ["identity", "bytes", "error"])
def test_blob_failure_prevents_dispatch_and_marker(validation, tmp_path, monkeypatch, failure):
    inputs, folder = saved_request(tmp_path)
    monkeypatch.setattr(publisher, "fetch_blob", REAL_FETCH)
    monkeypatch.setattr(publisher, "preflight", lambda *a: ACTOR)
    monkeypatch.setattr(publisher, "assert_main", lambda *a: None)
    calls = []

    def fake_api(path, **kwargs):
        calls.append(path)
        if failure == "error":
            raise publisher.PublicationError("fictional blob failure")
        if path.endswith("/git/blobs"):
            return {"sha": "e" * 40 if failure == "identity" else inputs["payload_blob"]}
        return payload(inputs) + b"x"

    monkeypatch.setattr(publisher, "api", fake_api)
    with pytest.raises(publisher.PublicationError):
        publisher.dispatch_saved(REQUEST)
    assert not any(path.endswith("/dispatches") for path in calls)
    assert not (folder / "dispatch-attempted").exists()


def test_dispatch_never_replays_ambiguous_failure(validation, tmp_path, monkeypatch):
    inputs, folder = saved_request(tmp_path)
    monkeypatch.setattr(publisher, "preflight", lambda *a: ACTOR)
    monkeypatch.setattr(publisher, "assert_main", lambda *a: None)
    monkeypatch.setattr(publisher, "publish_blob", lambda *a: None)
    calls = []

    def fail_api(path, *, data):
        calls.append((path, data))
        raise publisher.PublicationError("ambiguous failure")

    monkeypatch.setattr(publisher, "api", fail_api)
    with pytest.raises(publisher.PublicationError):
        publisher.dispatch_saved(REQUEST)
    with pytest.raises(FileExistsError):
        publisher.dispatch_saved(REQUEST)
    assert len(calls) == 1 and calls[0][1]["ref"] == "main"
    assert stat.S_IMODE((folder / "dispatch.json").stat().st_mode) == 0o600


def test_api_payload_on_stdin_not_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(
        publisher, "command", lambda argv, data, **kw: calls.append((argv, data, kw)) or b""
    )
    publisher.api(
        f"repos/{publisher.REPOSITORY}/actions/workflows/migration-schema-publish.yml/dispatches",
        data={"payload": "fictional-private-payload"},
    )
    argv, data, options = calls[0]
    assert "fictional-private-payload" not in " ".join(argv)
    assert argv[-2:] == ["--input", "-"] and b"fictional-private-payload" in data
    assert options == {"limit": 4 * 1024 * 1024, "seconds": 60}
    publisher.api(
        f"repos/{publisher.REPOSITORY}/git/blobs/{'a' * 40}",
        binary=True,
        accept=publisher.RAW_BLOB,
        seconds=publisher.MAX_TRANSFER_SECONDS,
    )
    argv, _, options = calls[1]
    assert argv[3:5] == ["--header", "Accept: " + publisher.RAW_BLOB]
    assert options == {"limit": publisher.MAX_ZIP, "seconds": publisher.MAX_TRANSFER_SECONDS}


def test_command_output_bounded_and_diagnostics_suppressed(validation):
    with pytest.raises(publisher.PublicationError, match="output exceeded"):
        publisher.command(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 5000000)"]
        )
    with pytest.raises(publisher.PublicationError):
        publisher.command(
            [sys.executable, "-c", "import sys; sys.stderr.write('fictional-private'); sys.exit(1)"]
        )


def test_workflow_no_payload_shell_interpolation_or_pointer_writes():
    source = (publisher.ROOT / publisher.WORKFLOW).read_text()
    assert "$" + "{{ inputs." not in source and "$" + "{{ github.event.inputs." not in source
    assert "retention-days: 1" in source and "overwrite: false" in source
    assert "cancel-in-progress: false" in source and "actions: read" in source
    assert "actions: write" not in source and "secrets." not in source
    assert "AC_MIGRATION_SCHEMA_ARTIFACT_ID" not in source
    assert "GITHUB_STEP_SUMMARY" in source
    assert "payload_blob:" in source and "payload_sha256:" in source
    assert "\n      payload:" not in source and "contents: read" in source


def test_real_schema_transport_and_full_backup_rejection(tmp_path, monkeypatch):
    if os.getenv("AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST") != "1":
        pytest.skip("real PostgreSQL transport proof runs in migration-safety CI")
    monkeypatch.setenv("PAPERCLIP_RUN_SCRATCH_DIR", str(tmp_path))
    with publisher.gate.disposable_postgres() as database:
        with database.connect() as connection:
            connection.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            connection.execute("CREATE TABLE fictional_publication (id integer PRIMARY KEY)")
            connection.execute("INSERT INTO fictional_publication VALUES (1)")
        schema = database.tool(
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
        full = database.tool(
            "pg_dump", "-U", "ac_owner", "-d", "ac_migration_safety", "--format=custom"
        )
    for data, forbidden in [(schema, False), (full, True)]:
        pair = fixture_pair(data)
        digest = hashlib.sha256(pair["manifest.json"]).hexdigest()
        downloaded = publisher.unpack(publisher.pack(pair))
        assert downloaded == pair
        if forbidden:
            with pytest.raises(publisher.gate.GateError, match="data or external"):
                publisher.validate_pair(downloaded, digest, BASELINE)
        else:
            publisher.validate_pair(downloaded, digest, BASELINE)
