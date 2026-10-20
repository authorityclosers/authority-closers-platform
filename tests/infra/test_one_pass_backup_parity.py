"""The one-pass trial's tables (migration 0116) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_one_pass_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261021_0116") == "ac-postgres-parity-v83"
        assert module.parity_tables_for_head("20261021_0116") == (
            *module.parity_tables_for_head("20261020_0115"),
            "analysis_pipeline_settings",
            "one_pass_runs",
        )
