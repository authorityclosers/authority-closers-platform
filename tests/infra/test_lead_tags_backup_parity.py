"""Migration 0161 (lead tags: two tables) is in every backup and restore path under its own
contract, with 0160's tables and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_tag_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261117_0161") == "ac-postgres-parity-v127"
        assert module.parity_tables_for_head("20261117_0161") == module.parity_tables_for_head(
            "20261117_0160"
        ) + ("lead_desk_tags", "lead_desk_lead_tags")
