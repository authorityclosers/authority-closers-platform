"""Bug issues (migration 0138, three tables) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_bug_issues_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0138") == "ac-postgres-parity-v105"
        assert module.parity_tables_for_head("20261025_0138") == (
            *module.parity_tables_for_head("20261025_0137"),
            "bug_issues",
            "bug_issue_reports",
            "bug_issue_events",
        )
