"""Lead pipelines (migration 0121, one table) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_pipelines_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261022_0121") == "ac-postgres-parity-v88"
        assert module.parity_tables_for_head("20261022_0121") == (
            *module.parity_tables_for_head("20261021_0120"),
            "lead_desk_pipelines",
        )
