"""Lead OS meetings (migration 0128, one table) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_meetings_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261024_0128") == "ac-postgres-parity-v95"
        assert module.parity_tables_for_head("20261024_0128") == (
            *module.parity_tables_for_head("20261023_0127"),
            "lead_desk_meetings",
        )
