"""Person-entered call outcomes (AUT-1677) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_call_outcomes_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0087") == "ac-postgres-parity-v58"
        assert module.parity_tables_for_head("20261011_0087") == (
            *module.parity_tables_for_head("20261011_0086"),
            "conversation_call_outcome_revisions",
        )
