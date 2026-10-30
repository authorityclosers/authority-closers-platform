"""Migration 0147 (a task may have no lead: a column change, no new table) is in every
backup and restore path under its own contract, with 0146's tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_tasks_of_your_own_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261030_0147") == "ac-postgres-parity-v114"
        assert module.parity_tables_for_head("20261030_0147") == module.parity_tables_for_head(
            "20261030_0146"
        )
