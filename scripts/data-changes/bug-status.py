"""Set bug reports' status by their numbers, as Admin's form does (approved data change).

Owner, 26 Oct 2026 (through the orchestrator): Admin's Save does not persist in the owner's
browser, and that Admin is signed in as someone else, so a change made there would be
misattributed. This goes through BugReportStore.change, the function Admin's form calls
(POST /v1/admin/bugs/{id}/events). For each report it makes one status event, plus the note,
by the approver as staff, so Admin, the reporter's own list and the "Solved" corner card read
it exactly as from Admin. Then it writes one audit event per changed report, as Admin writes
it (bug_report.changed), naming the approver, the issue and the actor "Claude (orchestrator)".

Idempotent: a report already at that status is left alone (no event, no note, no audit), so a
rerun changes nothing. Every number must exist, or nothing changes. It runs in one
transaction:
- the dry run (the default) makes the change, prints before and after, and rolls it back;
- ``--apply`` commits;
- ``--read`` prints the reports' current status only.

Run inside the API container with the deployed settings. Its filesystem is read-only, so the
input goes inline. The script uses only code that v0.91 already has:
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < bug-status.py
input: {"numbers": [9, 16], "status": "fixed", "note": "...", "approver_email": "...",
        "issue"?: "..."}
It prints numbers, statuses and counts: never a report's words, its reporter or its
organisation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import AuditRepository
from ac_platform.bug_reports.models import STATUSES, BugReport
from ac_platform.bug_reports.store import BugReportRefused, BugReportStore
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership

Mode = Literal["dry-run", "apply", "read"]
ACTOR = "Claude (orchestrator)"


class Refused(ValueError):
    """The input or the approver cannot be used; nothing is changed."""


def spec_from(raw: str, mode: Mode) -> dict[str, Any]:
    """The input, checked: report numbers, and for a change the status and the approver."""
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        raise Refused("The input is not JSON.") from None
    numbers = spec.get("numbers") if isinstance(spec, dict) else None
    if (
        not isinstance(numbers, list)
        or not 1 <= len(numbers) <= 200
        or not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in numbers)
    ):
        raise Refused("numbers: 1 to 200 report numbers.")
    if mode == "read":
        return {"numbers": sorted(set(numbers))}
    status, email = spec.get("status"), spec.get("approver_email")
    if status not in STATUSES:
        raise Refused(f"status: one of {', '.join(STATUSES)}.")
    if not isinstance(email, str) or "@" not in email:
        raise Refused("approver_email: the approving staff member's email.")
    note, issue = spec.get("note"), spec.get("issue")
    if note is not None and not isinstance(note, str):
        raise Refused("note: text.")
    if issue is not None and not isinstance(issue, str):
        raise Refused("issue: text.")
    return {
        "numbers": sorted(set(numbers)),
        "status": status,
        "note": " ".join(note.split())[:2000] if note else None,
        "approver_email": email.strip().lower(),
        "issue": issue.strip()[:80] if issue else None,
    }


async def _approver(db: AsyncSession, email: str, operations_tenant_id: UUID) -> Person:
    """A verified, active person who is an owner or admin of the AC operations workspace."""
    person = await db.scalar(select(Person).where(func.lower(Person.email) == email))
    member = await db.get(Membership, (operations_tenant_id, person.id)) if person else None
    if (
        person is None
        or person.status != "active"
        or person.email_verified_at is None
        or member is None
        or member.status != "active"
        or member.ended_at is not None
        or member.role not in {"owner", "admin"}
    ):
        raise Refused(
            "The approver must be a verified, active owner or admin of the AC operations workspace."
        )
    return person


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    operations_tenant_id: UUID,
) -> dict[str, Any]:
    numbers: list[int] = spec["numbers"]
    rows = (
        await db.execute(
            select(BugReport.number, BugReport.id).where(BugReport.number.in_(numbers))
        )
    ).all()
    ids = {int(row.number): row.id for row in rows}
    store = BugReportStore(db)
    before = {n: (await store.state(ids[n]))["status"] for n in numbers if n in ids}
    report: dict[str, Any] = {
        "numbers": numbers,
        "missing": [n for n in numbers if n not in ids],
        "before": {str(n): status for n, status in before.items()},
    }
    if mode == "read":
        report["status"] = "read"
        return report
    if report["missing"]:
        raise Refused(f"No report numbered {', '.join(map(str, report['missing']))}.")
    approver = await _approver(db, spec["approver_email"], operations_tenant_id)
    run_id = uuid4()
    audit = AuditRepository(db)
    changed: list[int] = []
    for number in numbers:
        if before[number] == spec["status"]:
            continue
        try:
            added = await store.change(
                ids[number],
                actor_person_id=approver.id,
                now=now,
                status=spec["status"],
                note=spec["note"],
            )
        except BugReportRefused as error:
            raise Refused(f"#{number}: {error}") from None
        if not added:
            continue
        await audit.append(
            tenant_id=operations_tenant_id,
            actor_person_id=approver.id,
            action="bug_report.changed",
            resource_type="bug_report",
            resource_id=str(ids[number]),
            payload={
                "changed": added,
                "status": [before[number], spec["status"]],
                "note": bool(spec["note"]),
                "data_change": "scripts/data-changes/bug-status.py",
                "actor": ACTOR,
                "approver_email": spec["approver_email"],
                "issue": spec["issue"],
                "run_id": str(run_id),
            },
            reason=f"Owner-approved data change: bug status ({spec['issue'] or 'no issue'})",
            now=now,
        )
        changed.append(number)
    report.update(
        run_id=str(run_id),
        actor=ACTOR,
        approver_email=spec["approver_email"],
        target=spec["status"],
        changed=changed,
        unchanged=[n for n in numbers if n not in changed],
        after={str(n): (await store.state(ids[n]))["status"] for n in numbers},
        audit_events=len(changed),
        status="applied" if mode == "apply" else "rehearsed_and_rolled_back",
    )
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    operations_tenant_id: UUID,
) -> dict[str, Any]:
    """One transaction: committed on apply, rolled back otherwise."""
    async with sessions() as db:
        try:
            report = await run(
                db, spec, mode=mode, now=now, operations_tenant_id=operations_tenant_id
            )
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(raw: str, mode: Mode) -> int:
    try:
        spec = spec_from(raw, mode)
    except Refused as error:
        print(json.dumps({"refused": str(error)}))
        return 2
    settings = get_settings()
    if settings.operations_tenant_id is None:
        print(json.dumps({"refused": "The AC operations workspace is not configured."}))
        return 2
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            spec,
            mode=mode,
            now=datetime.now(UTC),
            operations_tenant_id=settings.operations_tenant_id,
        )
    except Refused as error:
        print(json.dumps({"refused": str(error)}))
        return 2
    finally:
        await engine.dispose()
    report["environment"] = settings.environment
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or flags - {"--apply", "--read"} or flags == {"--apply", "--read"}:
        raise SystemExit("usage: python - '<input JSON>' [--apply | --read] < bug-status.py")
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
