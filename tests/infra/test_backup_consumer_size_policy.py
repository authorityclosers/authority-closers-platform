"""Fictional sparse dumps exercise both actual restore input contracts."""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.infra.test_postgres_restore_proof import (
    MIGRATION_HEAD_FIXTURE,
    ROOT,
    _write_pair,
    proof,
)
from tests.infra.test_postgres_restore_proof import (
    restore_drill_contract as drill,
)


@pytest.mark.parametrize("size", [9 * 1024 * 1024, 64 * 1024 * 1024, 64 * 1024 * 1024 + 1])
def test_shared_restore_consumers_keep_the_existing_64_mib_policy(tmp_path, monkeypatch, size):
    monkeypatch.setattr(proof, "_owner_is_root", lambda p: True)
    dump, metadata = _write_pair(tmp_path)
    with dump.open("r+b") as stream:
        stream.truncate(size)
    payload = json.loads(metadata.read_text())
    payload["dump_bytes"] = size
    payload["dump_sha256"] = hashlib.sha256(dump.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(payload))
    assert proof.MAX_DUMP_BYTES == drill.MAX_BACKUP_BYTES == 67_108_864
    if size > 67_108_864:
        with pytest.raises(proof.RestoreProofError, match="size or digest"):
            proof._validate_metadata(
                metadata, dump, "staging", expected_migration_head=MIGRATION_HEAD_FIXTURE
            )
        with pytest.raises(drill.DrillError):
            drill._validate_backup(str(dump), workspace_root=ROOT)
        with pytest.raises(drill.DrillError):
            drill._read_stable_source(dump, max_bytes=drill.MAX_BACKUP_BYTES)
        return
    proof._validate_metadata(
        metadata, dump, "staging", expected_migration_head=MIGRATION_HEAD_FIXTURE
    )
    assert drill._validate_backup(str(dump), workspace_root=ROOT) == dump.resolve()
    drill_metadata = dump.with_suffix(".json")
    metadata.rename(drill_metadata)
    drill._validate_backup_metadata(
        str(drill_metadata),
        backup=dump,
        environment="staging",
        workspace_root=ROOT,
        expected_migration_head=MIGRATION_HEAD_FIXTURE,
    )
    with dump.open("r+b") as stream:
        stream.seek(size - 1)
        stream.write(b"X")
    with pytest.raises(proof.RestoreProofError, match="size or digest"):
        proof._validate_metadata(
            drill_metadata, dump, "staging", expected_migration_head=MIGRATION_HEAD_FIXTURE
        )
    with pytest.raises(drill.DrillError, match="size or digest"):
        drill._validate_backup_metadata(
            str(drill_metadata),
            backup=dump,
            environment="staging",
            workspace_root=ROOT,
            expected_migration_head=MIGRATION_HEAD_FIXTURE,
        )
