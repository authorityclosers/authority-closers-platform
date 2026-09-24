"""Exact migration-bound parity through Sales Xray analysis-language settings."""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from tests.infra.test_postgres_backup import backup
from tests.infra.test_postgres_restore_proof import _schema_evidence, _write_pair, proof
from tests.infra.test_postgres_restore_proof import _write_release as _write_image_release
from tests.infra.test_postgres_restore_proof import restore_drill_contract as drill

pytestmark = pytest.mark.skipif(
    os.name != "nt" and os.geteuid() != 0,
    reason="root-owned metadata validation runs in the root control-plane gate",
)
LEGACY = "20260904_0018"
CAPABILITIES = "20260907_0019"
PRACTICE = "20260908_0020"
FOCUS = "20260908_0021"
AUTHORING = "20260908_0022"
REVISION = "20260909_0023"
MEDIA_LIBRARY = "20260909_0024"
COURSE_CREATION = "20260909_0025"
STUDIO_VIDEO_UPLOADS = "20260910_0026"
COMMUNITY_IDENTITY = "20260910_0027"
GLOBAL_COMMUNITY_IDENTITY = "20260910_0028"
APP_UPDATES = "20260910_0029"
SALES_XRAY = "20260913_0030"
INFERENCE = "20260913_0031"
PLANS = "20260913_0032"
COMMUNITY_CONNECTIONS = "20260913_0033"
REVIEWS = "20260913_0034"
REVIEW_INVITATIONS = "20260913_0035"
ACQUISITION = "20260914_0036"
PROCESSING_OWNERSHIP = "20260914_0037"
REVIEWER_IDENTITY = "20260914_0038"
PROVIDER_ACTIVATION = "20260914_0039"
PROCESSING_CONTINUATION = "20260914_0040"
EXECUTION_CONTROL = "20260914_0041"
ANALYSIS_LANGUAGE = "20260923_0044"
EMAIL_LOGIN_CODES = "20260923_0045"
SALES_XRAY_PROFILES = "20260923_0046"
COACHING_DEPTH = "20260924_0047"
EMAIL_ACKNOWLEDGEMENT = "20260924_0048"
HEADS = (
    LEGACY,
    CAPABILITIES,
    PRACTICE,
    FOCUS,
    AUTHORING,
    REVISION,
    MEDIA_LIBRARY,
    COURSE_CREATION,
    STUDIO_VIDEO_UPLOADS,
    COMMUNITY_IDENTITY,
    GLOBAL_COMMUNITY_IDENTITY,
    APP_UPDATES,
    SALES_XRAY,
    INFERENCE,
    PLANS,
    COMMUNITY_CONNECTIONS,
    REVIEWS,
    REVIEW_INVITATIONS,
    ACQUISITION,
    PROCESSING_OWNERSHIP,
    REVIEWER_IDENTITY,
    PROVIDER_ACTIVATION,
    PROCESSING_CONTINUATION,
    EXECUTION_CONTROL,
    "20260915_0042",
    "20260915_0043",
    ANALYSIS_LANGUAGE,
    EMAIL_LOGIN_CODES,
    SALES_XRAY_PROFILES,
    COACHING_DEPTH,
    EMAIL_ACKNOWLEDGEMENT,
)
VERSIONED_HEADS = HEADS[1:]
TABLELESS_VERSIONED_HEADS = (
    REVISION,
    MEDIA_LIBRARY,
    COURSE_CREATION,
    ANALYSIS_LANGUAGE,
    COACHING_DEPTH,
    EMAIL_ACKNOWLEDGEMENT,
)
NEW_TABLES = {
    PRACTICE: (
        "practice_set_versions",
        "practice_attempts",
        "practice_profiles",
        "practice_responses",
        "practice_commands",
        "practice_feedback_acks",
        "practice_participations",
        "practice_reward_claims",
        "practice_ledger_entries",
    ),
    FOCUS: ("practice_focus_runs", "practice_focus_events"),
    AUTHORING: ("catalog_authoring_commands",),
    STUDIO_VIDEO_UPLOADS: ("studio_video_uploads",),
    COMMUNITY_IDENTITY: ("academy_public_profiles",),
    GLOBAL_COMMUNITY_IDENTITY: (
        "community_public_profiles",
        "academy_leaderboard_preferences",
    ),
    APP_UPDATES: ("app_update_read_receipts",),
    SALES_XRAY: (
        "conversation_budget_accounts",
        "conversation_review_cursors",
        "conversation_minute_accounts",
        "conversation_permissions",
        "conversation_recordings",
        "conversation_checkpoints",
        "conversation_commands",
        "conversation_quotes",
        "conversation_runs",
        "conversation_reviews",
        "conversation_quote_acceptances",
        "conversation_provider_configurations",
        "conversation_report_drafts",
    ),
    INFERENCE: ("conversation_inference_tasks",),
    PLANS: (
        "conversation_processing_plans",
        "conversation_plan_stage_authorizations",
    ),
    COMMUNITY_CONNECTIONS: (
        "community_discovery_preferences",
        "community_connections",
        "community_connection_events",
        "community_blocks",
        "community_reports",
    ),
    REVIEWS: (
        "conversation_review_assignments",
        "conversation_review_revocations",
        "conversation_review_feedback",
    ),
    REVIEW_INVITATIONS: (
        "conversation_review_invitations",
        "conversation_review_invitation_revocations",
        "conversation_review_invitation_acceptances",
    ),
    ACQUISITION: (
        "conversation_visitors",
        "conversation_visitor_claims",
        "conversation_acquisition_usage",
        "conversation_acquisition_settlements",
    ),
    PROCESSING_OWNERSHIP: (
        "conversation_processing_principals",
        "conversation_processing_leases",
        "conversation_guest_submissions",
    ),
    REVIEWER_IDENTITY: ("reviewer_auth_challenges",),
    PROVIDER_ACTIVATION: ("conversation_provider_activations",),
    PROCESSING_CONTINUATION: ("conversation_processing_continuations",),
    EXECUTION_CONTROL: ("conversation_execution_controls",),
    "20260915_0042": ("conversation_analysis_settings",),
    "20260915_0043": ("conversation_retained_c5_versions",),
    EMAIL_LOGIN_CODES: ("email_login_codes",),
    SALES_XRAY_PROFILES: ("sales_xray_profiles",),
}
ROOT = Path(__file__).parents[2]


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
    if head != LEGACY:
        payload["row_counts"].update(capability_grants=3, capability_revocations=1)
    for tables in NEW_TABLES.values():
        for table in tables:
            if table in payload["row_counts"]:
                payload["row_counts"][table] = 4
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


