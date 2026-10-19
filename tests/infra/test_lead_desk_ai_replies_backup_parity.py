"""AI replies to leads (migration 0109) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_ai_replies_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0109") == "ac-postgres-parity-v76"
        assert module.parity_tables_for_head("20261019_0109") == (
            *module.parity_tables_for_head("20261019_0108"),
            "lead_desk_ai_replies",
        )
