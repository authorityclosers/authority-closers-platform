"""Username identity columns retain the complete reviewed recovery inventory."""

import pytest

from ac_platform.db.models import model_metadata
from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

HEAD = "20261010_0081"
PREVIOUS = "20261010_0080"


@pytest.mark.parametrize("module", (backup, proof, drill), ids=("backup", "proof", "drill"))
def test_username_head_preserves_complete_reviewed_inventory(module) -> None:
    tables = module.parity_tables_for_head(HEAD)
    assert module.parity_contract_for_head(HEAD) == "ac-postgres-parity-v51"
    assert tables == module.parity_tables_for_head(PREVIOUS)
    assert len(tables) == len(set(tables)) == 139
    # The existing row-count contract is narrower than the full schema dump.
    # Every governed domain table must still exist in the canonical registry;
    # Alembic owns its own version table separately from SQLAlchemy metadata.
    assert set(tables) - {"alembic_version"} <= set(model_metadata().tables)


@pytest.mark.parametrize(
    ("module", "error"),
    ((backup, backup.BackupError), (proof, proof.RestoreProofError), (drill, drill.DrillError)),
    ids=("backup", "proof", "drill"),
)
def test_username_mapping_does_not_admit_unknown_heads(module, error) -> None:
    with pytest.raises(error, match="no reviewed row-count parity contract"):
        module.parity_tables_for_head("20261010_unknown")
