"""AI spend caps (migration 0112) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_ai_spend_settings_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261020_0112") == "ac-postgres-parity-v79"
        assert module.parity_tables_for_head("20261020_0112") == (
            *module.parity_tables_for_head("20261020_0111"),
            "ai_spend_settings",
        )
