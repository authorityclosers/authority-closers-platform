"""Migration 0133 (a seller's open-lead limit may be none; a column, no table) keeps the same
tables in every backup and restore path, under its own contract."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_rep_limit_head_has_its_contract_and_the_same_tables() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0133") == "ac-postgres-parity-v100"
        assert module.parity_tables_for_head("20261025_0133") == module.parity_tables_for_head(
            "20261025_0132"
        )
