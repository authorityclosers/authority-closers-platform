"""Pure, fail-closed path classification; it grants no merge/action authority.

M1b: an added db/migrations/** Python file may be routine only when static AST checks
prove its upgrade() is purely additive. Contents are parsed, never executed.
"""

import ast
import re
from collections.abc import Mapping

_ROUTINE_ROOTS = {"apps", "packages", "tests", "docs", "tools"}
_STATUSES = {"added", "modified", "removed", "renamed"}
_TERMS = (
    "payment",
    "billing",
    "price",
    "checkout",
    "subscription",
    "top-up",
    "top_up",
    "topup",
    "credit",
    "entitlement",
    "consent",
    "retention",
    "deletion",
    "score",
    "purchase",
)
_PROTECTED_PREFIXES = (
    ".github/",
    "infra/",
    "scripts/ci/",
    "scripts/ops/",
    "scripts/data-changes/",
)
# Identity, authentication, sessions, permissions/roles and organisation membership (AUT-932).
_IDENTITY_PREFIXES = tuple(
    f"packages/python/ac_platform/{name}/"
    for name in ("identity", "authorization", "tenancy", "organisations", "bootstrap")
)
_IDENTITY_TERMS = (
    "identit",
    "authenticat",
    "authoriz",
    "authoris",
    "oauth",
    "session",
    "login",
    "logout",
    "sign-in",
    "sign_in",
    "signup",
    "sign-up",
    "sign_up",
    "signout",
    "sign-out",
    "sign_out",
    "password",
    "credential",
    "csrf",
    "permission",
    "capabilit",
    "organisation",
    "organization",
    "membership",
    "tenant",
    "tenancy",
    "invit",
    "ownership",
    "security",
)
# Short terms match whole words only, so "author" and "authority" (the brand) stay ordinary.
_IDENTITY_WORDS = {
    "auth", "authn", "authz", "signin", "sso", "jwt", "acl", "acls", "rbac", "role", "roles",
    "grant", "grants", "access", "member", "members", "cookie", "cookies",
}  # fmt: skip


def _valid_path(path: object) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and path == path.strip()
        and "\\" not in path
        and not any(ord(char) < 32 or ord(char) == 127 for char in path)
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


def _identity(path: str, lower: str) -> bool:
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", path).casefold()  # SignIn -> sign-in
    if lower.startswith(_IDENTITY_PREFIXES):
        return True
    if any(term in lower or term in split for term in _IDENTITY_TERMS):
        return True
    return not _IDENTITY_WORDS.isdisjoint(re.split(r"[^a-z0-9]+", split))


def _path_reasons(path: str) -> set[str]:
    lower = path.casefold()
    parts = lower.split("/")
    name = parts[-1]
    reasons = set()
    if path.split("/", 1)[0] not in _ROUTINE_ROOTS:
        reasons.add("path:unknown-root")
    if name in {"agents.md", "claude.md"}:
        reasons.add("protected:instructions")
    if lower.startswith(_PROTECTED_PREFIXES) or lower == "scripts/ac_task.py":
        reasons.add("protected:automation")
    if (
        name == "dockerfile"
        or name.startswith(("dockerfile.", "dockerfile-", "dockerfile_"))
        or name.endswith(".dockerfile")
        or ("compose" in name and name.endswith((".yaml", ".yml", ".json")))
    ):
        reasons.add("protected:deployment")
    if ".env" in lower or "secret" in lower or "infisical" in lower:
        reasons.add("protected:secrets")
    reasons.update(f"protected:name:{term}" for term in _TERMS if term in lower)
    if _identity(path, lower):
        reasons.add("protected:identity")
    if lower.startswith("db/migrations/"):
        reasons.add("protected:migration")
    if lower == "scripts/ci/merge_class.py":
        reasons.add("protected:classifier")
    return reasons


_MIGRATION_IMPORTS: set[tuple[str | None, str, str | None]] = {
    ("alembic", "op", None),
    ("sqlalchemy", "sqlalchemy", "sa"),
    ("sqlalchemy.dialects", "postgresql", None),
    ("__future__", "annotations", None),
    ("collections.abc", "Sequence", None),
    ("typing", "Any", None),
}
_MIGRATION_NAMES = {"revision", "down_revision", "branch_labels", "depends_on"}
_ANNOTATION_NODES = (
    ast.Name,
    ast.Attribute,
    ast.Subscript,
    ast.BinOp,
    ast.BitOr,
    ast.Constant,
    ast.Tuple,
    ast.Load,
)
_SA_TYPES = {
    "BigInteger", "Boolean", "Date", "DateTime", "Float", "Integer", "JSON",
    "LargeBinary", "Numeric", "SmallInteger", "String", "Text", "Time", "Uuid",
}  # fmt: skip
_PG_TYPES = {"JSONB", "TSVECTOR"}
_TYPE_KEYWORDS = {"length", "timezone", "precision", "scale", "asdecimal", "as_uuid"}
# sa.text() is written into DDL unchanged, so only these whole-string forms are static defaults.
_TEXT_DEFAULT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?|true|false|now\(\)|'[^';\\]*'(?:::jsonb)?")


