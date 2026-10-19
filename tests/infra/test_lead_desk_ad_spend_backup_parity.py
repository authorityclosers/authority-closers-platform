"""Ad spend per Meta campaign (migration 0108) survives every backup and restore
path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_ad_spend_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0108") == "ac-postgres-parity-v75"
        assert module.parity_tables_for_head("20261019_0108") == (
            *module.parity_tables_for_head("20261019_0107"),
            "lead_desk_ad_spend_days",
        )
