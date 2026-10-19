"""The CRM's lead stages sent back to Meta (migration 0104) survive every backup and
restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

TABLES = ("lead_desk_meta_conversions", "lead_desk_meta_conversion_attempts")


def test_meta_conversion_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0104") == "ac-postgres-parity-v71"
        assert module.parity_tables_for_head("20261019_0104") == (
            *module.parity_tables_for_head("20261019_0103"),
            *TABLES,
        )
        assert module.parity_contract_for_head("20261019_0103") == "ac-postgres-parity-v70"
