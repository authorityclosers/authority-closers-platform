"""Durable analytics recovery/heartbeat. Backfill is dry-run unless --apply is explicit."""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.learning.planning_repository import (
    AnalyticsEventReplayConflict,
    PlanningRepository,
)
from ac_platform.telemetry.durable import FIELDS, root_for
from ac_platform.telemetry.heartbeat import evaluate, snapshot
from ac_platform.telemetry.sales_xray_consent import read_standing


def backfill(session: Session, path: Path, *, now: datetime, limit: int = 20000) -> dict[str, int]:
    """Replay observations idempotently; current opt-outs and original expiry always win."""
    from ac_platform.http.telemetry import _stored_today
    from ac_platform.telemetry.sales_xray import PERSON_DAILY_CAP

    counts = {"stored": 0, "duplicate": 0, "skipped": 0, "conflicts": 0}
    opener = gzip.open if path.suffix == ".gz" else open
    repository = PlanningRepository()
    with opener(path, "rt") as handle:
        for line in handle:
            batch = json.loads(line)
            if batch["schema"] != "ac-telemetry-raw/1":
                raise ValueError("unknown journal schema")
            for source in batch["events"]:
                if counts["stored"] + counts["duplicate"] >= limit:
                    return counts
                if set(source) != set(FIELDS):
                    raise ValueError("invalid journal fields")
                values = dict(source)
                for field in (
                    "created_at",
                    "occurred_at",
                    "consent_captured_at",
                    "retention_expires_at",
                ):
                    values[field] = datetime.fromisoformat(values[field])
                for field in ("tenant_id", "actor_person_id", "subject_person_id"):
                    values[field] = UUID(values[field])
                standing = read_standing(
                    session, tenant_id=values["tenant_id"], person_id=values["subject_person_id"]
                )
                if (
                    values["retention_expires_at"] <= now
                    or not standing.collecting
                    or _stored_today(
                        session,
                        tenant_id=values["tenant_id"],
                        person_id=values["subject_person_id"],
                        now=now,
                    )
                    >= PERSON_DAILY_CAP
                ):
                    counts["skipped"] += 1
                    continue
                try:
                    with session.begin_nested():
                        existing = session.scalar(
                            select(AnalyticsEvent).where(
                                AnalyticsEvent.tenant_id == values["tenant_id"],
                                AnalyticsEvent.event_id == values["event_id"],
                            )
                        )
                        # The raw copy intentionally precedes optional server-only
                        # call-reference enrichment. Preserve that enrichment when
                        # comparing an existing row; every other immutable field
                        # still passes the repository's normal replay comparison.
                        if existing is not None and "call_ref" in existing.payload:
                            values["payload"] = {
                                **values["payload"],
                                "call_ref": existing.payload["call_ref"],
                            }
                        stored, duplicate, _ = repository.add_analytics_events(
                            session, [AnalyticsEvent(**values)]
                        )
                        session.flush()
                except AnalyticsEventReplayConflict:
                    counts["conflicts"] += 1
                    continue
                counts["stored"] += stored
                counts["duplicate"] += duplicate
    return counts


def heartbeat(root: Path, status: Path) -> dict[str, Any]:
    now = datetime.now(UTC)
    numbers = snapshot(root)
    problems = evaluate(numbers)
    # Never call a never-started counter stream healthy.
    if numbers["complete_buckets"] == 0:
        problems.append("Telemetry traffic counters unavailable")
    result = {
        "time": now.isoformat(),
        "environment": "production",
        "active": bool(problems),
        "problems": problems,
        "numbers": numbers,
    }
    status.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = status.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, sort_keys=True) + "\n")
    temporary.chmod(0o644)
    temporary.replace(status)
    print("telemetry-heartbeat " + json.dumps(result, sort_keys=True), flush=True)
    if problems:
        request = {
            "marker": "orch:telemetry-heartbeat",
            "fields": {
                "title": "Telemetry intake heartbeat alarm",
                "notes": "orch:telemetry-heartbeat\n" + json.dumps(result, sort_keys=True),
            },
        }
        completed = subprocess.run(  # noqa: S603 - fixed root-owned tool; no shell
            ["/usr/local/bin/ac-pulse-tasks", "ensure", json.dumps(request)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode:
            print("telemetry-heartbeat HQ task update failed; alarm remains active", flush=True)
            raise RuntimeError("HQ task update failed")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    alarm = commands.add_parser("heartbeat")
    alarm.add_argument("--root", type=Path, default=root_for("production"))
    alarm.add_argument(
        "--status", type=Path, default=Path("/var/lib/ac-telemetry-heartbeat/status.json")
    )
    replay = commands.add_parser("backfill")
    replay.add_argument("--file", type=Path, required=True)
    replay.add_argument("--database-url-file", type=Path, required=True)
    replay.add_argument("--apply", action="store_true")
    replay.add_argument("--limit", type=int, default=20000)
    args = parser.parse_args(argv)
    try:
        if args.command == "heartbeat":
            heartbeat(args.root, args.status)
            return 0
        url = make_url(args.database_url_file.read_text().strip())
        if url.get_backend_name() != "postgresql" or not 1 <= args.limit <= 20000:
            raise ValueError("invalid backfill configuration")
        engine = create_engine(url.set(drivername="postgresql+psycopg"), hide_parameters=True)
        try:
            with Session(engine) as session, session.begin():
                result = backfill(session, args.file, now=datetime.now(UTC), limit=args.limit)
                if not args.apply:
                    session.rollback()
            print(json.dumps({"applied": args.apply, **result}))
        finally:
            engine.dispose()
        return 0
    except Exception:
        # SQL/provider errors may include values. Never echo them.
        print('{"error":"telemetry operation failed; raw data retained"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
