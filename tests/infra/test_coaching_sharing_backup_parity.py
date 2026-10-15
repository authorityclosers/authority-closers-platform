"""Coaching share revisions and feedback survive every backup/restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_coaching_sharing_state_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0085") == "ac-postgres-parity-v56"
        assert module.parity_tables_for_head("20261011_0085") == (
            *module.parity_tables_for_head("20261011_0084"),
            "coaching_share_revisions",
            "coaching_feedback",
        )


def test_coaching_learner_context_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261011_0086") == "ac-postgres-parity-v57"
        assert module.parity_tables_for_head("20261011_0086") == (
            *module.parity_tables_for_head("20261011_0085"),
            "coaching_learner_context",
        )
