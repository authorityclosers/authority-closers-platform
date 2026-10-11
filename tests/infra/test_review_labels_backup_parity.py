"""Call review labels (AUT-1798) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_review_labels_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0083") == "ac-postgres-parity-v54"
        assert module.parity_tables_for_head("20261011_0083") == (
            *module.parity_tables_for_head("20261011_0082"),
            "conversation_review_labels",
        )