@pytest.mark.parametrize("head", ["", "20000101_0001", "20260907_0019;bad"])
def test_unknown_or_unsafe_heads_never_fall_back_to_legacy(head: str) -> None:
    for module in (backup, proof, drill):
        with pytest.raises(RuntimeError, match="no reviewed"):
            module.parity_tables_for_head(head)


@pytest.mark.parametrize("head", HEADS)
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
    assert ('FROM "capability_grants"' in query) == (head != LEGACY)
    output = f"__migration_head__|{head}\n" + "\n".join(f"{table}|0" for table in tables)
    monkeypatch.setattr(backup, "run_checked", lambda *_a, **_kw: SimpleNamespace(stdout=output))
    assert backup.source_row_counts(target, "00000003-0000001B-1") == {table: 0 for table in tables}
    if head == LEGACY:
        assert backup.parity_metadata_fields(head) == {}
    else:
        assert backup.parity_metadata_fields(head) == {
            "parity_contract": backup.parity_contract_for_head(head),
            "migration_head": head,
        }


@pytest.mark.parametrize("mode", ["wrong_head", "missing_head", "duplicate_head", "partial"])
@pytest.mark.parametrize("head", VERSIONED_HEADS)
def test_capture_refuses_snapshot_release_mismatch_and_partial_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    head: str,
) -> None:
    target = _target(tmp_path, head)
    rows = [f"__migration_head__|{head}"] + [
        f"{table}|0" for table in backup.parity_tables_for_head(head)
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


@pytest.mark.parametrize("head", HEADS)
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


@pytest.mark.parametrize("source,expected", list(itertools.permutations(HEADS, 2)))
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
            workspace_root=ROOT,
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
            workspace_root=ROOT,
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
            drill._verify_versioned_backup_parity(
                SimpleNamespace(
                    expected_migration_head=CAPABILITIES,
                    backup_metadata=metadata,
                ),
                actual,
            )


def test_exact_capability_parity_and_legacy_schema_proofs_pass(tmp_path: Path) -> None:
    _dump, metadata, source = _metadata(tmp_path, CAPABILITIES)
    drill._verify_versioned_backup_parity(
        SimpleNamespace(
            expected_migration_head=CAPABILITIES,
            backup_metadata=metadata,
        ),
        source["row_counts"],
    )
    for head in HEADS:
        counts = {table: 0 for table in proof.parity_tables_for_head(head)}
        payload = {"row_counts": counts, "schema": _schema_evidence(head)}
        if head != LEGACY:
            payload["parity_contract"] = proof.parity_contract_for_head(head)
        evidence = tmp_path / f"evidence-{head}.json"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        proof._verify_row_count_parity(evidence, counts, expected_migration_head=head)


def test_new_writer_v1_metadata_is_accepted_by_exact_old_controller(tmp_path: Path) -> None:
    historical = "35c658bd028b4fc3a7c048ab72dae700cd7682d6"
    required = os.getenv("AC_REQUIRE_HISTORICAL_BACKUP_CONTROLLER_TEST") == "1"
    root = Path(__file__).resolve().parents[2]
    git = shutil.which("git")
    if git is None:
        if required:
            pytest.fail("Git is required for the exact historical-controller proof")
        pytest.skip("Git is unavailable for the exact historical-controller proof")
    completed = subprocess.run(  # noqa: S603 - exact read-only historical Git blob
        [
            git,
            "-c",
            f"safe.directory={root.as_posix()}",
            "show",
            f"{historical}:infra/application/scripts/restore-drill.py",
        ],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        if required:
            pytest.fail("exact historical controller Git object is required but unreadable")
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
                (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "revision"
                )
                or isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "revision"
                    for target in node.targets
                )
            ):
                revisions.add(ast.literal_eval(node.value))
    assert backup.LEGACY_PARITY_MIGRATION_HEADS | set(VERSIONED_HEADS) <= revisions


