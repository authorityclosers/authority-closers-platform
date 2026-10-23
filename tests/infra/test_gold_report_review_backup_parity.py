"""Gold report review (migration 0123: a check and one column) keeps every backup and
restore path aligned."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_gold_report_review_head_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261023_0123") == "ac-postgres-parity-v90"
        assert module.parity_tables_for_head("20261023_0123") == module.parity_tables_for_head(
            "20261022_0122"
        )
