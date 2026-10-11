from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "postgres_schema_export", ROOT / "scripts/ops/export_migration_schema.py"
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = exporter
SPEC.loader.exec_module(exporter)


@pytest.fixture
def target(tmp_path):
    return exporter.backup.ApplicationTarget(
        environment="staging",
        current_link=tmp_path / "current-staging",
        release_dir=tmp_path / ("a" * 40),
        profile_file=tmp_path / "staging.env",
        images_file=tmp_path / "images.env",
        state_root=tmp_path / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106
        migration_head="20261010_0001",
    )


def test_schema_command_retains_backup_transport_but_never_exports_rows(target):
    snapshot = "00000003-0000001B-1"
    original = exporter.backup.dump_command(target, snapshot)
    schema = exporter.schema_dump_command(target, snapshot)
    assert schema[:-1] == original[:-1]
    assert "--schema-only --no-owner --no-acl --lock-wait-timeout=2s" in schema[-1]
    assert "--create" not in schema[-1]
    assert f"--snapshot={snapshot}" in schema[-1]
    assert original == exporter.backup.dump_command(target, snapshot)
    assert "--schema-only" not in original[-1]
    assert "$AC_DB_BACKUP_PASSWORD" in schema[-1]


def test_production_and_invalid_snapshot_are_rejected(target):
    from dataclasses import replace

    with pytest.raises(exporter.backup.BackupError, match="only.*staging"):
        exporter.schema_dump_command(replace(target, environment="production"), "unused")
    with pytest.raises(exporter.backup.BackupError, match="snapshot identity"):
        exporter.schema_dump_command(target, "invalid;sql")


@pytest.mark.parametrize("result", ["180000|older", "180000|20261010_0001\n180000|20261010_0002"])
def test_snapshot_metadata_requires_one_exact_release_revision(target, monkeypatch, result):
    monkeypatch.setattr(
        exporter.backup, "run_checked", lambda *a, **kw: SimpleNamespace(stdout=result)
    )
    with pytest.raises(exporter.backup.BackupError, match="snapshot|release"):
        exporter.snapshot_metadata(target, "00000003-0000001B-1")


@pytest.mark.parametrize("data", [b"PGDMPschema", b"", b"over-size"])
def test_export_manifest_is_bound_to_snapshot_and_failures_remove_partial_pair(
    target, tmp_path, monkeypatch, data
):
    states = []
    holder = SimpleNamespace(
        snapshot_id="00000003-0000001B-1",
        assert_alive=lambda: states.append("alive"),
        close=lambda: states.append("closed"),
    )
    process = SimpleNamespace(stdout=io.BytesIO(data), poll=lambda: 0, wait=lambda **kw: 0)
    monkeypatch.setattr(exporter.backup, "start_exported_snapshot_holder", lambda _: holder)
    monkeypatch.setattr(exporter, "snapshot_metadata", lambda *_: (180000, target.migration_head))
    monkeypatch.setattr(exporter.subprocess, "Popen", lambda *a, **kw: process)
    if data == b"over-size":
        monkeypatch.setattr(exporter, "MAX_BYTES", 1)
    directory = tmp_path / "export"
    if data == b"PGDMPschema":
        metadata = exporter.export_schema(target, directory)
        assert metadata["dump_sha256"] == hashlib.sha256(data).hexdigest()
        assert metadata["schema_only"] is True and metadata["environment"] == "staging"
        assert metadata["alembic_revision"] == target.migration_head
        assert metadata["postgres_version_num"] == 180000
        assert metadata["release_id"] == "a" * 40
        assert json.loads((directory / "manifest.json").read_text()) == metadata
    else:
        with pytest.raises(exporter.backup.BackupError):
            exporter.export_schema(target, directory)
        assert not directory.exists()
    assert "closed" in states