def test_versioned_contracts_match_all_new_migration_tables_exactly() -> None:
    import ast

    for head, added in NEW_TABLES.items():
        paths = list((ROOT / "db/migrations/versions").glob(f"{head}_*.py"))
        assert len(paths) == 1
        source = paths[0].read_text(encoding="utf-8")
        tree = ast.parse(source)
        created = {
            ast.literal_eval(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == "create_table"
        }
        # 0030 deliberately keeps most of its frozen SQL in execute() blocks;
        # include those CREATE TABLE statements alongside op.create_table.
        created.update(re.findall(r"\bCREATE\s+TABLE\s+([a-z_][a-z0-9_]*)", source, re.IGNORECASE))
        assert created == set(added)
    for head in TABLELESS_VERSIONED_HEADS:
        paths = list((ROOT / "db/migrations/versions").glob(f"{head}_*.py"))
        assert len(paths) == 1
        tree = ast.parse(paths[0].read_text(encoding="utf-8"))
        created = {
            ast.literal_eval(node.args[0])
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
            and node.func.attr == "create_table"
        }
        assert created == set()
    expected_counts = (
        39,
        41,
        50,
        52,
        53,
        53,
        53,
        53,
        54,
        55,
        57,
        58,
        71,
        72,
        74,
        79,
        82,
        85,
        89,
        92,
        93,
        94,
        95,
        96,
        97,
        98,
        98,
        99,
        100,
        100,
        100,
    )
    expected_contracts = (
        None,
        "ac-postgres-parity-v2",
        "ac-postgres-parity-v3",
        "ac-postgres-parity-v4",
        "ac-postgres-parity-v5",
        "ac-postgres-parity-v5",
        "ac-postgres-parity-v5",
        "ac-postgres-parity-v5",
        "ac-postgres-parity-v6",
        "ac-postgres-parity-v7",
        "ac-postgres-parity-v8",
        "ac-postgres-parity-v9",
        "ac-postgres-parity-v10",
        "ac-postgres-parity-v11",
        "ac-postgres-parity-v12",
        "ac-postgres-parity-v13",
        "ac-postgres-parity-v14",
        "ac-postgres-parity-v15",
        "ac-postgres-parity-v16",
        "ac-postgres-parity-v17",
        "ac-postgres-parity-v18",
        "ac-postgres-parity-v19",
        "ac-postgres-parity-v20",
        "ac-postgres-parity-v21",
        "ac-postgres-parity-v22",
        "ac-postgres-parity-v23",
        "ac-postgres-parity-v24",
        "ac-postgres-parity-v25",
        "ac-postgres-parity-v26",
        "ac-postgres-parity-v27",
        "ac-postgres-parity-v28",
    )
    for module in (backup, proof, drill):
        assert module.VERSIONED_PARITY_CONTRACTS == backup.VERSIONED_PARITY_CONTRACTS
        for head, count, contract in zip(HEADS, expected_counts, expected_contracts, strict=True):
            tables = module.parity_tables_for_head(head)
            assert tables == backup.parity_tables_for_head(head)
            assert len(set(tables)) == len(tables) == count
            assert module.parity_contract_for_head(head) == contract
        previous = set(module.CAPABILITY_PARITY_TABLES)
        for head, added in NEW_TABLES.items():
            current = set(module.parity_tables_for_head(head))
            assert current - previous == set(added)
            assert previous <= current
            previous = current


@pytest.mark.parametrize("head", tuple(NEW_TABLES))
def test_new_writer_populated_metadata_and_restore_parity_pass(tmp_path: Path, head: str) -> None:
    dump, metadata, payload = _metadata(tmp_path, head)
    _validate_both(dump, metadata, head)
    assert all(payload["row_counts"][name] == 4 for name in NEW_TABLES[head])
    drill._verify_versioned_backup_parity(
        SimpleNamespace(expected_migration_head=head, backup_metadata=metadata),
        payload["row_counts"],
    )
    evidence = tmp_path / "passed.json"
    evidence.write_text(
        json.dumps(
            {
                "row_counts": payload["row_counts"],
                "schema": _schema_evidence(head),
                "parity_contract": payload["parity_contract"],
            }
        ),
        encoding="utf-8",
    )
    proof._verify_row_count_parity(evidence, payload["row_counts"], expected_migration_head=head)


@pytest.mark.parametrize("head", tuple(NEW_TABLES))
@pytest.mark.parametrize("missing", ["row_counts", "migration_head", "parity_contract"])
def test_new_metadata_requires_complete_version_identity(
    tmp_path: Path, head: str, missing: str
) -> None:
    dump, metadata, payload = _metadata(tmp_path, head)
    payload.pop(missing)
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="contract|identity"):
        proof._validate_metadata(metadata, dump, "staging", expected_migration_head=head)
    with pytest.raises(drill.DrillError, match="contract"):
        drill._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=ROOT,
            expected_migration_head=head,
        )


