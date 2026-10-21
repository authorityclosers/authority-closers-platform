"""Gold checkpoints (migration 0118, two columns) keep every backup and restore path aligned."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_gold_checkpoint_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261021_0118") == "ac-postgres-parity-v85"
        assert module.parity_tables_for_head("20261021_0118") == module.parity_tables_for_head(
            "20261021_0117"
        )
