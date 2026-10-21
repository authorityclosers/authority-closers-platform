"""AI on calls (migration 0119, two tables) is in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_call_ai_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261021_0119") == "ac-postgres-parity-v86"
        assert module.parity_tables_for_head("20261021_0119") == (
            *module.parity_tables_for_head("20261021_0118"),
            "call_ai_settings",
            "call_ai_decisions",
        )


def test_call_ai_reason_head_keeps_the_same_tables() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261021_0120") == "ac-postgres-parity-v87"
        assert module.parity_tables_for_head("20261021_0120") == module.parity_tables_for_head(
            "20261021_0119"
        )
