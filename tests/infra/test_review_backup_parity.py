"""Review 2.0 tables (migration 0101) are in every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_review_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261019_0101") == "ac-postgres-parity-v68"
        assert tuple(module.parity_tables_for_head("20261019_0101")) == tuple(
            module.parity_tables_for_head("20261019_0100")
        ) + ("review_pipelines", "review_verdicts")
