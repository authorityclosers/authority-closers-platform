"""Migration 0155 (Ask Dipak's coaching loop: two append-only tables) is in every backup and
restore path under its own contract, with 0154's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_coaching_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261115_0155") == "ac-postgres-parity-v121"
        assert module.parity_tables_for_head("20261115_0155") == module.parity_tables_for_head(
            "20261115_0154"
        ) + ("sales_xray_ask_dipak_focus_events", "sales_xray_ask_dipak_call_checks")
