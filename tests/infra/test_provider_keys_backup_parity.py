"""Provider keys (migration 0114, a check constraint only) keep every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_provider_keys_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261020_0114") == "ac-postgres-parity-v81"
        assert module.parity_tables_for_head("20261020_0114") == module.parity_tables_for_head(
            "20261020_0113"
        )