@pytest.mark.parametrize("head", tuple(NEW_TABLES))
@pytest.mark.parametrize(
    "field,value",
    [
        ("parity_contract", "ac-postgres-parity-v2"),
        ("migration_head", CAPABILITIES),
    ],
)
def test_new_metadata_cannot_relabel_complete_counts_as_an_older_contract(
    tmp_path: Path, head: str, field: str, value: str
) -> None:
    dump, metadata, payload = _metadata(tmp_path, head)
    payload[field] = value
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="identity"):
        proof._validate_metadata(metadata, dump, "staging", expected_migration_head=head)
    with pytest.raises(drill.DrillError, match="contract"):
        drill._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=ROOT,
            expected_migration_head=head,
        )


@pytest.mark.parametrize(
    "head,table", [(head, table) for head, tables in NEW_TABLES.items() for table in tables]
)
def test_every_new_table_is_required_in_source_metadata_and_restored_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head: str, table: str
) -> None:
    dump, metadata, payload = _metadata(tmp_path, head)
    payload["row_counts"].pop(table)
    metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="size or digest"):
        proof._validate_metadata(metadata, dump, "staging", expected_migration_head=head)
    with pytest.raises(drill.DrillError, match="parity"):
        drill._validate_backup_metadata(
            str(metadata),
            backup=dump,
            environment="staging",
            workspace_root=ROOT,
            expected_migration_head=head,
        )
    monkeypatch.setattr(
        drill,
        "_query",
        lambda _target, _query, step: (
            "\n".join(payload["row_counts"]) if step == "inspect restored schema" else head
        ),
    )
    with pytest.raises(drill.DrillError, match="missing 1 canonical"):
        drill._schema_and_migration(object(), head)


