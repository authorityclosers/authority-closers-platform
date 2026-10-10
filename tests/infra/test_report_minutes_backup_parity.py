"""Report minute history belongs in every backup/restore parity inventory."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_report_minute_journal_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261010_0079") == "ac-postgres-parity-v50"
        assert module.parity_tables_for_head("20261010_0079") == (
            *module.parity_tables_for_head("20261008_0078"),
            "conversation_report_minute_events",
        )
