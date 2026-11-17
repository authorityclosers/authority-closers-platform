"""Migration 0160 (the workspace's import memory: one table) is in every backup and restore
path under its own contract, with 0159's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_import_memory_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261117_0160") == "ac-postgres-parity-v126"
        assert module.parity_tables_for_head("20261117_0160") == module.parity_tables_for_head(
            "20261117_0159"
        ) + ("lead_desk_import_memory",)
