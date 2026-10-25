"""Repair form answers an import split inside numbers (approved data change, AUT-2223).

The import of 25 Oct 2026 (``import-leads-file.py`` before its fix) wrote a multi-select comma
rule that also put a space after the comma inside numbers: "₹15,000 – ₹30,000" was stored as
"₹15, 000 – ₹30, 000". This joins them again in the leads' form answers (the questions, which
end in "?"), in one transaction, for the leads whose label starts as given:
  - only a comma between digits loses its space ("15, 000" -> "15,000"); answers with words
    and other fields ("Received on the form": "19 May 2026, 20:16 IST") stay as they are;
  - the leads' history (a repeat's line with its answers) is history and stays as written;
  - one audit event naming the approver and the issue.
A dry run (the default) makes the repair in its transaction, reports it and rolls it back.
``--apply`` commits; a rerun finds nothing to repair and writes no audit event.

    docker exec -i <api> python - '<input JSON>' [--apply] < repair-import-answers.py
input: {"command_id", "tenant" (its id or first 8 characters), "label_prefix",
        "approver_email", "issue"}
Prints counts and question names only.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead

Mode = Literal["dry-run", "apply"]
ACTION: Final = "lead_desk.file_import_correction"
SPLIT: Final = re.compile(r"(\d), (?=\d)")


def joined(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The payload with numbers joined again in its answers, and the questions changed."""
    fixed = dict(payload)
    changed: list[str] = []
    for question, answer in payload.items():
        if question.endswith("?") and isinstance(answer, str) and SPLIT.search(answer):
            fixed[question] = SPLIT.sub(r"\1,", answer)
            changed.append(question)
    return fixed, changed


async def _tenant(db: AsyncSession, given: str) -> UUID:
    given = given.strip().lower()
    if len(given) == 36:
        return UUID(given)
    found = (
        (
            await db.execute(
                text("select id from tenants where cast(id as text) like :p order by id limit 2"),
                {"p": f"{given}%"},
            )
        )
        .scalars()
        .all()
    )
    if len(given) < 8 or len(found) != 1:
        raise SystemExit(json.dumps({"refused": "tenant_not_found_once"}))
    return UUID(str(found[0]))


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    prefix = str(spec["label_prefix"])
    if len(prefix) < 8:
        raise SystemExit(json.dumps({"refused": "label_prefix_too_short"}))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    approver: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found"}))
    leads = (
        await db.scalars(
            select(Lead)
            .where(Lead.tenant_id == tenant_id, Lead.source_label.startswith(prefix))
            .with_for_update()
        )
    ).all()
    questions: Counter[str] = Counter()
    repaired = 0
    for lead in leads:
        fixed, changed = joined(dict(lead.payload or {}))
        if not changed:
            continue
        lead.payload = fixed
        lead.updated_at = now
        repaired += 1
        questions.update(changed)
    await db.flush()
    report: dict[str, Any] = {
        "mode": mode,
        "tenant_id": str(tenant_id),
        "label_prefix": prefix,
        "leads": len(leads),
        "repaired": repaired,
        "questions": dict(questions),
        "audited": bool(repaired),
    }
    if repaired:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Correction: numbers in imported form answers joined again",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "label_prefix": prefix,
                "repaired": repaired,
                "questions": dict(questions),
            },
        )
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession], spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(db, spec, mode=mode, now=now)
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


async def main(raw: str, mode: Mode) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            dict(json.loads(raw)),
            mode=mode,
            now=datetime.now(UTC),
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(
        asyncio.run(main(args[0], "apply" if "--apply" in sys.argv[1:] else "dry-run"))
    )
