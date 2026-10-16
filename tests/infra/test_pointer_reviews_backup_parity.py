"""AI pointer reviews (owner decision 16 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_pointer_reviews_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261016_0091") == "ac-postgres-parity-v59"
        assert module.parity_tables_for_head("20261016_0091") == (
            *module.parity_tables_for_head("20261013_0090"),
            "conversation_pointer_reviews",
        )
        # 0092 only adds erasure columns: same counted tables, same contract.
        assert module.parity_contract_for_head("20261016_0092") == "ac-postgres-parity-v59"
        assert module.parity_tables_for_head("20261016_0092") == module.parity_tables_for_head(
            "20261016_0091"
        )
