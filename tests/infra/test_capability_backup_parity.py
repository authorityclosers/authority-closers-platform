"""Version-bound backup parity: old0018/39 and capability0019/41 stay distinct."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import _schema_evidence, _write_pair, proof
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

pytestmark = pytest.mark.skipif(
    os.name != "nt" and os.geteuid() != 0,
    reason="root-owned metadata validation runs in the root control-plane gate",
)
LEGACY = "20260904_0018"
CAPABILITIES = "20260907_0019"


def _target(root: Path, head: str):
    return backup.ApplicationTarget(
        environment="staging",
        current_link=root / "current-staging",
        release_dir=root / ("a" * 40),
        profile_file=root / "staging.env",
        images_file=root / "release-images.env",
        state_root=root / "state",
        compose_project="ac-application-staging",
        secret_environment="staging",  # noqa: S106 - environment name, not a credential
        migration_head=head,
    )


def _metadata(root: Path, head: str) -> tuple[Path, Path, dict]:
    dump, original = _write_pair(root)
    payload = json.loads(original.read_text(encoding="utf-8"))
    payload["row_counts"] = {table: 0 for table in backup.parity_tables_for_head(head)}
    payload.update(backup.parity_metadata_fields(head))
    if head == CAPABILITIES:
        payload["row_counts"].update(capability_grants=3, capability_revocations=1)
    paired = dump.with_suffix(".json")
    paired.write_text(json.dumps(payload), encoding="utf-8")
    return dump, paired, payload


def _validate_both(dump: Path, metadata: Path, head: str) -> None:
    proof._validate_metadata(metadata, dump, "staging", expected_migration_head=head)
    drill._validate_backup_metadata(
        str(metadata),
        backup=dump,
        environment="staging",
        workspace_root=Path(__file__).parents[2],
        expected_migration_head=head,
    )


def test_three_separately_packaged_helpers_have_identical_versioned_contracts() -> None:
    assert len(backup.PARITY_TABLES) == 39
    assert backup.PARITY_TABLES == proof.PARITY_TABLES == drill.CANONICAL_TABLES
    for module in (backup, proof, drill):
        assert module.LEGACY_PARITY_MIGRATION_HEADS == backup.LEGACY_PARITY_MIGRATION_HEADS
        assert module.CAPABILITY_PARITY_CONTRACT == backup.CAPABILITY_PARITY_CONTRACT
        assert module.CAPABILITY_PARITY_MIGRATION_HEAD == CAPABILITIES
        assert module.CAPABILITY_PARITY_TABLES == backup.PARITY_TABLES + (
            "capability_grants",
            "capability_revocations",
        )
        assert len(module.parity_tables_for_head(CAPABILITIES)) == 41
        for head in module.LEGACY_PARITY_MIGRATION_HEADS:
            assert module.parity_tables_for_head(head) == backup.PARITY_TABLES


@pytest.mark.parametrize("head", ["", "20000101_0001", "20260908_0020", "20260907_0019;bad"])
def test_unknown_or_unsafe_heads_never_fall_back_to_legacy(head: str) -> None:
    for module in (backup, proof, drill):
        with pytest.raises(RuntimeError, match="no reviewed"):
            module.parity_tables_for_head(head)


@pytest.mark.parametrize("head", [LEGACY, CAPABILITIES])
def test_capture_queries_version_and_all_counts_from_same_exported_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head: str,
) -> None:
    target = _target(tmp_path, head)
    tables = backup.parity_tables_for_head(head)
    query = backup.parity_command(target, "00000003-0000001B-1")[-1]
    assert "SET TRANSACTION SNAPSHOT '00000003-0000001B-1'" in query
    assert "SELECT '__migration_head__', version_num FROM alembic_version" in query
    assert all(f'FROM "{table}"' in query for table in tables)
    assert ('FROM "capability_grants"' in query) == (head == CAPABILITIES)
    output = f"__migration_head__|{head}\n" + "\n".join(f"{table}|0" for table in tables)
    monkeypatch.setattr(backup, "run_checked", lambda *_a, **_kw: SimpleNamespace(stdout=output))
    assert backup.source_row_counts(target, "00000003-0000001B-1") == {table: 0 for table in tables}
    if head == LEGACY:
        assert backup.parity_metadata_fields(head) == {}
    else:
        assert backup.parity_metadata_fields(head) == {
            "parity_contract": backup.CAPABILITY_PARITY_CONTRACT,
            "migration_head": head,
        }


@pytest.mark.parametrize("mode", ["wrong_head", "missing_head", "duplicate_head", "partial"])
def test_capture_refuses_snapshot_release_mismatch_and_partial_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    target = _target(tmp_path, CAPABILITIES)
    rows = [f"__migration_head__|{CAPABILITIES}"] + [
        f"{table}|0" for table in backup.CAPABILITY_PARITY_TABLES
    ]
    if mode == "wrong_head":
        rows[0] = f"__migration_head__|{LEGACY}"
    elif mode == "missing_head":
        rows = rows[1:]
    elif mode == "duplicate_head":
        rows.append(rows[0])
    else:
        rows = rows[:-1]
    monkeypatch.setattr(
        backup, "run_checked", lambda *_a, **_kw: SimpleNamespace(stdout="\n".join(rows))
    )
    with pytest.raises(backup.BackupError):
        backup.source_row_counts(target, "00000003-0000001B-1")


@pytest.mark.parametrize("head", [LEGACY, CAPABILITIES])
def test_exact_old_and_new_metadata_are_accepted_without_format_substitution(
    tmp_path: Path,
    head: str,
) -> None:
    dump, metadata, payload = _metadata(tmp_path, head)
    _validate_both(dump, metadata, head)
    if head == LEGACY:
        assert "parity_contract" not in payload and "migration_head" not in payload
        assert len(payload["row_counts"]) == 39
    else:
        assert payload["row_counts"]["capability_grants"] == 3
        assert payload["row_counts"]["capability_revocations"] == 1


@pytest.mark.parametrize("source,expected", [(LEGACY, CAPABILITIES), (CAPABILITIES, LEGACY)])
def test_old_backup_cannot_prove_new_capabilities_or_reverse(
    tmp_path: Path,
    source: str,
    expected: str,
) -> None:
    dump, metadata, _ = _metadata(tmp_path, source)
    with pytest.raises(proof.RestoreProofError):
        proof._validate_metadata(metadata, dump, "staging", expected_migration_head=expected)
    with pytest.raises(drill.DrillError):
        drill._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=tmp_path.parent,
            expected_migration_head=expected,
        )


@pytest.mark.parametrize(
    "missing",
    [
        "capability_grants",
        "capability_revocations",
        "both",
        "row_counts",
        "migration_head",
        "parity_contract",
    ],
)
def test_capability_metadata_cannot_omit_counts_or_version_identity(
    tmp_path: Path,
    missing: str,
) -> None:
    dump, metadata, payload = _metadata(tmp_path, CAPABILITIES)
    if missing in {"row_counts", "migration_head", "parity_contract"}:
        payload.pop(missing)
    else:
        for key in (
            ["capability_grants", "capability_revocations"] if missing == "both" else [missing]
        ):
            payload["row_counts"].pop(key)
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError):
        proof._validate_metadata(metadata, dump, "staging", expected_migration_head=CAPABILITIES)
    with pytest.raises(drill.DrillError):
        drill._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=tmp_path.parent,
            expected_migration_head=CAPABILITIES,
        )


@pytest.mark.parametrize("missing", ["capability_grants", "capability_revocations", "both", "head"])
def test_restored_schema_requires_both_tables_and_exact_migration(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    tables = set(drill.CAPABILITY_PARITY_TABLES)
    if missing != "head":
        tables -= (
            {"capability_grants", "capability_revocations"} if missing == "both" else {missing}
        )

    def query(_target, _query, step):
        return "\n".join(sorted(tables)) if step == "inspect restored schema" else LEGACY

    monkeypatch.setattr(drill, "_query", query)
    with pytest.raises(drill.DrillError):
        drill._schema_and_migration(object(), CAPABILITIES)


@pytest.mark.parametrize(
    "mode",
    [
        "grant_count",
        "revocation_count",
        "missing_table",
        "wrong_head",
        "missing_contract",
        "boolean_count",
    ],
)
def test_restore_evidence_fails_on_partial_capability_records_or_wrong_head(
    tmp_path: Path,
    mode: str,
) -> None:
    _dump, metadata, source = _metadata(tmp_path, CAPABILITIES)
    expected = source["row_counts"]
    actual = dict(expected)
    payload = {
        "row_counts": actual,
        "schema": _schema_evidence(CAPABILITIES),
        "parity_contract": proof.CAPABILITY_PARITY_CONTRACT,
    }
    if mode == "grant_count":
        actual["capability_grants"] -= 1
    elif mode == "revocation_count":
        actual["capability_revocations"] -= 1
    elif mode == "missing_table":
        actual.pop("capability_revocations")
    elif mode == "wrong_head":
        payload["schema"]["actual_migration_versions"] = [LEGACY]
    elif mode == "missing_contract":
        payload.pop("parity_contract")
    else:
        actual["capability_revocations"] = True
    evidence = tmp_path / "restore-evidence.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="parity"):
        proof._verify_row_count_parity(evidence, expected, expected_migration_head=CAPABILITIES)
    if mode in {"grant_count", "revocation_count", "missing_table", "boolean_count"}:
        with pytest.raises(drill.DrillError, match="parity"):
            drill._verify_capability_backup_parity(
                SimpleNamespace(
                    expected_migration_head=CAPABILITIES,
                    backup_metadata=metadata,
                ),
                actual,
            )


def test_exact_capability_parity_and_legacy_schema_proofs_pass(tmp_path: Path) -> None:
    _dump, metadata, source = _metadata(tmp_path, CAPABILITIES)
    drill._verify_capability_backup_parity(
        SimpleNamespace(
            expected_migration_head=CAPABILITIES,
            backup_metadata=metadata,
        ),
        source["row_counts"],
    )
    for head in (LEGACY, CAPABILITIES):
        counts = {table: 0 for table in proof.parity_tables_for_head(head)}
        payload = {"row_counts": counts, "schema": _schema_evidence(head)}
        if head == CAPABILITIES:
            payload["parity_contract"] = proof.CAPABILITY_PARITY_CONTRACT
        evidence = tmp_path / f"evidence-{head}.json"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        proof._verify_row_count_parity(evidence, counts, expected_migration_head=head)


def test_new_writer_v1_metadata_is_accepted_by_exact_old_controller(tmp_path: Path) -> None:
    historical = "35c658bd028b4fc3a7c048ab72dae700cd7682d6"
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is unavailable for the exact historical-controller proof")
    completed = subprocess.run(  # noqa: S603 - exact read-only historical Git blob
        [git, "show", f"{historical}:infra/application/scripts/restore-drill.py"],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        pytest.skip("exact historical controller Git object is absent in this checkout")
    source = completed.stdout.decode("utf-8")
    assert "CAPABILITY_PARITY_CONTRACT" not in source
    module = ModuleType("ac_restore_drill_exact_35c658b")
    module.__file__ = str(Path(__file__).parents[2] / "infra/application/scripts/restore-drill.py")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102 - exact tracked source
        dump, metadata, payload = _metadata(tmp_path, LEGACY)
        assert set(payload) == {
            "artifact_type",
            "restic_tag",
            "environment",
            "release_id",
            "compose_project",
            "database_role",
            "format",
            "verification",
            "capture_started_at",
            "capture_completed_at",
            "captured_at",
            "captured_at_epoch_ns",
            "capture_clock",
            "dump_bytes",
            "dump_sha256",
            "row_counts",
        }
        result = module._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=Path(__file__).parents[2],
        )
        assert result[0] == metadata.resolve()
        assert result[2] == "a" * 40
    finally:
        sys.modules.pop(module.__name__, None)


def test_compatibility_head_catalogue_contains_only_actual_checked_in_revisions() -> None:
    import ast

    revisions = set()
    for path in (Path(__file__).parents[2] / "db/migrations/versions").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "revision"
            ):
                revisions.add(ast.literal_eval(node.value))
    assert backup.LEGACY_PARITY_MIGRATION_HEADS | {CAPABILITIES} <= revisions
