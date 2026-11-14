"""Migration 0153 (Ask Dipak's saved lessons and missions: one append-only table) is in every
backup and restore path under its own contract, with 0152's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

DOWN = "20261113_0152"


def test_the_ask_dipak_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261114_0153") == "ac-postgres-parity-v119"
        assert module.parity_tables_for_head("20261114_0153") == module.parity_tables_for_head(
            DOWN
        ) + ("sales_xray_ask_dipak_events",)
