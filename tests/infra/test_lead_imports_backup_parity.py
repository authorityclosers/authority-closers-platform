"""Migration 0154 (lead imports through the API: two tables) is in every backup and
restore path under its own contract, with the head before it and its own."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_lead_import_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261115_0154") == "ac-postgres-parity-v120"
        assert module.parity_tables_for_head("20261115_0154") == module.parity_tables_for_head(
            "20261114_0153"
        ) + ("integration_lead_imports", "integration_lead_import_chunks")
