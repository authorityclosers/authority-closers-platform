"""Migration 0144 (complimentary seat grants, one table) is in every backup and restore path
under its own contract: 0143's tables plus organisation_seat_grants."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_organisation_seat_grants_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261030_0144") == "ac-postgres-parity-v111"
        assert module.parity_tables_for_head("20261030_0144") == (
            *module.parity_tables_for_head("20261029_0143"),
            "organisation_seat_grants",
        )
