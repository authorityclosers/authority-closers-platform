"""Prepare an audited practice catalog activation receipt.

The checked-in exercise library is editorial draft content. This command does
not publish it or mutate a database. It validates an externally reviewed
questionbank and daily-selection policy, then writes a deterministic receipt
that the normal release controller can carry to staging or production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import UUID


class PracticeActivationError(ValueError):
    """The reviewed activation bundle is incomplete or not yet approved."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PracticeActivationError("practice activation input is unavailable") from error
    if not isinstance(value, dict):
        raise PracticeActivationError("practice activation input must be a JSON object")
    return value


def _digest(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PracticeActivationError(f"{label} is required")
    return value.strip()


def validate_bundle(
    catalog: dict[str, Any],
    policy: dict[str, Any],
    *,
    environment: str,
    tenant_id: UUID,
    allow_production: bool = False,
) -> dict[str, Any]:
    """Validate a reviewed bundle without changing runtime or database state."""

    target = environment.strip().lower()
    if target not in {"staging", "production"}:
        raise PracticeActivationError("practice activation target must be staging or production")
    if target == "production" and not allow_production:
        raise PracticeActivationError("production preparation requires --allow-production")
    if tenant_id.int == 0:
        raise PracticeActivationError("practice activation requires a non-zero tenant id")
    if _required_text(catalog.get("status"), "questionbank status").lower() != "published":
        raise PracticeActivationError("questionbank is not published; Dipak review is required")
    if _required_text(policy.get("status"), "daily-selection policy status").lower() != "approved":
        raise PracticeActivationError("daily-selection policy is not approved")

    sets = catalog.get("sets")
    if not isinstance(sets, list) or not sets:
        raise PracticeActivationError("questionbank must contain at least one set")
    set_by_id: dict[str, dict[str, Any]] = {}
    for value in sets:
        if not isinstance(value, dict):
            raise PracticeActivationError("questionbank set is invalid")
        set_id = _required_text(value.get("id"), "questionbank set id")
        if set_id in set_by_id:
            raise PracticeActivationError("questionbank contains duplicate set ids")
        if (
            _required_text(value.get("review_status"), f"review status for {set_id}").lower()
            != "approved"
        ):
            raise PracticeActivationError("questionbank contains an unapproved set")
        if (
            value.get("competition_eligible") is not False
            or value.get("assessment_eligible") is not False
        ):
            raise PracticeActivationError(
                "practice activation cannot enable competition or assessment"
            )
        set_by_id[set_id] = value

    language_rows = policy.get("languages")
    if not isinstance(language_rows, list) or not language_rows:
        raise PracticeActivationError("daily-selection policy must define languages")
    languages: list[dict[str, str]] = []
    seen_languages: set[str] = set()
    for value in language_rows:
        if not isinstance(value, dict):
            raise PracticeActivationError("daily-selection language entry is invalid")
        language_id = _required_text(value.get("id"), "daily-selection language id")
        label = _required_text(value.get("label"), f"label for {language_id}")
        set_id = _required_text(value.get("set_id"), f"set id for {language_id}")
        if language_id in seen_languages or set_id not in set_by_id:
            raise PracticeActivationError(
                "daily-selection policy references a missing or duplicate entry"
            )
        seen_languages.add(language_id)
        languages.append({"id": language_id, "label": label, "set_id": set_id})

    return {
        "schema_version": "practice-activation-receipt-v1",
        "environment": target,
        "tenant_id": str(tenant_id),
        "questionbank_digest": _digest(catalog),
        "daily_selection_policy_digest": _digest(policy),
        "set_ids": sorted(set_by_id),
        "languages": languages,
        "activation": "prepared",
        "database_mutated": False,
    }


def prepare_receipt(
    *,
    catalog_path: Path,
    policy_path: Path,
    output_path: Path,
    environment: str,
    tenant_id: UUID,
    allow_production: bool = False,
) -> dict[str, Any]:
    receipt = validate_bundle(
        _read_json(catalog_path),
        _read_json(policy_path),
        environment=environment,
        tenant_id=tenant_id,
        allow_production=allow_production,
    )
    encoded = json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if output_path.exists():
        try:
            if output_path.read_text("utf-8") == encoded:
                return {**receipt, "receipt_status": "already_prepared"}
        except OSError as error:
            raise PracticeActivationError("practice activation receipt is unavailable") from error
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    try:
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        os.replace(temporary, output_path)
    except OSError as error:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise PracticeActivationError("practice activation receipt could not be written") from error
    return {**receipt, "receipt_status": "prepared"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--allow-production", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        result = prepare_receipt(
            catalog_path=args.catalog,
            policy_path=args.policy,
            output_path=args.output,
            environment=args.environment,
            tenant_id=args.tenant_id,
            allow_production=args.allow_production,
        )
    except (PracticeActivationError, OSError, ValueError):
        print(
            "practice activation refused: reviewed inputs are unavailable or incomplete",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PracticeActivationError", "main", "prepare_receipt", "validate_bundle"]
