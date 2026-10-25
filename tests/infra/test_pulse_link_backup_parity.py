"""Pulse (migration 0139: profiles from Pulse, organisation links and their directory,
recordings apps send for a person) survives every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

PREVIOUS, CONTRACT = "20261025_0137", "ac-postgres-parity-v105"


def test_pulse_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261026_0139") == CONTRACT
        assert module.parity_tables_for_head("20261026_0139") == (
            *module.parity_tables_for_head(PREVIOUS),
            "person_pulse_profiles",
            "pulse_org_links",
            "pulse_org_members",
            "app_call_uploads",
        )
