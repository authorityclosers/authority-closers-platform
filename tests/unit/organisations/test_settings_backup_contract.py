"""Keep historical backup contracts and the column-only settings head portable."""

import importlib.util
from pathlib import Path

import pytest

from ac_platform.db.models import model_metadata
from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof, restore_drill_contract


def test_settings_head_preserves_inventory_in_all_three_backup_consumers():
    for helper in (backup, proof, restore_drill_contract):
        previous = helper.parity_tables_for_head("20261004_0075")
        current = helper.parity_tables_for_head("20261005_0076")
        assert current == previous
        assert len(current) == len(set(current)) == 133
        assert "organisations" in current
        assert helper.parity_contract_for_head("20261004_0075") == "ac-postgres-parity-v46"
        assert helper.parity_contract_for_head("20261005_0076") == "ac-postgres-parity-v47"
        assert "organisations" in model_metadata().tables


def test_settings_migration_is_forward_only():
    root = Path(__file__).resolve().parents[3]
    path = root / "db/migrations/versions/20261005_0076_organisation_settings.py"
    spec = importlib.util.spec_from_file_location("organisation_settings_0076", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "20261004_0075"
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
