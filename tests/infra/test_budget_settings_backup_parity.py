"""Budget settings table (migration 0099, 19 Oct 2026) survives every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_budget_settings_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0099") == "ac-postgres-parity-v66"
        assert module.parity_tables_for_head("20261019_0099") == (
            *module.parity_tables_for_head("20261019_0098"),
            "conversation_budget_settings",
        )
