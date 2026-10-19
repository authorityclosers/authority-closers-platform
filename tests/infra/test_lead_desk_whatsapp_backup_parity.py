"""WhatsApp in the CRM and the first-response SLA (migration 0105) survive every
backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

TABLES = (
    "lead_desk_whatsapp_numbers",
    "lead_desk_whatsapp_messages",
    "lead_desk_whatsapp_templates",
    "lead_desk_sla_breaches",
)


def test_whatsapp_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0105") == "ac-postgres-parity-v72"
        assert module.parity_tables_for_head("20261019_0105") == (
            *module.parity_tables_for_head("20261019_0104"),
            *TABLES,
        )
