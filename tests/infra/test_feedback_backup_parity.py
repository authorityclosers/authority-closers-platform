"""Feedback answers and bug voice notes (migration 0127) are in every backup path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_feedback_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261023_0127") == "ac-postgres-parity-v94"
        assert module.parity_tables_for_head("20261023_0127") == (
            *module.parity_tables_for_head("20261023_0126"),
            "feedback_responses",
            "bug_report_attachments",
        )
