"""Migration 0152 (saved reports: one append-only table) is in every backup and restore path
under its own contract, with 0151's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_report_saves_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261113_0152") == "ac-postgres-parity-v118"
        assert module.parity_tables_for_head("20261113_0152") == module.parity_tables_for_head(
            "20261113_0151"
        ) + ("conversation_report_saves",)