def _const(node: ast.AST | None, *types: type) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) in (types or (str,))


def _member(node: ast.AST, base: str, names: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == base
        and node.attr in names
    )


def _call(node: ast.AST, base: str, names: set[str]) -> ast.Call | None:
    if isinstance(node, ast.Call) and _member(node.func, base, names):
        return node
    return None


def _keywords(call: ast.Call, allowed: set[str]) -> dict[str, ast.expr] | None:
    names = [keyword.arg for keyword in call.keywords]
    if None in names or len(set(names)) != len(names) or not set(names) <= allowed:
        return None  # **kwargs, repeated or unknown keywords are dynamic or out of scope.
    return {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}


def _is(node: ast.AST | None, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def _name(node: ast.AST) -> bool:
    call = _call(node, "op", {"f"})
    if call is None:
        return _const(node)
    return len(call.args) == 1 and not call.keywords and _const(call.args[0])


def _type(node: ast.AST) -> bool:
    if _member(node, "sa", _SA_TYPES) or _member(node, "postgresql", _PG_TYPES):
        return True
    call = _call(node, "sa", _SA_TYPES) or _call(node, "postgresql", _PG_TYPES)
    # String type arguments (precision, collation) are written into DDL raw: ints/bools only.
    kw = _keywords(call, _TYPE_KEYWORDS) if call else None
    return (
        call is not None
        and kw is not None
        and all(_const(arg, int, bool) for arg in call.args)
        and all(_const(value, int, bool) for value in kw.values())
    )


def _server_default(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if _const(node):
        return True
    text = _call(node, "sa", {"text"})
    if text is not None:
        sql = text.args[0] if len(text.args) == 1 and not text.keywords else None
        if not (isinstance(sql, ast.Constant) and isinstance(sql.value, str)):
            return False
        return _TEXT_DEFAULT.fullmatch(sql.value) is not None and "--" not in sql.value
    call = _call(node, "sa", {"false", "true"})
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        and _member(node.func.value, "sa", {"func"})
    ):
        call = node
    return call is not None and not call.args and not call.keywords


def _column(node: ast.AST, *, added: bool) -> bool:
    call = _call(node, "sa", {"Column"})
    kw = _keywords(call, {"nullable", "server_default", "primary_key", "comment"}) if call else None
    if call is None or kw is None or len(call.args) != 2:
        return False  # Positional ForeignKey/constraint arguments are not accepted.
    if not (_const(call.args[0]) and _type(call.args[1])):
        return False
    if any(not _const(kw[key], bool) for key in ("nullable", "primary_key") if key in kw):
        return False
    if "comment" in kw and not _const(kw["comment"]):
        return False
    if "server_default" in kw and not _server_default(kw["server_default"]):
        return False
    if not added:
        return True
    explicit_null = _is(kw.get("nullable"), True)
    return (explicit_null or "server_default" in kw) and not _is(kw.get("primary_key"), True)


def _primary_key(node: ast.AST) -> bool:
    call = _call(node, "sa", {"PrimaryKeyConstraint"})
    kw = _keywords(call, {"name"}) if call else None
    return (
        call is not None
        and kw is not None
        and bool(call.args)
        and all(_const(arg) for arg in call.args)
        and ("name" not in kw or _name(kw["name"]))
    )


def _options(call: ast.Call, extra: set[str]) -> dict[str, ast.expr] | None:
    kw = _keywords(call, {"schema", "if_not_exists"} | extra)
    if kw is None or ("schema" in kw and not _const(kw["schema"])):
        return None
    if "if_not_exists" in kw and not _const(kw["if_not_exists"], bool):
        return None
    return kw


def _additive_op(node: ast.AST) -> bool:
    call = _call(node, "op", {"create_table", "create_index", "add_column"})
    if call is None or len(call.args) < 2:
        return False
    assert isinstance(call.func, ast.Attribute)
    if call.func.attr == "create_index":
        kw = _options(call, {"unique"})
        if kw is None or len(call.args) != 3:
            return False
        name, table, columns = call.args
        return (
            _name(name)
            and _const(table)
            and isinstance(columns, (ast.List, ast.Tuple))
            and bool(columns.elts)
            and all(_const(column) for column in columns.elts)
            and ("unique" not in kw or _is(kw["unique"], False))
        )
    if _options(call, set()) is None or not _const(call.args[0]):
        return False
    if call.func.attr == "add_column":
        return len(call.args) == 2 and _column(call.args[1], added=True)
    # create_table: FK, unique and check constraints are not accepted by this exception.
    return all(_column(item, added=False) or _primary_key(item) for item in call.args[1:])


def _annotation(node: ast.AST | None) -> bool:
    stack = [node] if node is not None else []
    while stack:  # Iterative walk: ast.walk imports lazily, and annotations stay shallow.
        current = stack.pop()
        if not isinstance(current, _ANNOTATION_NODES):
            return False
        stack.extend(ast.iter_child_nodes(current))
    return True


def _additive_migration(path: str, content: object) -> bool:
    """Return True only for statically proven additive upgrade() bodies; never executes."""
    if not (path.startswith("db/migrations/") and path.endswith(".py")):
        return False
    if not isinstance(content, str):
        return False
    try:
        module = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    upgrades: list[ast.FunctionDef] = []
    defined: list[str] = []
    imports: set[tuple[str | None, str, str | None]]
    for statement in module.body:
        if isinstance(statement, ast.Expr) and _const(statement.value):
            continue
        if isinstance(statement, ast.Import):
            imports = {(alias.name, alias.name, alias.asname) for alias in statement.names}
        elif isinstance(statement, ast.ImportFrom) and statement.level == 0:
            imports = {(statement.module, a.name, a.asname) for a in statement.names}
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            value = statement.value
            values = value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]
            if not (
                len(targets) == 1
                and isinstance(targets[0], ast.Name)
                and targets[0].id in _MIGRATION_NAMES
                and all(_const(item, str, type(None)) for item in values)
                and _annotation(getattr(statement, "annotation", None))
            ):
                return False
            continue
        elif isinstance(statement, ast.FunctionDef) and statement.name in {"upgrade", "downgrade"}:
            arguments = statement.args
            if (
                statement.decorator_list
                or statement.type_params
                or arguments.posonlyargs
                or arguments.args
                or arguments.vararg
                or arguments.kwonlyargs
                or arguments.kwarg
                or not _annotation(statement.returns)
            ):
                return False
            defined.append(statement.name)
            if statement.name == "upgrade":
                upgrades.append(statement)
            continue
        else:
            return False  # Any other module-level code would run when Alembic loads the file.
        if not imports <= _MIGRATION_IMPORTS:
            return False
    if len(upgrades) != 1 or len(set(defined)) != len(defined):
        return False  # Missing or ambiguous upgrade()/downgrade().
    for statement in upgrades[0].body:
        if isinstance(statement, ast.Pass):
            continue
        if not isinstance(statement, ast.Expr):
            return False
        if not (_const(statement.value) or _additive_op(statement.value)):
            return False
    return True


