"""Migration 0164 (the email on each linked sign-in account: a column, no table) is in every
backup and restore path under its own contract, with 0162's tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_provider_email_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261120_0164") == "ac-postgres-parity-v129"
        assert module.parity_tables_for_head("20261120_0164") == module.parity_tables_for_head(
            "20261117_0162"
        )
