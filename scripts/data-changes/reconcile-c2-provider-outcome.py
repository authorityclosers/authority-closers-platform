#!/usr/bin/env python3
"""Record reviewed, exact C2 outcome evidence; dry-run by default, never retry."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.provider_reconciliation import (
    C2OutcomeEvidence,
    record_c2_outcome,
)


async def execute(
    settings: Settings,
    proof: C2OutcomeEvidence,
    *,
    apply: bool,
    snapshot_sha256: str | None,
) -> dict[str, Any]:
    if proof.environment != settings.environment:
        raise ValueError("environment_mismatch")
    if (
        apply
        and settings.environment == "production"
        and (snapshot_sha256 is None or re.fullmatch(r"[a-f0-9]{64}", snapshot_sha256) is None)
    ):
        raise ValueError("production_snapshot_required")
    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db, db.begin():
            result = await record_c2_outcome(
                db, proof, environment=settings.environment, now=datetime.now(UTC), apply=apply
            )
            return {**result, "production_snapshot_sha256": snapshot_sha256}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--production-snapshot-sha256")
    args = parser.parse_args()
    try:
        if args.evidence.is_symlink() or not 0 < args.evidence.stat().st_size <= 16_384:
            raise ValueError("evidence_invalid")
        raw = args.evidence.read_bytes()
        if hashlib.sha256(raw).hexdigest() != args.evidence_sha256:
            raise ValueError("evidence_digest_mismatch")
        proof = C2OutcomeEvidence.model_validate_json(raw)
        # Runtime injection only; no server secret files or provider access.
        result = asyncio.run(
            execute(
                Settings(), proof, apply=args.apply, snapshot_sha256=args.production_snapshot_sha256
            )
        )
    except Exception:
        parser.exit(2, "C2 reconciliation refused; credentials and evidence contents withheld.\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
