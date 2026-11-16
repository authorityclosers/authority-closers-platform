"""Migration 0157 (Ask Dipak's imported lessons: one append-only table) is in every backup and
restore path under its own contract, with 0156's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_ask_dipak_library_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261116_0157") == "ac-postgres-parity-v123"
        assert module.parity_tables_for_head("20261116_0157") == module.parity_tables_for_head(
            "20261115_0156"
        ) + ("sales_xray_ask_dipak_library_versions",)
