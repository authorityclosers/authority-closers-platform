"""Partner webhook tables (migration 0096, 18 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

PARTNER_WEBHOOK_TABLES = (
    "partner_webhook_endpoints",
    "partner_quote_facts",
    "partner_webhook_events",
    "partner_webhook_attempts",
)


def test_partner_webhook_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261018_0096") == "ac-postgres-parity-v63"
        assert module.parity_tables_for_head("20261018_0096") == (
            *module.parity_tables_for_head("20261017_0095"),
            *PARTNER_WEBHOOK_TABLES,
        )
