"""Migration 0134 (duplicate leads: pairs, decisions, merges) is in every backup and restore
path under its own contract."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_duplicate_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0134") == "ac-postgres-parity-v101"
        assert module.parity_tables_for_head("20261025_0134") == (
            *module.parity_tables_for_head("20261025_0133"),
            "lead_desk_duplicate_pairs",
            "lead_desk_duplicate_decisions",
            "lead_desk_merges",
        )
