"""Correct the 16 Nov 2026 Nature Solutions lead import (approved data change).

The owner approved the import (Suyash, 16 Nov 2026, in chat to the orchestrator); this is a
correction of it, found by reading production:
  1. a sheet's header row went in as a lead ("Sr.No", in Interested). It is not deleted
     (deleting is the owner's call): it goes to history, Lost with the reason "Junk / not a
     real lead" (or Other) and the words "Imported header row, not a lead", given to nobody,
     so it is on no work list. Nobody's move: no actor, source "import";
  2. leads with no phone and no email whose own row (the lead's payload, as imported) holds
     one the import could not read:
       - a number written with the +1 country code before a ten-digit Indian mobile
         ("p:+1 98…", Meta's country picker): saved as +91 and the ten digits, with a note
         saying so;
       - an email typed into the name column: saved as the email (the name stays);
     anything else is left as it is and reported ("sheet_has_none"). A number already on
     another lead is never set twice: reported ("phone_on_another_lead") for a merge
     through the app's own merge path.
Phones and emails are set through the app's own edit (``LeadDesk.edit``: its phone rule and
its one-lead-per-number check), the notes through ``LeadDesk.note``, as "Data change".
One transaction; one audit event naming the approver; a rerun changes nothing.

A dry run (the default) makes every change in its transaction, reports it and rolls it
back. ``--apply`` commits. ``--read`` only reads.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < this file
input: {"command_id", "tenant" (its id or first 8 characters), "approver_email", "approver",
        "issue", "header_rows": [lead id or its first 8 characters, ...],
        "contacts": [lead id or its first 8 characters, ...]}
Prints lead ids (first 8 characters), counts and reasons only; never a name, number or email.
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

from sqlalchemy import String, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.capture import first_email, key
from ac_platform.lead_desk.contracts import LeadEdit, NoteCommand
from ac_platform.lead_desk.history import HISTORY
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import transitions
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.lead_desk.vocabulary import NOT_A_LEAD, OTHER_REASON

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.import_correction_data_change"
HEADER_WORDS: Final = "Imported header row, not a lead"
PHONE_AS_WRITTEN: Final = "Phone as written"
# A sheet's header cells that name a row, as the import's ``key`` spells them.
HEADER_NAMES: Final = frozenset({"sr_no", "s_no", "sl_no", "serial_no", "sr", "no"})


def plus_one_mobile(written: object) -> str | None:
    """A ten-digit Indian mobile written behind the +1 country code ("p:+1 98765 43210":
    the form's country picker left at +1), as +91 and the ten digits; else None."""
    if written is None:
        return None
    # Meta writes "p:"; the import keeps the cell readable, so it may read "P:".
    words = re.sub(r"^\s*p:\s*", "", str(written), flags=re.IGNORECASE).strip()
    if not words.startswith("+1") or re.search(r"[A-Za-z]", words):
        return None
    digits = re.sub(r"\D", "", words)
    if len(digits) == 11 and digits[1] in "6789":
        return "+91" + digits[1:]
    return None


def is_header_row(lead: Lead) -> bool:
    """A lead made from a sheet's header row: its name is a header cell ("Sr.No") and its
    row holds nothing but that name."""
    payload = lead.payload if isinstance(lead.payload, dict) else {}
    others = [name for name, value in payload.items() if str(value or "").strip()]
    return key(lead.name or "") in HEADER_NAMES and len(others) <= 1


def _input(path: str) -> dict[str, Any]:
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


async def _tenant(db: AsyncSession, given: str) -> UUID:
    given = given.strip().lower()
    if len(given) == 36:
        return UUID(given)
    found = (
        await db.execute(
            text("select id from tenants where cast(id as text) like :p order by id limit 2"),
            {"p": f"{given}%"},
        )
    ).scalars()
    rows = list(found)
    if len(given) < 8 or len(rows) != 1:
        raise SystemExit(json.dumps({"refused": "tenant_not_found_once"}))
    return UUID(str(rows[0]))


async def _lead(db: AsyncSession, tenant_id: UUID, given: str) -> Lead:
    """One lead of this organisation by its id or its id's first 8 characters, locked."""
    given = given.strip().lower()
    if len(given) < 8 or not re.fullmatch(r"[0-9a-f-]+", given):
        raise SystemExit(json.dumps({"refused": "lead_not_found_once", "lead": given[:8]}))
    found = (
        await db.scalars(
            select(Lead)
            .where(Lead.tenant_id == tenant_id, cast(Lead.id, String).like(f"{given}%"))
            .order_by(Lead.id)
            .limit(2)
            .with_for_update()
        )
    ).all()
    if len(found) != 1:
        raise SystemExit(json.dumps({"refused": "lead_not_found_once", "lead": given[:8]}))
    return found[0]


async def _readback(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    side = func.coalesce(Lead.pipeline, "live")
    rows = (
        await db.execute(
            select(
                side,
                Lead.stage,
                func.count(),
                func.count().filter(
                    func.coalesce(Lead.phone, "") == "", func.coalesce(Lead.email, "") == ""
                ),
                func.count().filter(Lead.owner_person_id.is_not(None)),
            )
            .where(Lead.tenant_id == tenant_id, Lead.merged_into_id.is_(None))
            .group_by(side, Lead.stage)
            .order_by(side, Lead.stage)
        )
    ).all()
    worked = [row for row in rows if row[0] != HISTORY]
    return {
        "by_side_stage": {f"{side}:{stage}": int(n) for side, stage, n, _, _ in rows},
        "live": sum(int(row[2]) for row in worked),
        "live_owned": sum(int(row[4]) for row in worked),
        "live_without_phone_or_email": sum(int(row[3]) for row in worked),
        "live_header_rows": int(
            await db.scalar(
                select(func.count()).where(
                    Lead.tenant_id == tenant_id,
                    Lead.merged_into_id.is_(None),
                    Lead.pipeline.is_distinct_from(HISTORY),
                    func.regexp_replace(func.lower(Lead.name), "[^a-z]", "", "g").in_(
                        ["srno", "sno", "slno", "serialno"]
                    ),
                )
            )
            or 0
        ),
    }


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    report: dict[str, Any] = {"mode": mode, "tenant_id": str(tenant_id)}
    if mode == "read":
        report["status"] = "read"
        report["after"] = await _readback(db, tenant_id)
        return report
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found", **report}))
    report["before"] = await _readback(db, tenant_id)
    desk = LeadDesk(
        db,
        Viewer(person_id=approver.id, tenant_id=tenant_id, role="owner", name="Data change"),
        now=now,
    )
    journey = await journeys.read(db, tenant_id, journeys.MAIN_PIPELINE)
    lost = next(
        (stage for stage in journey.stages if stage.kind == "lost" and not stage.archived), None
    )
    if lost is None:
        raise SystemExit(json.dumps({"refused": "no_lost_stage", **report}))
    listed = dict(transitions.reasons_of(lost))
    reason = NOT_A_LEAD if NOT_A_LEAD in listed else OTHER_REASON
    counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []

    for given in spec.get("header_rows") or []:
        lead = await _lead(db, tenant_id, str(given))
        if not is_header_row(lead):
            raise SystemExit(json.dumps({"refused": "not_a_header_row", "lead": str(lead.id)[:8]}))
        step = uuid5(command_id, f"{lead.id}:header")
        done: list[str] = []
        if lead.stage != "lost" or lead.step != lost.key:
            move = desk._check(
                journey,
                lead,
                lost.key,
                transitions.Given(reason=reason, reason_note=HEADER_WORDS),
                source="import",
            )
            desk._move(
                lead,
                journey,
                move,
                source="import",
                via="api",
                command_id=uuid5(step, "stage"),
                outcome_reason=reason,
                reason_note=HEADER_WORDS,
                note=HEADER_WORDS,
                actor=None,
            )
            done.append("lost")
        if lead.owner_person_id is not None:
            await desk._set_owner(
                lead, None, HEADER_WORDS, "data_change", actor=None, command_id=uuid5(step, "owner")
            )
            done.append("unassigned")
        if lead.pipeline != HISTORY:
            # Last: an event written on a history lead by someone would bring it back.
            lead.pipeline = HISTORY
            lead.next_action_at = None
            lead.next_action_note = None
            done.append("history")
        counts["header_closed" if done else "header_already_closed"] += 1
        results.append({"lead": str(lead.id)[:8], "kind": "header_row", "done": done})
    await db.flush()

    for given in spec.get("contacts") or []:
        lead = await _lead(db, tenant_id, str(given))
        payload = lead.payload if isinstance(lead.payload, dict) else {}
        phone = None if lead.phone else plus_one_mobile(payload.get(PHONE_AS_WRITTEN))
        email = None if lead.email else first_email(lead.name)
        entry: dict[str, Any] = {"lead": str(lead.id)[:8], "kind": "contact"}
        if lead.pipeline == HISTORY or lead.merged_into_id is not None:
            entry["result"] = "not_live"
        elif phone is None and email is None:
            entry["result"] = (
                "already_has_contact" if lead.phone or lead.email else "sheet_has_none"
            )
        else:
            if phone is not None:
                other = await db.scalar(
                    select(Lead.id).where(
                        Lead.tenant_id == tenant_id, Lead.phone == phone, Lead.id != lead.id
                    )
                )
                if other is not None:
                    entry["phone_on_another_lead"] = str(other)[:8]
                    counts["phone_on_another_lead"] += 1
                    phone = None
            if phone is None and email is None:
                entry["result"] = "left_for_merge"
            else:
                step = uuid5(command_id, f"{lead.id}:contact")
                await desk.edit(
                    lead.id,
                    LeadEdit(
                        command_id=step,
                        expected_revision=lead.revision,
                        phone=phone,
                        email=email,
                    ),
                )
                words = []
                if phone is not None:
                    words.append(
                        "The number was written with the +1 country code in the sheet; "
                        "saved with India's +91 for calling (the number as written is kept)."
                    )
                if email is not None:
                    words.append("The email was written in the name column; saved as the email.")
                await desk.note(
                    lead.id,
                    NoteCommand(
                        command_id=uuid5(step, "note"),
                        note="Import corrected (16 Nov 2026): " + " ".join(words),
                    ),
                )
                entry["result"] = "set"
                entry["set"] = [n for n, v in (("phone", phone), ("email", email)) if v]
                for name in entry["set"]:
                    counts[f"{name}_set"] += 1
        counts[entry["result"]] += 1
        results.append(entry)
    await db.flush()

    changed = counts["header_closed"] + counts["set"]
    report["audited"] = bool(changed)
    if changed:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner-approved correction of a lead import",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "approver": spec.get("approver"),
                "counts": dict(counts),
                "leads": results,
            },
        )
    report["counts"] = dict(counts)
    report["leads"] = results
    report["after"] = await _readback(db, tenant_id)
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


async def main(path: str, mode: Mode) -> int:
    engine = create_async_engine(get_settings().database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    chosen: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    raise SystemExit(asyncio.run(main(args[0], chosen)))
