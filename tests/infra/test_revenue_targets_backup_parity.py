"""Migration 0150 (what Won leads were worth and monthly revenue targets: two tables) is in
every backup and restore path under its own contract, with 0149's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_revenue_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261031_0150") == "ac-postgres-parity-v116"
        assert module.parity_tables_for_head("20261031_0150") == module.parity_tables_for_head(
            "20261031_0149"
        ) + ("lead_desk_deal_amounts", "lead_desk_revenue_targets")
