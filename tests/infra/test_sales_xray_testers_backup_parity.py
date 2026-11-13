"""Migration 0151 (the Sales X-Ray tester list: one append-only table) is in every backup and
restore path under its own contract, with 0150's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_tester_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261113_0151") == "ac-postgres-parity-v117"
        assert module.parity_tables_for_head("20261113_0151") == module.parity_tables_for_head(
            "20261031_0150"
        ) + ("sales_xray_tester_events",)
