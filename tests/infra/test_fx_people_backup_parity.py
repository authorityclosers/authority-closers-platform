"""Daily rates and the usage pseudonym key (migration 0115) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_rates_and_pseudonym_key_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261020_0115") == "ac-postgres-parity-v82"
        assert module.parity_tables_for_head("20261020_0115") == (
            *module.parity_tables_for_head("20261020_0114"),
            "fx_reference_rates",
            "metrics_pseudonym_keys",
        )
