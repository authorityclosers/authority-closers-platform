"""Messenger and Instagram conversations (migration 0107) survive every backup and
restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

TABLES = ("lead_desk_social_accounts", "lead_desk_social_messages")


def test_social_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0107") == "ac-postgres-parity-v74"
        assert module.parity_tables_for_head("20261019_0107") == (
            *module.parity_tables_for_head("20261019_0106"),
            *TABLES,
        )
