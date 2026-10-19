"""Capture-source CHECK (migration 0100) keeps every backup and restore path on parity."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_capture_source_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0100") == "ac-postgres-parity-v67"
        # Only a CHECK changed: the table list is 0099's.
        assert module.parity_tables_for_head("20261019_0100") == module.parity_tables_for_head(
            "20261019_0099"
        )
