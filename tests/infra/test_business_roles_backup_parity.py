"""Business roles (migration 0136, no new table) keep every backup and restore path's
tables, under contract v103."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_business_roles_keep_the_tables_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0136") == "ac-postgres-parity-v103"
        assert module.parity_tables_for_head("20261025_0136") == module.parity_tables_for_head(
            "20261025_0135"
        )
