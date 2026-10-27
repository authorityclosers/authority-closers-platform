"""Google connections (migration 0141: an organisation's Google connection for Sheets and
Drive, and the rows its Sheet copy has written) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

PREVIOUS, CONTRACT = "20261026_0140", "ac-postgres-parity-v108"


def test_google_connection_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261027_0141") == CONTRACT
        assert module.parity_tables_for_head("20261027_0141") == (
            *module.parity_tables_for_head(PREVIOUS),
            "lead_desk_google_connections",
            "lead_desk_sheet_rows",
        )
