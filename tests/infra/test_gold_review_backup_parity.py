"""Gold reviewer identity, assignment and every saved version survive restore."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_gold_history_is_required_by_all_backup_and_restore_consumers() -> None:
    tables = (
        "conversation_gold_reviewers",
        "conversation_gold_assignments",
        "conversation_gold_rows",
    )
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261016_0094") == "ac-postgres-parity-v61"
        assert module.parity_tables_for_head("20261016_0094") == (
            *module.parity_tables_for_head("20261016_0093"),
            *tables,
        )
