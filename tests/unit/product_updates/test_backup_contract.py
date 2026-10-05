"""Portable proof that the three packaged inventories include the new model tables."""

from ac_platform.db.models import model_metadata
from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof, restore_drill_contract


def test_product_update_contract_preserves_the_prior_head_and_adds_the_three_models() -> None:
    for helper in (backup, proof, restore_drill_contract):
        previous = helper.parity_tables_for_head("20261004_0074")
        current = helper.parity_tables_for_head("20261004_0075")
        assert len(previous) == 130
        assert current == previous + ("product_updates", "update_seen", "notifications")
        assert len(current) == len(set(current)) == 133
        assert {"product_updates", "update_seen", "notifications"} <= set(model_metadata().tables)
        assert helper.parity_contract_for_head("20261004_0074") == "ac-postgres-parity-v45"
        assert helper.parity_contract_for_head("20261004_0075") == "ac-postgres-parity-v46"
