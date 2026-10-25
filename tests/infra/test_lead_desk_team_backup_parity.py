"""The team engine's targets and nudge ledger (migration 0130, two tables) are in every
backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_team_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0130") == "ac-postgres-parity-v97"
        assert module.parity_tables_for_head("20261025_0130") == (
            *module.parity_tables_for_head("20261024_0129"),
            "lead_desk_targets",
            "lead_desk_nudges",
        )