def classify_changed_files(
    files: object, contents: object, *, changed_files: object, truncated: bool = False
) -> dict[str, object]:
    """Classify GitHub records and supplied head strings without any external IO.

    The caller owns head pinning. Require a string for every surviving filename;
    removed files have no head content. Unsupported statuses and noncanonical
    paths fail closed. Contents are never executed; only added db/migrations/** Python files
    are AST-parsed for the additive exception, and any doubt keeps the migration escalation.
    """
    reasons: set[str] = set()
    if type(truncated) is not bool:
        reasons.add("evidence:truncation-flag")
    elif truncated:
        reasons.add("evidence:truncated")
    if not isinstance(files, (list, tuple)):
        reasons.add("evidence:records")
        files = ()
    if type(changed_files) is not int or changed_files < 0 or changed_files != len(files):
        reasons.add("evidence:count")
    if not isinstance(contents, Mapping):
        reasons.add("evidence:contents")
        contents = {}
    seen: set[str] = set()
    for record in files:
        if not isinstance(record, Mapping):
            reasons.add("evidence:record")
            continue
        filename = record.get("filename")
        previous = record.get("previous_filename")
        status = record.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            reasons.add("evidence:status")
        if status == "renamed":
            if not _valid_path(previous) or previous == filename:
                reasons.add("evidence:rename")
        elif previous is not None:
            reasons.add("evidence:rename")
        paths = [filename] + ([previous] if previous is not None else [])
        for path in paths:
            if not _valid_path(path):
                reasons.add("evidence:path")
                continue
            assert isinstance(path, str)
            if path in seen:
                reasons.add("evidence:duplicate")
            seen.add(path)
            path_reasons = _path_reasons(path)
            if (
                status == "added"
                and path == filename
                and _additive_migration(path, contents.get(filename))
            ):
                path_reasons -= {"path:unknown-root", "protected:migration"}
            reasons.update(path_reasons)
        if (
            isinstance(filename, str)
            and status != "removed"
            and not isinstance(contents.get(filename), str)
        ):
            reasons.add("evidence:contents")
    return {"class": "escalation" if reasons else "routine", "reasons": sorted(reasons)}
