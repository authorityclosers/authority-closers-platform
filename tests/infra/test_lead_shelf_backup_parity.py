"""Migration 0158 (Archive and Bin for leads: four nullable columns and an index, no table
changes) is in every backup and restore path under its own contract, with 0157's tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_lead_shelf_head_keeps_the_library_tables_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261117_0158") == "ac-postgres-parity-v124"
        assert module.parity_tables_for_head("20261117_0158") == module.parity_tables_for_head(
            "20261116_0157"
        )