@pytest.mark.parametrize(
    "head,table", [(head, table) for head, tables in NEW_TABLES.items() for table in tables]
)
@pytest.mark.parametrize("mode", ["lost_record", "missing_table", "boolean_count"])
def test_each_new_history_table_rejects_partial_restoration(
    tmp_path: Path, head: str, table: str, mode: str
) -> None:
    _dump, metadata, payload = _metadata(tmp_path, head)
    expected = payload["row_counts"]
    actual = dict(expected)
    if mode == "lost_record":
        actual[table] -= 1
    elif mode == "missing_table":
        actual.pop(table)
    else:
        actual[table] = True
    evidence = tmp_path / "failed.json"
    evidence.write_text(
        json.dumps(
            {
                "row_counts": actual,
                "schema": _schema_evidence(head),
                "parity_contract": payload["parity_contract"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(proof.RestoreProofError, match="parity"):
        proof._verify_row_count_parity(evidence, expected, expected_migration_head=head)
    with pytest.raises(drill.DrillError, match="parity"):
        drill._verify_versioned_backup_parity(
            SimpleNamespace(expected_migration_head=head, backup_metadata=metadata), actual
        )


@pytest.mark.parametrize("head", tuple(NEW_TABLES))
@pytest.mark.parametrize("mode", ["wrong_head", "missing_contract", "wrong_contract", "extra_head"])
def test_new_restore_evidence_requires_exact_migration_and_contract(
    tmp_path: Path, head: str, mode: str
) -> None:
    _dump, _metadata_path, source = _metadata(tmp_path, head)
    payload = {
        "row_counts": source["row_counts"],
        "schema": _schema_evidence(head),
        "parity_contract": source["parity_contract"],
    }
    if mode == "wrong_head":
        payload["schema"]["actual_migration_versions"] = [CAPABILITIES]
    elif mode == "extra_head":
        payload["schema"]["actual_migration_versions"] = [head, CAPABILITIES]
    elif mode == "missing_contract":
        payload.pop("parity_contract")
    else:
        payload["parity_contract"] = backup.CAPABILITY_PARITY_CONTRACT
    evidence = tmp_path / "failed.json"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(proof.RestoreProofError, match="parity"):
        proof._verify_row_count_parity(evidence, source["row_counts"], expected_migration_head=head)


def _coach_image_manifest(tmp_path: Path) -> Path:
    manifest = _write_image_release(tmp_path) / "release-images.env"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        + "AC_COACH_IMAGE=sha256:"
        + "e" * 64
        + "\n"
        + "AC_COACH_TRANSPORT_DIGEST=sha256:"
        + "e" * 64
        + "\n"
        + "AC_COACH_REGISTRY_DIGEST=ghcr.io/authorityclosers/authority-closers-coach-web@sha256:"
        + "e" * 64
        + "\n",
        encoding="utf-8",
    )
    return manifest


def test_coach_complete_image_triplet_and_historical_three_images_remain_accepted(
    tmp_path: Path,
) -> None:
    old = _write_image_release(tmp_path / "old") / "release-images.env"
    assert set(proof._parse_release_env(old)) == proof.RELEASE_IMAGE_KEYS
    new = _coach_image_manifest(tmp_path / "new")
    assert set(proof._parse_release_env(new)) == proof.COACH_RELEASE_IMAGE_KEYS


@pytest.mark.parametrize(
    "key", ["AC_COACH_IMAGE", "AC_COACH_TRANSPORT_DIGEST", "AC_COACH_REGISTRY_DIGEST"]
)
def test_partial_coach_release_image_inventory_is_rejected(tmp_path: Path, key: str) -> None:
    manifest = _coach_image_manifest(tmp_path)
    manifest.write_text(
        "\n".join(
            line
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if not line.startswith(key + "=")
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(proof.RestoreProofError, match="unexpected contract"):
        proof._parse_release_env(manifest)


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("AC_COACH_IMAGE", "latest", "image identity"),
        ("AC_COACH_TRANSPORT_DIGEST", "sha256:" + "e" * 64 + ":tag", "transport identity"),
        ("AC_COACH_TRANSPORT_DIGEST", "sha256:" + "f" * 64, "transport identity is inconsistent"),
        (
            "AC_COACH_REGISTRY_DIGEST",
            "ghcr.io/other/coach@sha256:" + "e" * 64,
            "registry provenance",
        ),
    ],
)
def test_coach_image_values_have_the_same_strict_identity_guards(
    tmp_path: Path, key: str, value: str, message: str
) -> None:
    manifest = _coach_image_manifest(tmp_path)
    manifest.write_text(
        "\n".join(
            f"{key}={value}" if line.startswith(key + "=") else line
            for line in manifest.read_text(encoding="utf-8").splitlines()
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(proof.RestoreProofError, match=message):
        proof._parse_release_env(manifest)


def test_coach_environment_values_cannot_override_the_verified_backup_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = ("AC_COACH_IMAGE", "AC_COACH_APP_URL", "AC_EDGE_COACH_ALIAS")
    for key in keys:
        monkeypatch.setenv(key, "untrusted-inherited-value")
    target = _target(tmp_path, AUTHORING)
    environment = backup.compose_environment(target)
    command = backup.compose_command(target, "config", "--quiet")
    for key in keys:
        assert key not in environment
        assert command[command.index(key) - 1] == "-u"


@pytest.mark.parametrize("failure", ["missing-git", "unreadable-object"])
def test_required_historical_controller_proof_fails_instead_of_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setenv("AC_REQUIRE_HISTORICAL_BACKUP_CONTROLLER_TEST", "1")
    monkeypatch.setattr(shutil, "which", lambda _: None if failure == "missing-git" else "git")
    if failure == "unreadable-object":
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda command, **_: subprocess.CompletedProcess(command, 1, b"", b""),
        )
    with pytest.raises(pytest.fail.Exception, match="required"):
        test_new_writer_v1_metadata_is_accepted_by_exact_old_controller(tmp_path)
