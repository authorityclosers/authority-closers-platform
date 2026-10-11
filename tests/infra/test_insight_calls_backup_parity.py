"""The company view's call projection (AUT-1798) survives every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_insight_calls_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0084") == "ac-postgres-parity-v55"
        assert module.parity_tables_for_head("20261011_0084") == (
            *module.parity_tables_for_head("20261011_0083"),
            "conversation_insight_calls",
        )
