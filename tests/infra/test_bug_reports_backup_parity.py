"""Bug reports and their history (migration 0124) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_bug_report_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261023_0124") == "ac-postgres-parity-v91"
        assert module.parity_tables_for_head("20261023_0124") == (
            *module.parity_tables_for_head("20261023_0123"),
            "bug_reports",
            "bug_report_events",
        )
