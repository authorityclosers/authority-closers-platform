"""The work-memory engine's tasks and reminder ledger (migration 0129, two tables) are in
every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_task_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261024_0129") == "ac-postgres-parity-v96"
        assert module.parity_tables_for_head("20261024_0129") == (
            *module.parity_tables_for_head("20261024_0128"),
            "lead_desk_tasks",
            "lead_desk_task_reminders",
        )
