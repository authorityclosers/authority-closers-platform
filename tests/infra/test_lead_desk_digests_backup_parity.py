"""Migration 0137 (the digest and sweep ledger) is in every backup and restore path under
its own contract."""

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill


def test_digest_ledger_is_in_all_consumers() -> None:
    for module in (backup, proof, drill):
        assert module.parity_contract_for_head("20261025_0137") == "ac-postgres-parity-v104"
        assert module.parity_tables_for_head("20261025_0137") == (
            *module.parity_tables_for_head("20261025_0136"),
            "lead_desk_digests",
        )
