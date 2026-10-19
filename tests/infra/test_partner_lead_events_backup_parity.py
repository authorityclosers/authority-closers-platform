"""Partner lead event tables (migration 0102) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_partner_lead_events_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0102") == "ac-postgres-parity-v69"
        assert tuple(module.parity_tables_for_head("20261019_0102")) == tuple(
            module.parity_tables_for_head("20261019_0101")
        ) + ("partner_handover_recipients", "partner_lead_events", "partner_lead_attempts")
