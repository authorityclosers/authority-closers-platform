"""Migration 0156 (the app-change ledger records assigns: a check constraint, no table changes)
is in every backup and restore path under its own contract, with 0155's tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_assign_head_keeps_the_coaching_tables_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261115_0156") == "ac-postgres-parity-v122"
        assert module.parity_tables_for_head("20261115_0156") == module.parity_tables_for_head(
            "20261115_0155"
        )
