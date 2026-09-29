from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from scripts.ops.migration_safety import (
    ClassifierError,
    classify_range,
    classify_source,
    load_migrations,
    main,
    migration_range,
)


def source_for(upgrade: str, revision: str = "r1", down_revision: str = "None") -> str:
    return f"revision = {revision!r}\ndown_revision = {down_revision}\ndef upgrade():\n{upgrade}\n"


@pytest.mark.parametrize(
    "operation",
    [
        'op.create_table("items", sa.Column("id", sa.Integer()))',
        'op.create_index("ix_items_id", "items", ["id"])',
        'op.create_foreign_key("fk", "items", "parents", ["parent_id"], ["id"])',
        'op.create_unique_constraint("uq", "items", ["name"])',
        'op.create_check_constraint("ck", "items", "id > 0")',
    ],
)
def test_additive_schema_operations(operation: str) -> None:
    assert classify_source(source_for(f"    {operation}")).verdict == "additive"


@pytest.mark.parametrize(
    "column, expected",
    [
        ('sa.Column("name", sa.String())', "additive"),
        ('sa.Column("name", sa.String(), nullable=True)', "additive"),
        ('sa.Column("name", sa.String(), nullable=False)', "unknown"),
        ('sa.Column("name", sa.String(), nullable=None)', "unknown"),
        (
            'sa.Column("name", sa.String(), nullable=False, server_default=sa.text("x"))',
            "additive",
        ),
        ('sa.Column("name", sa.String(), nullable=False, server_default=None)', "unknown"),
        ('sa.Column("name", sa.String(), nullable=runtime_flag)', "unknown"),
    ],
)
def test_add_column_requires_safe_nullability_or_server_default(column: str, expected: str) -> None:
    migration = classify_source(source_for(f'    op.add_column("items", {column})'))
    assert migration.verdict == expected


@pytest.mark.parametrize(
    "operation",
    [
        'op.drop_table("items")',
        'op.drop_column("items", "name")',
        'op.drop_index("ix_items_name", table_name="items")',
        'op.drop_constraint("ck_items", "items")',
        'op.rename_table("items", "renamed_items")',
    ],
)
def test_drop_and_rename_operations_are_destructive(operation: str) -> None:
    assert classify_source(source_for(f"    {operation}")).verdict == "destructive"


@pytest.mark.parametrize(
    "operation",
    [
        'op.execute("SELECT 1")',
        'op.alter_column("items", "name", nullable=False)',
        (
            'with op.batch_alter_table("items") as batch:\n'
            '        batch.add_column(sa.Column("x", sa.Integer()))'
        ),
        "op.bulk_insert(items, [])",
        "apply_custom_schema_change()",
        'for item in columns:\n        op.add_column("items", item)',
    ],
)
def test_uninspectable_operations_are_unknown(operation: str) -> None:
    assert classify_source(source_for(f"    {operation}")).verdict == "unknown"


def test_destructive_operation_wins_over_unknown_operation() -> None:
    migration = classify_source(
        source_for('    op.execute("SELECT 1")\n    op.drop_table("items")')
    )
    assert migration.verdict == "destructive"


def test_source_is_parsed_but_never_executed() -> None:
    source = source_for('    op.create_table("items")') + 'raise RuntimeError("must not run")\n'
    assert classify_source(source).verdict == "additive"


def write_migration(
    directory: Path,
    revision: str,
    down_revision: str | None,
    operation: str,
) -> None:
    (directory / f"{revision}.py").write_text(
        source_for(f"    {operation}", revision=revision, down_revision=repr(down_revision)),
        encoding="utf-8",
    )


def test_revision_chain_excludes_from_and_includes_to(tmp_path: Path) -> None:
    write_migration(tmp_path, "r1", None, 'op.create_table("one")')
    write_migration(tmp_path, "r2", "r1", 'op.create_index("ix", "two", ["id"])')
    write_migration(tmp_path, "r3", "r2", 'op.execute("SELECT 1")')
    migrations = load_migrations(tmp_path)

    chain = migration_range(migrations, "r1", "r3")
    assert [migration.revision for migration in chain] == ["r2", "r3"]
    assert classify_range(chain)["verdict"] == "unknown"
    assert [item.revision for item in migration_range(migrations, "base", "r3")] == [
        "r1",
        "r2",
        "r3",
    ]
    assert migration_range(migrations, "r2", "r2") == []


@pytest.mark.parametrize(
    "operation, expected_code",
    [
        ('op.create_table("items")', 0),
        ('op.drop_table("items")', 3),
        ('op.execute("SELECT 1")', 4),
    ],
)
def test_cli_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], operation: str, expected_code: int
) -> None:
    write_migration(tmp_path, "r1", None, operation)
    code = main(["--versions", str(tmp_path), "--from", "base", "--to", "r1", "--json"])
    captured = capsys.readouterr()
    assert code == expected_code
    assert '"verdict"' in captured.out


def test_cli_equal_revisions_is_empty_additive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_migration(tmp_path, "r1", None, 'op.drop_table("items")')
    code = main(["--versions", str(tmp_path), "--from", "r1", "--to", "r1", "--json"])
    assert code == 0
    assert capsys.readouterr().out.strip() == '{"verdict":"additive","migrations":[]}'


def test_missing_revision_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_migration(tmp_path, "r1", None, 'op.create_table("items")')
    code = main(["--versions", str(tmp_path), "--from", "missing", "--to", "r1"])
    assert code == 2
    assert "revision not found" in capsys.readouterr().err


def test_non_ancestor_range_is_a_usage_error(tmp_path: Path) -> None:
    write_migration(tmp_path, "r1", None, 'op.create_table("one")')
    write_migration(tmp_path, "r2", "r1", 'op.create_table("two")')
    with pytest.raises(ClassifierError, match="not an ancestor"):
        migration_range(load_migrations(tmp_path), "r2", "r1")


def test_all_repository_migrations_parse_and_receive_a_verdict() -> None:
    versions = Path(__file__).resolve().parents[2] / "db/migrations/versions"
    counts: Counter[str] = Counter()
    files = sorted(path for path in versions.glob("*.py") if path.name != "__init__.py")
    assert files
    for path in files:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        migration = classify_source(source, str(path))
        assert migration.verdict in {"additive", "destructive", "unknown"}
        counts[migration.verdict] += 1
    print(f"migration verdict counts: {dict(sorted(counts.items()))}")
