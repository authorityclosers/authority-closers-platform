"""Migration 0139 (when a lead reached the business, a column) is in every backup and restore
path under its own contract, with the same tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_lead_arrival_time_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0139") == "ac-postgres-parity-v106"
        assert module.parity_tables_for_head("20261025_0139") == module.parity_tables_for_head(
            "20261025_0138"
        )
