"""Pure, fail-closed path classification; M1a grants no merge/action authority."""

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


def _valid_path(path: object) -> bool:
    return (
        isinstance(path, str)
        and bool(path)
        and path == path.strip()
        and "\\" not in path
        and not any(ord(char) < 32 or ord(char) == 127 for char in path)
        and all(part not in {"", ".", ".."} for part in path.split("/"))
    )


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
        or name.startswith("dockerfile.")
        or name.endswith(".dockerfile")
        or ("compose" in name and name.endswith((".yaml", ".yml", ".json")))
    ):
        reasons.add("protected:deployment")
    if ".env" in lower or "secret" in lower or "infisical" in lower:
        reasons.add("protected:secrets")
    reasons.update(f"protected:name:{term}" for term in _TERMS if term in lower)
    if lower.startswith("db/migrations/"):
        reasons.add("protected:migration")
    if lower == "scripts/ci/merge_class.py":
        reasons.add("protected:classifier")
    return reasons


def classify_changed_files(
    files: object, contents: object, *, changed_files: object, truncated: bool = False
) -> dict[str, object]:
    """Classify GitHub records and supplied head strings without any external IO.

    The caller owns head pinning. Require a string for every surviving filename;
    removed files have no head content. Unsupported statuses and noncanonical
    paths fail closed. Contents are never parsed or executed, including migrations.
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
            reasons.update(_path_reasons(path))
        if (
            isinstance(filename, str)
            and status != "removed"
            and not isinstance(contents.get(filename), str)
        ):
            reasons.add("evidence:contents")
    return {"class": "escalation" if reasons else "routine", "reasons": sorted(reasons)}
