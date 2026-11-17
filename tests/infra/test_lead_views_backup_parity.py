"""Migration 0159 (saved views on Leads: one table) is in every backup and restore path under
its own contract, with 0158's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_saved_views_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261117_0159") == "ac-postgres-parity-v125"
        assert module.parity_tables_for_head("20261117_0159") == module.parity_tables_for_head(
            "20261117_0158"
        ) + ("lead_desk_saved_views",)
