"""The call-history index (migration 0122) keeps every backup and restore path's tables."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_call_submission_index_head_is_known_to_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261022_0122") == "ac-postgres-parity-v89"
        assert module.parity_tables_for_head("20261022_0122") == module.parity_tables_for_head(
            "20261022_0121"
        )
