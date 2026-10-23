"""Offer Studio versions (migration 0125, one table) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_offer_versions_table_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261023_0125") == "ac-postgres-parity-v92"
        assert module.parity_tables_for_head("20261023_0125") == (
            *module.parity_tables_for_head("20261023_0124"),
            "admin_offer_versions",
        )
