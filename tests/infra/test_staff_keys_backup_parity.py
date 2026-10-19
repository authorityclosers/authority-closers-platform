"""Staff keys (migration 0106) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_staff_keys_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0106") == "ac-postgres-parity-v73"
        assert module.parity_tables_for_head("20261019_0106") == (
            *module.parity_tables_for_head("20261019_0105"),
            "admin_staff_keys",
        )
