"""Migration 0166 (the outreach log: senders, touches, replies and overrides) is in every
backup and restore path under its own contract (v131), with 0165's tables and its own; 0165
keeps v130."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_the_outreach_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261123_0166") == "ac-postgres-parity-v131"
        assert module.parity_tables_for_head("20261123_0166") == module.parity_tables_for_head(
            "20261122_0165"
        ) + (
            "lead_desk_outreach_senders",
            "lead_desk_touches",
            "lead_desk_touch_replies",
            "lead_desk_touch_overrides",
        )
        assert module.parity_contract_for_head("20261122_0165") == "ac-postgres-parity-v130"
