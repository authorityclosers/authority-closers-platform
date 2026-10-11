"""Migration gate failures plus opt-in real disposable PostgreSQL rehearsal."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "migration_schema_gate", ROOT / "scripts/ci/migration_schema_gate.py"
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

BASELINE = "20261010_0001"
CANDIDATE = "20261010_0002"


def migration(tmp_path: Path, upgrade: str, downgrade: str = "op.drop_table('added')"):
    versions = tmp_path / "db/migrations/versions"
    versions.mkdir(parents=True, exist_ok=True)
    path = versions / "candidate.py"
    path.write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        f"revision = '{CANDIDATE}'\ndown_revision = '{BASELINE}'\n"
        f"def upgrade():\n{upgrade}\ndef downgrade():\n    {downgrade}\n",
        encoding="utf-8",
    )
    return gate.Migration(CANDIDATE, BASELINE, str(path), "additive", ())


def evidence(tmp_path: Path, data: bytes = b"PGDMPfixture", **changes):
    directory = tmp_path / "artifact"
    directory.mkdir(exist_ok=True)
    (directory / "schema.dump").write_bytes(data)
    metadata = {
        "schema": "ac.migration_schema/1",
        "environment": "staging",
        "schema_only": True,
        "postgres_version_num": 180000,
        "alembic_revision": BASELINE,
        "exported_at": datetime.now(UTC).isoformat(),
        "dump_sha256": hashlib.sha256(data).hexdigest(),
        "release_id": "a" * 40,
    }
    metadata.update(changes)
    raw = json.dumps(metadata).encode()
    (directory / "manifest.json").write_bytes(raw)
    return directory, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_only": False}, "staging schema"),
        ({"environment": "production"}, "staging schema"),
        ({"postgres_version_num": True}, "staging schema"),
        ({"release_id": "unknown"}, "staging schema"),
        ({"alembic_revision": "older"}, "PR base"),
        ({"exported_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat()}, "stale"),
        ({"exported_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}, "future"),
        ({"exported_at": "2026-10-10T01:00:00"}, "stale"),
        ({"exported_at": None}, "timestamp"),
        ({"dump_sha256": "b" * 64}, "checksum"),
        ({"unexpected": "field"}, "unknown fields"),
    ],
)
def test_missing_stale_or_incompatible_provenance_fails(tmp_path, changes, message):
    directory, checksum = evidence(tmp_path, **changes)
    with pytest.raises(gate.GateError, match=message):
        gate.load_evidence(directory, checksum, BASELINE)


def test_evidence_requires_governed_checksum_and_dump_integrity(tmp_path):
    directory, checksum = evidence(tmp_path)
    assert gate.load_evidence(directory, checksum, BASELINE)[1] == b"PGDMPfixture"
    with pytest.raises(gate.GateError, match="missing"):
        gate.load_evidence(directory, "", BASELINE)
    with pytest.raises(gate.GateError, match="manifest checksum"):
        gate.load_evidence(directory, "b" * 64, BASELINE)
    (directory / "schema.dump").write_bytes(b"PGDMPchanged")
    with pytest.raises(gate.GateError, match="dump format or checksum"):
        gate.load_evidence(directory, checksum, BASELINE)


@pytest.mark.parametrize(
    "description",
    ["TABLE DATA", "MATERIALIZED VIEW DATA", "SEQUENCE SET", "BLOB", "SUBSCRIPTION", "SERVER"],
)
def test_full_backup_or_external_objects_cannot_reach_restore(description):
    listing = "1; 1259 1 TABLE public alembic_version ac_owner\n"
    with pytest.raises(gate.GateError, match="data or external"):
        gate.validate_archive_listing(listing + f"2; 0 1 {description} public fixture ac_owner\n")


def test_schema_archive_must_include_version_table():
    gate.validate_archive_listing("1; 1259 1 TABLE public alembic_version ac_owner\n")
    with pytest.raises(gate.GateError, match="Alembic"):
        gate.validate_archive_listing("1; 1259 1 TABLE public fixture ac_owner\n")


@pytest.mark.parametrize(
    ("upgrade", "message"),
    [
        ("    op.add_column('existing', sa.Column('x', sa.Text(), server_default='x'))", "default"),
        ("    op.add_column('existing', sa.Column('x', sa.Text(), unique=True))", "index"),
        ("    op.create_index('ix', 'existing', ['id'])", "CONCURRENTLY"),
        ("    op.create_unique_constraint('uq', 'existing', ['id'])", "CONCURRENTLY"),
        ("    op.execute('CREATE INDEX ix ON existing(id)')", "unproven"),
        ("    helper()", "unproven"),
        ("    op.create_index('ix', table, ['id'])", "dynamic"),
        ("    op.create_table('existing', sa.Column('id', sa.Integer()))", "baseline table"),
    ],
)
def test_unsafe_defaults_indexes_and_unproven_helpers_fail(tmp_path, upgrade, message):
    item = migration(tmp_path, upgrade)
    with pytest.raises(gate.GateError, match=message):
        gate.check_operations([item], {("public", "existing")})


@pytest.mark.parametrize(
    "upgrade",
    [
        "    op.add_column('existing', sa.Column('x', sa.Text(), server_default=None))",
        "    with op.get_context().autocommit_block():\n"
        "        op.create_index('ix', 'existing', ['id'], postgresql_concurrently=True)",
        "    op.create_table('added', sa.Column('id', sa.Integer()))\n"
        "    op.create_index('ix', 'added', ['id'])",
    ],
)
def test_nullable_columns_concurrent_indexes_and_empty_table_indexes_pass(tmp_path, upgrade):
    gate.check_operations([migration(tmp_path, upgrade)], {("public", "existing")})


def test_missing_downgrade_fails_before_rehearsal(tmp_path):
    item = migration(tmp_path, "    op.create_table('added', sa.Column('id', sa.Integer()))")
    path = Path(item.file)
    path.write_text(path.read_text().split("def downgrade", 1)[0])
    with pytest.raises(gate.GateError, match="missing"):
        gate.check_operations([item], set())


def test_multiple_heads_and_disconnected_cycles_fail():
    root = gate.Migration(BASELINE, None, "baseline.py", "additive", ())
    left = gate.Migration(CANDIDATE, BASELINE, "left.py", "additive", ())
    right = gate.Migration("other", BASELINE, "right.py", "additive", ())
    assert gate.head({BASELINE: root, CANDIDATE: left}) == CANDIDATE
    with pytest.raises(gate.GateError, match="collision"):
        gate.head({BASELINE: root, CANDIDATE: left, "other": right})
    cycle_a = replace(right, revision="cycle-a", down_revision="cycle-b")
    cycle_b = replace(right, revision="cycle-b", down_revision="cycle-a")
    with pytest.raises(gate.GateError, match="complete chain"):
        gate.head({BASELINE: root, "cycle-a": cycle_a, "cycle-b": cycle_b})


def test_irrelevant_pr_gets_named_pass_without_artifact_access(monkeypatch, capsys):
    monkeypatch.setattr(gate, "run", lambda *_: b"a" * 40)
    monkeypatch.setattr(gate, "changed_paths", lambda _: [])
    monkeypatch.setattr(gate, "rehearse", lambda *_: pytest.fail("irrelevant PR accessed evidence"))
    assert gate.main(["--base-ref", "main"]) == 0
    assert capsys.readouterr().out == "migration-safety: PASS (no migration changes)\n"


def test_relevant_pr_without_artifact_fails(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gate, "run", lambda *_: b"a" * 40)
    item = migration(tmp_path, "    op.create_table('added', sa.Column('id', sa.Integer()))")
    root = gate.Migration(BASELINE, None, "db/migrations/versions/base.py", "additive", ())
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "changed_paths", lambda _: ["db/migrations/versions/candidate.py"])
    monkeypatch.setattr(gate, "base_migrations", lambda _: {BASELINE: root})
    monkeypatch.setattr(gate, "load_migrations", lambda _: {BASELINE: root, CANDIDATE: item})
    assert gate.main(["--base-ref", "main"]) == 1
    assert (
        "migration-safety: FAIL (governed staging schema evidence is missing)"
        in capsys.readouterr().out
    )


def test_schema_normalization_preserves_ddl_semantics():
    assert (
        gate.normalized_schema(
            b"-- version\n\\restrict random\nCREATE TABLE x();\n\\unrestrict random"
        )
        == b"-- version\nCREATE TABLE x();\n"
    )
    assert gate.normalized_schema(b"CREATE TABLE x();") != gate.normalized_schema(
        b"CREATE TABLE y();"
    )
    literal = b"CREATE FUNCTION f() RETURNS text AS $$\n-- literal  \n$$ LANGUAGE sql;\n"
    assert gate.normalized_schema(literal) == literal


@pytest.fixture
def docker_evidence(tmp_path):
    if os.getenv("AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST") != "1":
        pytest.skip("Docker rehearsal runs in the required migration-safety CI job")
    with gate.disposable_postgres() as database:
        with database.connect() as connection:
            connection.execute("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)")
            connection.execute("CREATE TABLE existing (id integer PRIMARY KEY)")
            connection.execute("ALTER TABLE existing ENABLE ROW LEVEL SECURITY")
            connection.execute(
                "CREATE POLICY fictional_read ON existing TO ac_runtime USING (true)"
            )
            connection.execute(
                "INSERT INTO existing VALUES (1)"
            )  # fictional row must never be exported
            version = int(connection.execute("SHOW server_version_num").fetchone()[0])
        data = database.tool(
            "pg_dump",
            "-U",
            "ac_owner",
            "-d",
            "ac_migration_safety",
            "--schema-only",
            "--no-owner",
            "--no-acl",
            "--format=custom",
        )
        full_data = database.tool(
            "pg_dump", "-U", "ac_owner", "-d", "ac_migration_safety", "--format=custom"
        )
    directory, checksum = evidence(tmp_path, data, postgres_version_num=version)
    return directory, checksum, full_data


def write_rehearsal_repo(tmp_path: Path):
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = db/migrations\n")
    (tmp_path / "db/migrations/env.py").write_text(
        "import os\nfrom alembic import context\nfrom sqlalchemy import create_engine\n"
        "with create_engine(os.environ['AC_DATABASE_MIGRATOR_URL']).connect() as c:\n"
        "    context.configure(connection=c)\n"
        "    with context.begin_transaction():\n        context.run_migrations()\n"
    )
    (tmp_path / "db/migrations/versions/base.py").write_text(
        f"revision = '{BASELINE}'\ndown_revision = None\n"
        "def upgrade():\n    pass\ndef downgrade():\n    pass\n"
    )


@pytest.mark.parametrize("downgrade", ["op.drop_table('added')", "pass"])
def test_real_upgrade_downgrade_comparison_and_reupgrade(tmp_path, docker_evidence, downgrade):
    item = migration(
        tmp_path, "    op.create_table('added', sa.Column('id', sa.Integer()))", downgrade
    )
    write_rehearsal_repo(tmp_path)
    directory, checksum, _ = docker_evidence
    if downgrade == "pass":
        with pytest.raises(gate.GateError, match="restore the baseline schema"):
            gate.rehearse(directory, checksum, BASELINE, [item], CANDIDATE, repo=tmp_path)
    else:
        gate.rehearse(directory, checksum, BASELINE, [item], CANDIDATE, repo=tmp_path)


def test_real_full_backup_rejected_before_restore(tmp_path, docker_evidence):
    directory, _, full_data = docker_evidence
    directory, checksum = evidence(tmp_path, full_data)
    item = migration(tmp_path, "    op.create_table('added', sa.Column('id', sa.Integer()))")
    with pytest.raises(gate.GateError, match="data or external"):
        gate.rehearse(directory, checksum, BASELINE, [item], CANDIDATE, repo=tmp_path)


def test_workflow_always_names_and_summarizes_check_without_staging_secrets():
    source = (ROOT / ".github/workflows/migration-safety.yml").read_text()
    assert "name: migration-safety" in source
    assert "if: always()" in source
    assert "GITHUB_STEP_SUMMARY" in source
    assert "paths:" not in source and "paths-ignore:" not in source
    assert "AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST" in source
    assert "artifact-ids: ${{ vars.AC_MIGRATION_SCHEMA_ARTIFACT_ID }}" in source
    assert "run-id: ${{ steps.artifact.outputs.run-id }}" in source
    assert "secrets." not in source and "pull_request_target" not in source
