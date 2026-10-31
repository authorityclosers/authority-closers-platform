"""Migration 0149 (the advanced bug reporter's files and who may use it: two tables) is in
every backup and restore path under its own contract, with 0147's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_advanced_reporters_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261031_0149") == "ac-postgres-parity-v115"
        assert module.parity_tables_for_head("20261031_0149") == module.parity_tables_for_head(
            "20261030_0147"
        ) + ("bug_report_files", "bug_reporter_access")
