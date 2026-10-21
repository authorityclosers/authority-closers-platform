"""Brain 4.0's shadow reads (migration 0117) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_brain4_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261021_0117") == "ac-postgres-parity-v84"
        assert module.parity_tables_for_head("20261021_0117") == (
            *module.parity_tables_for_head("20261021_0116"),
            "conversation_brain4_reviews",
        )
