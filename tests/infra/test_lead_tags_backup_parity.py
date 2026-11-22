"""Migration 0165 (tags on leads: two tables) is in every backup and restore path under its own
contract (v130), with 0164's tables and its own; 0164 keeps v129."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_lead_tags_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261122_0165") == "ac-postgres-parity-v130"
        assert module.parity_tables_for_head("20261122_0165") == module.parity_tables_for_head(
            "20261120_0164"
        ) + ("lead_desk_tags", "lead_desk_lead_tags")
        assert module.parity_contract_for_head("20261120_0164") == "ac-postgres-parity-v129"
