"""Migration 0162 (WhatsApp files, campaigns and who each reaches: four tables) is in every
backup and restore path under its own contract, with 0161's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_whatsapp_campaign_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261117_0162") == "ac-postgres-parity-v128"
        assert module.parity_tables_for_head("20261117_0162") == module.parity_tables_for_head(
            "20261117_0161"
        ) + (
            "lead_desk_whatsapp_media",
            "lead_desk_whatsapp_campaigns",
            "lead_desk_whatsapp_campaign_leads",
            "lead_desk_whatsapp_campaign_messages",
        )
