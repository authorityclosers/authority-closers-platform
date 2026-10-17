"""Lead Desk tables (owner order 16 Oct 2026) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

LEAD_DESK_TABLES = (
    "lead_desk_leads",
    "lead_desk_events",
    "lead_desk_reps",
    "lead_desk_sources",
    "lead_desk_settings",
)


def test_lead_desk_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261016_0093") == "ac-postgres-parity-v60"
        assert module.parity_tables_for_head("20261016_0093") == (
            *module.parity_tables_for_head("20261016_0092"),
            *LEAD_DESK_TABLES,
        )


def test_lead_desk_phones_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261017_0095") == "ac-postgres-parity-v62"
        assert module.parity_tables_for_head("20261017_0095") == (
            *module.parity_tables_for_head("20261016_0094"),
            "lead_desk_devices",
        )
