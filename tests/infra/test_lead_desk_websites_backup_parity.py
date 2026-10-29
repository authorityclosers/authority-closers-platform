"""Migration 0145 (websites and their pages' counters, two tables) is in every backup and
restore path under its own contract: 0144's tables plus lead_desk_sites and
lead_desk_site_pages."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_website_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261030_0145") == "ac-postgres-parity-v112"
        assert module.parity_tables_for_head("20261030_0145") == (
            *module.parity_tables_for_head("20261030_0144"),
            "lead_desk_sites",
            "lead_desk_site_pages",
        )
