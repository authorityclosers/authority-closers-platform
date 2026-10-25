"""The AI-write ledger (migration 0131, one table) is in every backup and restore path, and
0132 (a check, no table) keeps the same tables under its own contract."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_ai_write_ledger_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0131") == "ac-postgres-parity-v98"
        assert module.parity_tables_for_head("20261025_0131") == (
            *module.parity_tables_for_head("20261025_0130"),
            "integration_writes",
        )
        assert module.parity_contract_for_head("20261025_0132") == "ac-postgres-parity-v99"
        assert module.parity_tables_for_head("20261025_0132") == module.parity_tables_for_head(
            "20261025_0131"
        )
