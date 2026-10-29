"""Migration 0143 (plan price history, one table) is in every backup and restore path under
its own contract: 0142's tables plus plan_price_changes."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_plan_price_changes_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261029_0143") == "ac-postgres-parity-v110"
        assert module.parity_tables_for_head("20261029_0143") == (
            *module.parity_tables_for_head("20261027_0142"),
            "plan_price_changes",
        )
