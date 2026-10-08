"""Prospect backup catalogue and fail-closed row-count checks without root access."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.infra.test_capability_backup_parity import _target
from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

HEAD = "20261007_0077"
PREVIOUS = "20261005_0076"
TABLES = ("conversation_prospects", "conversation_prospect_memberships")


def test_all_backup_consumers_cover_exact_prospect_migration() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head(HEAD) == "ac-postgres-parity-v48"
        tables = module.parity_tables_for_head(HEAD)
        assert tables == module.parity_tables_for_head(PREVIOUS)
        assert len(tables) == len(set(tables)) == 133
        assert module.parity_contract_for_head(PREVIOUS) == "ac-postgres-parity-v47"

        for head, mapping in module.VERSIONED_PARITY_CONTRACTS.items():
            assert module.parity_contract_for_head(head) == mapping[0]
            assert module.parity_tables_for_head(head) == mapping[1]
        error = (
            module.BackupError
            if module is backup
            else module.RestoreProofError
            if module is proof
            else module.DrillError
        )
        with pytest.raises(error):
            module.parity_contract_for_head("20261007_unknown")


@pytest.mark.parametrize("missing", TABLES)
def test_source_capture_rejects_missing_prospect_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    counts = {table: 1 for table in backup.parity_tables_for_head(HEAD) if table != missing}
    rows = [f"__migration_head__|{HEAD}"] + [f"{table}|{count}" for table, count in counts.items()]
    monkeypatch.setattr(
        backup, "run_checked", lambda *_a, **_kw: SimpleNamespace(stdout="\n".join(rows))
    )
    with pytest.raises(backup.BackupError, match="incomplete"):
        backup.source_row_counts(_target(tmp_path, HEAD), "00000003-0000001B-1")


@pytest.mark.parametrize("mode", [*TABLES, "wrong_count", "extra_table", "wrong_head", "complete"])
def test_populated_restore_parity_requires_exact_prospect_history(
    tmp_path: Path, mode: str
) -> None:
    expected = {table: 1 for table in proof.parity_tables_for_head(HEAD)}
    actual = expected.copy()
    if mode in TABLES:
        actual.pop(mode)
    elif mode == "wrong_count":
        actual[TABLES[1]] = 0
    elif mode == "extra_table":
        actual["unexpected_table"] = 0
    evidence = tmp_path / "restore.json"
    evidence.write_text(
        json.dumps(
            {
                "row_counts": actual,
                "schema": {
                    "expected_migration_head": HEAD,
                    "actual_migration_versions": [PREVIOUS if mode == "wrong_head" else HEAD],
                    "canonical_tables_checked": len(expected),
                },
                "parity_contract": "ac-postgres-parity-v48",
            }
        ),
        encoding="utf-8",
    )
    if mode == "complete":
        proof._verify_row_count_parity(evidence, expected, expected_migration_head=HEAD)
    else:
        with pytest.raises(proof.RestoreProofError):
            proof._verify_row_count_parity(evidence, expected, expected_migration_head=HEAD)
