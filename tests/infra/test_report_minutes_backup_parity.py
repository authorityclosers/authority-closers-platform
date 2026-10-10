"""Report minute history belongs in every backup/restore parity inventory."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_report_minute_journal_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261010_0080") == "ac-postgres-parity-v51"
        assert module.parity_tables_for_head("20261010_0080") == (
            *module.parity_tables_for_head("20261009_0079"),
            "conversation_report_minute_events",
        )
