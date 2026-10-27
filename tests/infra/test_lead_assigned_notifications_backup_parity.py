"""Migration 0142 (the bell's "lead assigned" kind, a check) is in every backup and restore
path under its own contract, with the same tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_lead_assigned_kind_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261027_0142") == "ac-postgres-parity-v109"
        assert module.parity_tables_for_head("20261027_0142") == module.parity_tables_for_head(
            "20261027_0141"
        )
