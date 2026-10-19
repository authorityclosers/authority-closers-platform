"""Developer platform tables (migration 0103, 19 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

INTEGRATION_TABLES = (
    "integration_api_keys",
    "integration_secrets",
    "integration_oauth_clients",
    "integration_oauth_grants",
    "integration_oauth_codes",
    "integration_oauth_tokens",
)


def test_integration_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0103") == "ac-postgres-parity-v70"
        assert module.parity_tables_for_head("20261019_0103") == (
            *module.parity_tables_for_head("20261019_0102"),
            *INTEGRATION_TABLES,
        )
