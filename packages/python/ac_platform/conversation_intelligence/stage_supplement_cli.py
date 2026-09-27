"""Prepare one reviewed exact-source hosted-stage supplement bundle.

This command only builds a new approval artifact. It never activates a bundle,
updates runtime state, or contacts a provider. Store inputs and output only in
the approved private operator directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from ac_platform.conversation_intelligence.activation_contract import (
    MAX_APPROVAL_BUNDLE_BYTES,
    StageCallSupplement,
    load_hosted_approval_bundle,
)

MAX_SUPPLEMENT_BYTES = 16_384


class CommandError(ValueError):
    """Safe operator-facing command validation failure."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise CommandError("Invalid arguments; use --help for the command contract.")


def parser() -> argparse.ArgumentParser:
    command = _Parser(description=__doc__, allow_abbrev=False)
    command.add_argument("--bundle", required=True, type=Path)
    command.add_argument("--supplement", required=True, type=Path)
    command.add_argument("--out", required=True, type=Path)
    return command


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def prepare_bundle(
    bundle_raw: bytes,
    supplement_raw: bytes,
    *,
    now_epoch: int,
) -> bytes:
    """Append exactly one active, validated grant without altering its base policy."""

    if not 0 < len(bundle_raw) <= MAX_APPROVAL_BUNDLE_BYTES:
        raise CommandError("The approval bundle is outside the supported size limit.")
    if not 0 < len(supplement_raw) <= MAX_SUPPLEMENT_BYTES:
        raise CommandError("The supplement is outside the supported size limit.")
    bundle = load_hosted_approval_bundle(bundle_raw)
    if bundle.stage_call_supplements:
        raise CommandError("Prepare one grant per reviewed bundle revision.")
    try:
        payload = json.loads(
            supplement_raw.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        if not isinstance(payload, dict):
            raise ValueError("supplement_object_required")
        supplement = StageCallSupplement.model_validate_json(supplement_raw)
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError, TypeError):
        raise CommandError("The supplement does not match the bounded grant contract.") from None
    if not supplement.issued_at_epoch <= now_epoch < supplement.expires_at_epoch:
        raise CommandError("The supplement must be active when prepared.")
    try:
        combined = load_hosted_approval_bundle(
            {**bundle.as_dict(), "stage_call_supplements": [supplement.model_dump(mode="json")]}
        )
    except (ValueError, TypeError):
        raise CommandError("The supplement does not match the current approval bundle.") from None
    return combined.to_json()


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.bundle.resolve() == args.out.resolve():
            raise CommandError("Output must be a new artifact path.")
        bundle_raw = args.bundle.read_bytes()
        supplement_raw = args.supplement.read_bytes()
        prepared = prepare_bundle(bundle_raw, supplement_raw, now_epoch=int(time.time()))
        # Exclusive creation prevents replacing a previously reviewed artifact.
        with args.out.open("xb") as stream:
            stream.write(prepared)
        bundle = load_hosted_approval_bundle(prepared)
        print(f"prepared approval digest: {bundle.digest}")
        print("supplements: 1; active: false")
        return 0
    except CommandError as exc:
        print(f"Stage supplement refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # File-system and validation exceptions may contain private input paths.
        print("Stage supplement preparation failed; no approval was activated.", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised by command wrapper.
    raise SystemExit(main())
