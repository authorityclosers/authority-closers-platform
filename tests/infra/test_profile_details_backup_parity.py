"""Each member's details and own photo (migration 0135, two tables) are in every backup and
restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_person_photos_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0135") == "ac-postgres-parity-v102"
        assert module.parity_tables_for_head("20261025_0135") == (
            *module.parity_tables_for_head("20261025_0134"),
            "person_photos",
            "person_profile_details",
        )
