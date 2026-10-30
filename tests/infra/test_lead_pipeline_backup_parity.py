"""Migration 0146 (live or cold on every lead, a column) is in every backup and restore path
under its own contract, with the same tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_lead_pipeline_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261030_0146") == "ac-postgres-parity-v113"
        assert module.parity_tables_for_head("20261030_0146") == module.parity_tables_for_head(
            "20261030_0145"
        )
