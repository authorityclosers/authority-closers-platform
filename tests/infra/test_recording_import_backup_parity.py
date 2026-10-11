"""Batch decisions and normal usage bindings survive every backup/restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_recording_import_state_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0081") == "ac-postgres-parity-v52"
        assert module.parity_tables_for_head("20261011_0081") == (
            *module.parity_tables_for_head("20261010_0080"),
            "conversation_recording_imports",
            "conversation_recording_import_items",
        )
