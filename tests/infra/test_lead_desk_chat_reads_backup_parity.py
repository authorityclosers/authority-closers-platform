"""Chats read marks (migration 0113) survive every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_chat_read_marks_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261020_0113") == "ac-postgres-parity-v80"
        assert module.parity_tables_for_head("20261020_0113") == (
            *module.parity_tables_for_head("20261020_0112"),
            "lead_desk_chat_reads",
        )
