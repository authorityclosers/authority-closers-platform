"""Report settings tables (migration 0098, 19 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

REPORT_SETTINGS_TABLES = (
    "conversation_report_settings_versions",
    "conversation_report_settings_events",
)


def test_report_settings_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0098") == "ac-postgres-parity-v65"
        assert module.parity_tables_for_head("20261019_0098") == (
            *module.parity_tables_for_head("20261019_0097"),
            *REPORT_SETTINGS_TABLES,
        )
