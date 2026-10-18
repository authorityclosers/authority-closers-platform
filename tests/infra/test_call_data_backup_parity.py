"""Call data engine tables (migration 0097, 19 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

CALL_DATA_TABLES = (
    "call_data_settings",
    "call_data_runs",
    "call_objects",
    "call_object_decisions",
)


def test_call_data_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0097") == "ac-postgres-parity-v64"
        assert module.parity_tables_for_head("20261019_0097") == (
            *module.parity_tables_for_head("20261018_0096"),
            *CALL_DATA_TABLES,
        )
