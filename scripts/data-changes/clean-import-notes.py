"""Clean a sheet import's notes down to the seller's own words (approved data change).

Owner, 17 Nov 2026 (Shivam Patil's review of Wise Life and iSolar, section C1, through the
orchestrator): notes such as "Call notes in the sheet (New Sheet CAmp tab): ..." came from our
import, not from the sellers. Keep only what the seller wrote in the sheet, with its date;
take the importer's labels and directions out of the note text.

Notes are history, so nothing is rewritten or deleted. The app's own supersede path
(``LeadDesk.undo_app_change``: an "edited" marker naming the note, which every notes list,
the lead page and the activity counts leave out; the history keeps both) hides the importer's
note, and, where the seller wrote something, a new note with just those words takes its place,
dated as the original was (or on the day the words name, "didn't answer 17 sep"). In one
transaction, for every note an import wrote (``source: "import"``) in the workspace:
  - "Call notes in the sheet (<tab> tab): <words>"        -> <words>, dated by the words if
                                                             they name a day, else as before;
  - "Remark in the EPC outbound sheet: <words>"           -> <words>, its date kept;
  - "Call status in the EPC outbound sheet: <words>"      -> <words>, its date kept;
  - "From the sheet (<tab> tab): <Column: value> · ..."  -> hidden when the lead's details
    already hold every value (a new lead keeps them as "<Column> (sheet)"); otherwise the
    column values alone, without the label or "(not a member of this workspace)";
  - "Also in the <book> sheet's <tab> tab..."             -> hidden (the importer's own
    comparison of two rows; the rows stay on the lead's history);
  - anything else, and every note a person wrote, stays as it is.
The leads are not touched otherwise: no stage, owner, "last updated" or revision changes, no
bell, nothing sent to Meta or a partner app (an "edited" marker and an imported note are never
conversions). One audit event names the approver, the issue and every note it superseded.

A dry run (the default) makes the whole change in its transaction, reports it and rolls it
back. ``--apply`` commits; a rerun changes nothing (each note's marker and replacement have
their own command ids). ``--read`` counts the importer's notes still showing.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < clean-import-notes.py
input: {"command_id", "tenant" (its id or first 8 characters), "approver_email", "approver",
        "issue", "examples"? (how many before -> after pairs to print, digits and e-mails
        masked)}
Prints counts and note id prefixes only; examples only when asked, masked.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import UNDO_OF, LeadDesk, Viewer

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.import_notes_cleaned_data_change"
# The importer's labels (build_spec for Wise Life and iSolar, 17 Nov 2026), each with what
# becomes of the note.
WORDS: Final = (
    ("call_notes", re.compile(r"^Call notes in the sheet \([^)]*\btab\): ", re.S)),
    ("epc_remark", re.compile(r"^Remark in the EPC outbound sheet: ", re.S)),
    ("epc_status", re.compile(r"^Call status in the EPC outbound sheet: ", re.S)),
)
FROM_SHEET: Final = re.compile(r"^From the sheet \([^)]*\btab\): ", re.S)
ALSO_IN: Final = re.compile(r"^Also in the .+? sheet's .+? tab\b", re.S)
NOT_MEMBER: Final = " (not a member of this workspace)"
SELLER: Final = "Seller in the sheet"
MONTHS: Final = {
    m: i + 1
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    )
}
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
DAY_MONTH: Final = re.compile(
    r"(?<![\w.])(\d{1,2})(?:st|nd|rd|th)?\s*-?\s*" + _MONTH + r"(?![a-z])", re.I
)
MONTH_DAY: Final = re.compile(r"(?<![a-z])" + _MONTH + r"\s*-?\s*(\d{1,2})(?!\d)", re.I)
# Noon in India, as the import dated the EPC remarks.
NOON_UTC: Final = (6, 30)


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


def named_day(words: str, *, before: datetime) -> datetime | None:
    """The latest day the seller's words name ("17 sep", "Nov16"), at noon in India, if it
    is not after the note itself; else None."""
    days: list[datetime] = []
    for match in DAY_MONTH.finditer(words):
        days.extend(_day(int(match.group(1)), match.group(2), before))
    for match in MONTH_DAY.finditer(words):
        days.extend(_day(int(match.group(2)), match.group(1), before))
    return max(days) if days else None


def _day(day: int, month: str, before: datetime) -> list[datetime]:
    number = MONTHS[month[:3].lower()]
    try:
        at = datetime(before.year, number, day, *NOON_UTC, tzinfo=UTC)
    except ValueError:
        return []
    if at > before:
        try:
            at = at.replace(year=before.year - 1)
        except ValueError:
            return []
    # A day more than a year back is no day the sheet meant.
    return [at] if before - at <= timedelta(days=366) else []


def _held(payload: dict[str, Any], column: str, value: str) -> bool:
    keys = (SELLER,) if column == SELLER else (f"{column} (sheet)", f"{column} (₹, sheet)")
    return any(str(payload.get(k) or "").strip().lower() == value.strip().lower() for k in keys)


def cleaned(
    note: str, created_at: datetime, payload: dict[str, Any]
) -> tuple[str, str | None, datetime]:
    """What becomes of one imported note: (kind, the words to keep or None to hide, when).
    Kind "keep" leaves it as it is."""
    for kind, label in WORDS:
        found = label.match(note)
        if found:
            words = note[found.end() :].strip()
            at = created_at
            if kind == "call_notes":
                at = named_day(words, before=created_at) or created_at
            return kind, words or None, at
    found = FROM_SHEET.match(note)
    if found:
        items = [item.strip() for item in note[found.end() :].split(" · ") if item.strip()]
        pairs: list[tuple[str, str]] = []
        for item in items:
            column, _, value = item.partition(": ")
            if value.endswith(NOT_MEMBER):
                value = value[: -len(NOT_MEMBER)]
            pairs.append((column.strip(), value.strip()))
        if all(_held(payload, column, value) for column, value in pairs):
            return "from_sheet", None, created_at
        return "from_sheet", " · ".join(f"{c}: {v}" for c, v in pairs) or None, created_at
    if ALSO_IN.match(note):
        return "also_in", None, created_at
    return "keep", note, created_at


def _masked(words: str) -> str:
    words = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<e-mail>", words)
    return re.sub(r"\d{6,}", lambda m: "#" * len(m.group(0)), words)[:160]


async def _imported(db: AsyncSession, tenant_id: UUID) -> list[LeadEvent]:
    return list(
        (
            await db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.kind == "note",
                    LeadEvent.data["source"].as_string() == "import",
                )
                .order_by(LeadEvent.created_at, LeadEvent.id)
            )
        ).all()
    )


async def _showing(desk: LeadDesk, notes: list[LeadEvent]) -> list[LeadEvent]:
    gone = await desk._undone(str(note.id) for note in notes)
    return [note for note in notes if str(note.id) not in gone]


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    report: dict[str, Any] = {"mode": mode, "tenant_id": str(tenant_id)}
    approver: Person | None = await db.scalar(
        select(Person).where(
            func.lower(Person.email) == str(spec["approver_email"]).strip().lower()
        )
    )
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found", **report}))
    desk = LeadDesk(
        db,
        Viewer(person_id=approver.id, tenant_id=tenant_id, role="owner", name="Data change"),
        now=now,
    )
    notes = await _showing(desk, await _imported(db, tenant_id))
    found = select(Lead).where(Lead.tenant_id == tenant_id, Lead.id.in_({n.lead_id for n in notes}))
    # A read takes no lock (its transaction is read-only); a change locks the leads.
    if mode != "read":
        found = found.with_for_update()
    leads = {lead.id: lead for lead in (await db.scalars(found)).all()} if notes else {}
    plan = []
    for note in notes:
        data = note.data if isinstance(note.data, dict) else {}
        lead = leads[note.lead_id]
        payload = lead.payload if isinstance(lead.payload, dict) else {}
        kind, words, at = cleaned(str(data.get("note") or ""), note.created_at, payload)
        plan.append((note, lead, kind, words, at))
    before = Counter(kind for _, _, kind, _, _ in plan)
    report["before"] = {"imported_notes_showing": len(plan), "by_kind": dict(before)}
    if mode == "read":
        report["status"] = "read"
        return report
    counts: Counter[str] = Counter()
    superseded: list[str] = []
    examples: list[dict[str, str]] = []
    wanted = int(spec.get("examples") or 0)
    for note, lead, kind, words, at in plan:
        if kind == "keep":
            counts["kept"] += 1
            continue
        hide = uuid5(command_id, f"hide:{note.id}")
        if await desk._command_seen(hide) is not None:
            counts["done_before"] += 1
            continue
        # The app's supersede: a marker naming the note (undo_app_change); the history keeps
        # both. "source: import" keeps an old lead kept as history where it is.
        desk._event(
            lead,
            "edited",
            {
                UNDO_OF: str(note.id),
                "change": str(command_id),
                "source": "import",
                "reason": "import_note_cleaned",
            },
            actor=note.actor_person_id,
            command_id=hide,
        )
        superseded.append(str(note.id))
        if words:
            desk._event(
                lead,
                "note",
                {"note": words[:2000], "source": "import", "supersedes": str(note.id)},
                actor=note.actor_person_id,
                command_id=uuid5(command_id, f"note:{note.id}"),
                at=at,
            )
            counts[f"{kind}:words_kept"] += 1
            if at != note.created_at:
                counts[f"{kind}:dated_by_words"] += 1
        else:
            counts[f"{kind}:hidden"] += 1
        if len(examples) < wanted and (kind, words is None) not in {
            (e["kind"], e["after"] == "(hidden)") for e in examples
        }:
            examples.append(
                {
                    "kind": kind,
                    "before": f"{note.created_at:%d %b %H:%M}Z · "
                    + _masked(str(note.data.get("note"))),
                    "after": f"{at:%d %b %H:%M}Z · {_masked(words)}" if words else "(hidden)",
                }
            )
    await db.flush()
    report["counts"] = dict(counts)
    report["superseded"] = len(superseded)
    report["superseded_first"] = [i[:8] for i in superseded[:10]]
    if examples:
        report["examples"] = examples
    report["audited"] = bool(superseded)
    if superseded:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner request: imported notes keep only the seller's own words",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "approver": spec.get("approver"),
                "superseded_note_ids": superseded,
                "counts": dict(counts),
            },
        )
    after = await _showing(desk, await _imported(db, tenant_id))
    report["after"] = {
        "imported_notes_showing": len(after),
        "importer_labels_showing": sum(
            1
            for note in after
            if cleaned(str(note.data.get("note") or ""), note.created_at, {})[0] != "keep"
        ),
    }
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
