#!/usr/bin/env python3
"""Conservatively classify Alembic migrations without importing them."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERDICTS = ("additive", "unknown", "destructive")
SEVERITY = {verdict: rank for rank, verdict in enumerate(VERDICTS)}
ADDITIVE_OPS = {
    "create_table",
    "create_index",
    "create_foreign_key",
    "create_unique_constraint",
    "create_check_constraint",
}
UNKNOWN_OPS = {"execute", "alter_column", "batch_alter_table", "bulk_insert"}
SAFE_SQLALCHEMY_CALLS = {
    "ARRAY",
    "BigInteger",
    "Boolean",
    "CheckConstraint",
    "Column",
    "Date",
    "DateTime",
    "Enum",
    "Float",
    "ForeignKey",
    "ForeignKeyConstraint",
    "Identity",
    "Index",
    "Integer",
    "JSON",
    "LargeBinary",
    "Numeric",
    "PrimaryKeyConstraint",
    "SmallInteger",
    "String",
    "Text",
    "Time",
    "UniqueConstraint",
    "Uuid",
    "text",
}


class ClassifierError(ValueError):
    """A versions directory or revision range cannot be resolved."""


@dataclass(frozen=True)
class Migration:
    revision: str
    down_revision: str | None
    file: str
    verdict: str
    reasons: tuple[str, ...]


def _call_name(call: ast.Call) -> tuple[str, str] | None:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    return None


def _qualified_tail(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        tail = node.attr
        node = node.value
    if isinstance(node, ast.Name) and node.id == "sa":
        return tail
    return None


def _is_safe_nested_call(call: ast.Call) -> bool:
    name = _call_name(call)
    if name == ("op", "f"):
        return True
    return _qualified_tail(call.func) in SAFE_SQLALCHEMY_CALLS


def _literal_assignment(module: ast.Module, name: str) -> Any:
    for statement in module.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            try:
                return ast.literal_eval(value)
            except (ValueError, TypeError):
                return _MISSING
    return _MISSING


_MISSING = object()


def _classify_upgrade(module: ast.Module) -> tuple[str, tuple[str, ...]]:
    upgrades = [
        statement
        for statement in module.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == "upgrade"
    ]
    if len(upgrades) != 1:
        return "unknown", ("upgrade() is missing or ambiguous",)

    verdicts: list[str] = []
    reasons: list[str] = []

    def record(verdict: str, reason: str) -> None:
        verdicts.append(verdict)
        reasons.append(reason)

    def inspect_nested_calls(node: ast.AST, root: ast.Call | None = None) -> None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or child is root:
                continue
            name = _call_name(child)
            if name and name[0] == "op":
                if name[1].startswith("drop_") or name[1] == "rename_table":
                    record("destructive", f"op.{name[1]} removes or renames schema objects")
                elif name[1] == "f":
                    continue
                else:
                    record("unknown", f"nested op.{name[1]} call is not classified")
            elif not _is_safe_nested_call(child):
                record("unknown", "upgrade() contains a helper or unsupported call")

    def visit_statement(statement: ast.stmt) -> None:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return  # A docstring does not change schema state.
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            name = _call_name(call)
            if name and name[0] == "op":
                operation = name[1]
                if operation.startswith("drop_") or operation == "rename_table":
                    record("destructive", f"op.{operation} removes or renames schema objects")
                elif operation == "add_column":
                    column = call.args[1] if len(call.args) > 1 else None
                    if not isinstance(column, ast.Call) or _qualified_tail(column.func) != "Column":
                        record("unknown", "op.add_column column definition is not a literal Column")
                    else:
                        no_keyword = object()
                        nullable = next(
                            (kw.value for kw in column.keywords if kw.arg == "nullable"),
                            no_keyword,
                        )
                        server_default = next(
                            (kw.value for kw in column.keywords if kw.arg == "server_default"),
                            no_keyword,
                        )
                        explicit_not_null = (
                            isinstance(nullable, ast.Constant) and nullable.value is False
                        )
                        has_server_default = server_default is not no_keyword and not (
                            isinstance(server_default, ast.Constant)
                            and server_default.value is None
                        )
                        if explicit_not_null and not has_server_default:
                            record(
                                "unknown",
                                "op.add_column is non-nullable without a server default",
                            )
                        elif (
                            nullable is not no_keyword
                            and not (isinstance(nullable, ast.Constant) and nullable.value is True)
                            and not has_server_default
                        ):
                            record("unknown", "op.add_column nullability is not statically safe")
                        else:
                            record("additive", "op.add_column is nullable or has a server default")
                elif operation in ADDITIVE_OPS:
                    record("additive", f"op.{operation} adds schema objects")
                elif operation in UNKNOWN_OPS:
                    record("unknown", f"op.{operation} requires manual safety review")
                else:
                    record("unknown", f"op.{operation} is not classified")
                inspect_nested_calls(call, root=call)
                return

        if isinstance(
            statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)
        ):
            record(
                "unknown", f"upgrade() contains unsupported {type(statement).__name__} control flow"
            )
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.stmt):
                    visit_statement(child)
            inspect_nested_calls(statement)
            return

        if isinstance(statement, ast.Pass):
            record("unknown", "upgrade() contains an unsupported pass statement")
            return

        record("unknown", f"upgrade() contains unsupported {type(statement).__name__} code")
        inspect_nested_calls(statement)
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.stmt):
                visit_statement(child)

    for statement in upgrades[0].body:
        visit_statement(statement)
    if not verdicts:
        return "unknown", ("upgrade() has no recognized schema operations",)
    return max(verdicts, key=SEVERITY.__getitem__), tuple(dict.fromkeys(reasons))


def classify_source(source: str, file: str = "<memory>") -> Migration:
    """Parse and classify one migration source without executing it."""
    try:
        module = ast.parse(source, filename=file)
    except SyntaxError as exc:
        return Migration("unknown", None, file, "unknown", (f"Python parse error: {exc.msg}",))

    revision = _literal_assignment(module, "revision")
    down_revision = _literal_assignment(module, "down_revision")
    if not isinstance(revision, str) or not revision:
        return Migration("unknown", None, file, "unknown", ("revision is not a literal string",))
    if down_revision is not None and not isinstance(down_revision, str):
        return Migration(
            revision,
            None,
            file,
            "unknown",
            ("down_revision is not a single literal revision",),
        )
    verdict, reasons = _classify_upgrade(module)
    return Migration(revision, down_revision, file, verdict, reasons)


def load_migrations(versions_dir: Path) -> dict[str, Migration]:
    if not versions_dir.is_dir():
        raise ClassifierError(f"versions directory not found: {versions_dir}")
    migrations: dict[str, Migration] = {}
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ClassifierError(f"cannot read migration {path}: {exc}") from exc
        migration = classify_source(source, str(path))
        if migration.revision == "unknown":
            raise ClassifierError(f"migration has no literal revision: {path}")
        if migration.revision in migrations:
            raise ClassifierError(f"duplicate revision {migration.revision!r}")
        migrations[migration.revision] = migration
    return migrations


def migration_range(
    migrations: dict[str, Migration], from_revision: str, to_revision: str
) -> list[Migration]:
    if from_revision == to_revision:
        if from_revision != "base" and from_revision not in migrations:
            raise ClassifierError(f"revision not found: {from_revision}")
        return []
    if to_revision == "base":
        raise ClassifierError("revision not found: base cannot be the target of a non-empty range")
    if from_revision != "base" and from_revision not in migrations:
        raise ClassifierError(f"revision not found: {from_revision}")
    if to_revision not in migrations:
        raise ClassifierError(f"revision not found: {to_revision}")

    reverse_chain: list[Migration] = []
    cursor = to_revision
    while cursor != from_revision:
        migration = migrations.get(cursor)
        if migration is None:
            raise ClassifierError(f"revision chain is broken at: {cursor}")
        reverse_chain.append(migration)
        parent = migration.down_revision
        if parent is None:
            if from_revision != "base":
                raise ClassifierError(f"{from_revision!r} is not an ancestor of {to_revision!r}")
            break
        if parent not in migrations:
            raise ClassifierError(f"revision chain references missing parent: {parent}")
        cursor = parent
    return list(reversed(reverse_chain))


def classify_range(migrations: list[Migration]) -> dict[str, Any]:
    verdict = "additive"
    for migration in migrations:
        if SEVERITY[migration.verdict] > SEVERITY[verdict]:
            verdict = migration.verdict
    return {
        "verdict": verdict,
        "migrations": [
            {
                "revision": migration.revision,
                "file": migration.file,
                "verdict": migration.verdict,
                "reasons": list(migration.reasons),
            }
            for migration in migrations
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", required=True, type=Path)
    parser.add_argument("--from", dest="from_revision", required=True)
    parser.add_argument("--to", dest="to_revision", required=True)
    parser.add_argument("--json", action="store_true", help="emit the JSON result")
    args = parser.parse_args(argv)
    try:
        migrations = load_migrations(args.versions)
        chain = migration_range(migrations, args.from_revision, args.to_revision)
    except ClassifierError as exc:
        print(f"migration_safety: {exc}", file=sys.stderr)
        return 2
    result = classify_range(chain)
    print(json.dumps(result, separators=(",", ":")))
    return {"additive": 0, "destructive": 3, "unknown": 4}[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
