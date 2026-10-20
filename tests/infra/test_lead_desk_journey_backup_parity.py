"""Lead stages per business and the ad-platform outbox (migration 0111) survive
every backup and restore path."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

TABLES = (
    "lead_desk_journey_versions",
    "lead_desk_conversions",
    "lead_desk_conversion_attempts",
)


def test_journey_tables_are_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261020_0111") == "ac-postgres-parity-v78"
        assert module.parity_tables_for_head("20261020_0111") == (
            *module.parity_tables_for_head("20261019_0110"),
            *TABLES,
        )
