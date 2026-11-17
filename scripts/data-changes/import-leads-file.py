"""Import a workbook's leads into one organisation for one seller (approved data change).

Owner, 25 Oct 2026 (through the orchestrator, AUT-2223): a Meta lead form's export, "our own
leads", every tab of it, added to the Authority Closers organisation and given to one seller.
The same path as the app's own file import (``Intake.commit``: ``LeadDesk.ingest`` per row, the
original row kept as the lead's payload, ``content_ref`` so a rerun adds nothing), in one
transaction:
  1. each tab is a batch with its own label and pipeline (and fields to add, such as "Lead
     type: Business owner"); all rows go in the order they were received, so a phone that
     is in two tabs becomes one lead from its first row, and the later row is a repeat of it
     (one history line with its answers), which keeps its owner;
  2. each row's form answers are made readable ("sales_job_/_business_development" is "Sales
     job / business development", the question "What do you currently do?"), its form time
     kept beside them as "Received on the form" (India time; a date typed into the sheet is
     read and marked), numbers stored as numbers become text ("919876543210", a city's PIN),
     and the city is tidied for the lead with what was written kept;
  3. a row without a phone match whose email is already a lead's is counted and left out;
  4. every new lead goes to the seller, in its batch's pipeline, at its first stage;
  5. one audit event naming the approver and the issue.
A batch may also say its ``side`` ("live", "cold", or "history": old leads kept out of every
work list and given to nobody, as the app's own history import does) and its ``stage`` (a key
of the pipeline's stage list); a row may say its own ``_stage`` and carry ``_notes`` (its
history from the sheet: ``[{"text", "at"?}]``, dated when the sheet dates it). An imported
stage is nobody's move today (no actor, source "import"); a Lost one reads "Imported". A row's
notes go on its lead whether the row made it or repeated it. ``actor_email`` (default: the
approver) is the person the leads' history names, e.g. a workspace's owner whose own sheet it
is; the audit event still names the approver (and ``approver``, the words of the approval).
A batch may say ``"assign": "none"``: its new leads wait in the no-owner pool, whatever the
side (Wise Life and iSolar, 17 Nov 2026: the sheets name no seller who is on the team; the
owner gives them out). With no batch for a seller, ``seller_email`` may be left out. A batch
may say ``"merge": "existing"``: each row must be a lead already here (by phone, else email);
the lead comes back as it is (no "asked again", no new owner, no move to To call), the row's
notes go on it, and the row's own ``_stage`` is set only while the lead is still at its
pipeline's first stage, so a lead someone has worked is never moved. A row with no lead here is
counted (``not_here``) and left out. A new lead keeps its form time (``created_time``) as when
it was received.
Nothing is sent to any lead. The source is "csv" with the label given: imports never reach
Meta's conversions API, which only sends leads Meta delivered.

A dry run (the default) makes the whole import in its transaction, reports it and rolls it
back. ``--apply`` commits; a rerun adds nothing. ``--read`` reads the result back.

Run inside the API container with the deployed settings (its filesystem is read-only, so the
input goes inline):
    docker exec -i <api> python - '<input JSON>' [--apply | --read] < import-leads-file.py
input: {"command_id", "tenant" (its id or first 8 characters), "seller_email",
        "approver_email", "issue", "mapping": {"name": header, "phone": header, "email": header,
        "city": header?}, "batches": [{"label", "pipeline" (key or name), "rows": [...],
        "add": {field: value}?}, ...]}
Prints counts, row numbers and masked emails only; never a lead's name, number or email.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.capture import ALIASES, extract, key
from ac_platform.lead_desk.history import HISTORY
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadPipeline, LeadRep
from ac_platform.lead_desk.store import LeadDesk, Viewer, content_ref, person_name
from ac_platform.tenancy.models import Membership

Mode = Literal["dry-run", "apply", "read"]
IST: Final = ZoneInfo("Asia/Kolkata")
ACTION: Final = "lead_desk.file_import_data_change"
RECEIVED: Final = "Received on the form"
TYPED: Final = "Received date typed into the sheet"
CITY_AS_WRITTEN: Final = "City as written"
SIDES: Final = frozenset({"live", "cold", HISTORY})
ASSIGNS: Final = frozenset({"seller", "none"})
MERGES: Final = frozenset({"new", "existing"})
# A row's own instructions, never stored as its answers.
ROW_STAGE: Final = "_stage"
ROW_NOTES: Final = "_notes"
# Columns a lead form export carries that say nothing about the lead.
DROPPED: Final = frozenset({"lead_status", "ad_name"})
EXCEL_EPOCH: Final = datetime(1899, 12, 30, tzinfo=UTC)
# Spellings of a city seen in forms, as the city is called.
CITY_SPELLINGS: Final = {"pume": "Pune", "pube": "Pune", "poona": "Pune"}
EMAIL_HINTS: Final = re.compile(r"(@(gamil|gmial|gmai|gmal|gnail|gmail\.con)\b)|(^www\.)")
# A sheet's header cells, as ``key`` spells them. A row made mostly of them is the sheet's
# own header (a tab with a title row above it), never a lead (Nature Solutions, 16 Nov
# 2026: a header row went in as a lead named "Sr.No").
HEADER_CELLS: Final = frozenset(
    {
        "sr_no",
        "s_no",
        "sl_no",
        "serial_no",
        *(alias for names in ALIASES.values() for alias in names),
    }
)


def header_row(record: dict[str, str]) -> bool:
    """Whether a row is the sheet's own header: most of its cells are header names."""
    cells = [key(value) for value in record.values() if str(value).strip()]
    return bool(cells) and 2 * sum(cell in HEADER_CELLS for cell in cells) > len(cells)


def _input(path: str) -> dict[str, Any]:
    if path.lstrip().startswith("{"):
        return dict(json.loads(path))
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _mask(email: str | None) -> str:
    if not email or "@" not in email:
        return "[none]"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def readable(text: str) -> str:
    """A form's token as people write it: "sales_job_/_business_development" is "Sales
    job / business development", "₹15,000_–_₹30,000" is "₹15,000 – ₹30,000"; a multi-select
    answer keeps its commas."""
    # A multi-select answer separates its choices with a comma and a space (Meta writes a
    # no-break space); a comma inside a number ("15,000") stays as it is.
    words = re.sub(r"\s*,\s+", ", ", text.replace("_", " "))
    words = re.sub(r"\s+", " ", words).strip()
    return words[:1].upper() + words[1:] if words else words


def as_text(value: Any) -> str:
    """A cell as text: a number stored as a number loses its ".0" (a phone, a PIN)."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else "").strip()


def received_at(value: Any) -> tuple[datetime | None, bool]:
    """When the form was received, and whether the date was typed into the sheet (an Excel
    date number) rather than written by the form."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return EXCEL_EPOCH + timedelta(days=float(value)), True
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None, False
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)), False


def ist_words(moment: datetime, *, typed: bool) -> str:
    local = moment.astimezone(IST)
    return f"{local.day} {local:%b %Y}" if typed else f"{local.day} {local:%b %Y, %H:%M} IST"


def tidy_city(raw: str) -> str:
    words = re.sub(r"\s+", " ", raw).strip(" ,.")
    words = re.sub(r"[\s,\-]+maharashtra$", "", words, flags=re.IGNORECASE).strip(" ,.-")
    words = CITY_SPELLINGS.get(words.lower(), words)
    return words if any(ch.isupper() for ch in words) else words.title()


def record_of(
    row: dict[str, Any], mapping: dict[str, str], add: dict[str, str] | None = None
) -> dict[str, str]:
    """The row as the lead keeps it: mapped columns as text, the city tidied with what was
    written kept, answers readable, the form time kept and made readable, empty and
    meaningless columns out, and the batch's own fields."""
    kept = set(mapping.values())
    city = mapping.get("city")
    record: dict[str, str] = {}
    for header, raw in row.items():
        if header in (ROW_STAGE, ROW_NOTES):
            continue
        value = as_text(raw)
        if not value or header in DROPPED:
            continue
        if header == "created_time":
            moment, typed = received_at(raw)
            record[header] = value
            if moment is not None:
                record[RECEIVED] = ist_words(moment, typed=typed)
                if typed:
                    record[TYPED] = "yes"
        elif header == city:
            record[header] = tidy_city(value)
            if record[header] != value:
                record[CITY_AS_WRITTEN] = value
        elif header in kept:
            record[header] = value
        else:
            record[readable(header)] = readable(value)
    for name, value in (add or {}).items():
        record[str(name)] = str(value)
    return record


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


async def _person(db: AsyncSession, email: str) -> Person | None:
    found: Person | None = await db.scalar(
        select(Person).where(func.lower(Person.email) == email.strip().lower())
    )
    return found


def _batches(spec: dict[str, Any]) -> list[dict[str, Any]]:
    if spec.get("batches"):
        return [dict(batch) for batch in spec["batches"]]
    return [{"label": spec["label"], "pipeline": spec.get("pipeline"), "rows": spec["rows"]}]


async def _readback(db: AsyncSession, tenant_id: UUID, labels: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label in labels:
        leads = (
            await db.execute(
                select(
                    Lead.owner_person_id,
                    Lead.stage,
                    Lead.pipeline_key,
                    Lead.test_data,
                    Lead.pipeline,
                ).where(Lead.tenant_id == tenant_id, Lead.source_label == label)
            )
        ).all()
        out[label] = {
            "leads": len(leads),
            "by_owner": dict(Counter(str(o)[:8] if o else "nobody" for o, *_ in leads)),
            "by_stage": dict(Counter(stage for _, stage, *_ in leads)),
            "by_pipeline": dict(Counter(key for _, _, key, *_ in leads)),
            "by_side": dict(Counter(side or "live" for *_, side in leads)),
            "test_data": sum(1 for *_, test, _ in leads if test),
        }
    return out


async def import_unassigned_history(
    db: AsyncSession, spec: dict[str, Any], *, tenant_id: UUID, actor_id: UUID, now: datetime
) -> dict[str, int]:
    """Import explicit CRM facts through intake, without assigning absent CRM users.

    Callers own the transaction and audit. Source ids and command ids are stable across
    reordered CSVs. Existing source content is immutable; changed exports need a new
    reviewed command. No date in the source replaces the ingestion created_at.
    """
    command = UUID(spec["command_id"])
    desk = LeadDesk(
        db,
        Viewer(person_id=actor_id, tenant_id=tenant_id, role="owner", name="Data import"),
        now=now,
    )
    counts: Counter[str] = Counter()
    for item in spec["history_rows"]:
        source_ref = "crm:" + str(item["id"])
        step = uuid5(command, source_ref)
        fingerprint = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        existing = await db.scalar(
            select(LeadEvent).where(LeadEvent.tenant_id == tenant_id, LeadEvent.command_id == step)
        )
        if existing is not None:
            if existing.data.get("crm_sha256") != fingerprint:
                raise ValueError("Imported source changed; refusing to overwrite history")
            counts["done_before"] += 1
            continue
        lead, outcome = await desk.ingest(
            item["record"],
            source="csv",
            source_label=item["label"],
            source_ref=source_ref,
            mapping=spec["mapping"],
            actor=actor_id,
            command_id=step,
            reps=[],
            received_at=datetime.fromisoformat(item["received_at"]),
        )
        if outcome not in {"created", "repeat"} or lead is None:
            raise ValueError("CRM source collided with an existing import; transaction refused")
        event = await db.scalar(
            select(LeadEvent).where(LeadEvent.tenant_id == tenant_id, LeadEvent.command_id == step)
        )
        if event is None:
            raise ValueError("CRM intake did not record its command")
        if outcome == "repeat":
            imported = await db.scalar(
                select(LeadEvent.id)
                .where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.lead_id == lead.id,
                    LeadEvent.data["crm_sha256"].as_string().is_not(None),
                )
                .limit(1)
            )
            if imported is None:
                raise ValueError("CRM row collided with a lead outside this import")
        event.data = {**event.data, "crm_sha256": fingerprint, "payload": item["record"]}
        # Each observation stays in its event; the newest is the visible lead record.
        lead.payload = item["record"]
        lead.source_label = item["label"]
        previous_stage = lead.stage
        stage = str(item["stage"])
        if stage not in {"new", "not_connected", "follow_up", "interested", "won", "lost"}:
            raise ValueError("Unsupported explicit CRM stage")
        lead.stage = stage
        lead.stage_at = datetime.fromisoformat(item["stage_at"]) if item["stage_at"] else None
        lead.first_contact_at = (
            datetime.fromisoformat(item["first_contact_at"]) if item["first_contact_at"] else None
        )
        lead.next_action_at = (
            datetime.fromisoformat(item["next_action_at"]) if item["next_action_at"] else None
        )
        desk._event(
            lead,
            "stage",
            {
                "previous_stage": previous_stage,
                "stage": stage,
                "imported": True,
                "note": "CRM status imported; original status and dates kept in lead fields",
            },
            actor=actor_id,
            command_id=uuid5(step, "stage"),
        )
        counts[outcome] += 1
    await db.flush()
    return dict(counts)


async def run(
    db: AsyncSession, spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    command_id = UUID(spec["command_id"])
    mapping = {str(k): str(v) for k, v in dict(spec["mapping"]).items()}
    batches = _batches(spec)
    labels = [str(batch["label"])[:120] for batch in batches]
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    sides = [str(batch.get("side") or "live") for batch in batches]
    assigns = [str(batch.get("assign") or "seller") for batch in batches]
    merges = [str(batch.get("merge") or "new") for batch in batches]
    if any(side not in SIDES for side in sides):
        raise SystemExit(json.dumps({"refused": "side_not_known"}))
    if any(a not in ASSIGNS for a in assigns) or any(m not in MERGES for m in merges):
        raise SystemExit(json.dumps({"refused": "assign_or_merge_not_known"}))
    # A seller is needed only by a batch whose new leads go to one.
    wants_seller = any(
        assign == "seller" and side != HISTORY and merge == "new"
        for assign, side, merge in zip(assigns, sides, merges, strict=True)
    )
    seller = await _person(db, str(spec["seller_email"])) if spec.get("seller_email") else None
    approver = await _person(db, str(spec["approver_email"]))
    actor = await _person(db, str(spec.get("actor_email") or spec["approver_email"]))
    report: dict[str, Any] = {
        "mode": mode,
        "tenant_id": str(tenant_id),
        "seller": _mask(seller.email if seller else None),
        "approver_found": approver is not None,
    }
    if mode == "read":
        report["status"] = "read"
        report["after"] = await _readback(db, tenant_id, labels)
        return report
    if approver is None or actor is None or (wants_seller and seller is None):
        raise SystemExit(json.dumps({"refused": "person_not_found", **report}))
    member = None
    if seller is not None:
        member = await db.scalar(
            select(Membership.role).where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == seller.id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if member is None:
            raise SystemExit(json.dumps({"refused": "seller_not_an_active_member", **report}))
    pipelines: list[str] = []
    for batch in batches:
        wanted = str(batch.get("pipeline") or "main")
        pipeline_found = (
            await db.execute(
                select(LeadPipeline.key, LeadPipeline.name).where(
                    LeadPipeline.tenant_id == tenant_id,
                    (LeadPipeline.key == wanted)
                    | (func.lower(LeadPipeline.name) == wanted.lower()),
                )
            )
        ).first()
        if pipeline_found is None and wanted != "main":
            raise SystemExit(json.dumps({"refused": "pipeline_not_found", "pipeline": wanted}))
        # The first pipeline is "main" even before it has a row of its own.
        pipelines.append(pipeline_found.key if pipeline_found is not None else "main")
    desk = LeadDesk(
        db,
        Viewer(
            person_id=actor.id,
            tenant_id=tenant_id,
            role="owner",
            name=person_name(actor) if actor.id != approver.id else "Data change",
        ),
        now=now,
    )
    _, config = await desk.settings()
    # Every stage named (a batch's or a row's) is on its pipeline's list before anything is
    # written.
    lists: dict[str, journeys.Journey] = {}
    for number, batch in enumerate(batches):
        key = pipelines[number]
        if key not in lists:
            lists[key] = await journeys.read(db, tenant_id, key)
        named = {str(batch["stage"])} if batch.get("stage") else set()
        named |= {str(r[ROW_STAGE]) for r in batch.get("rows") or [] if r.get(ROW_STAGE)}
        unknown = sorted(name for name in named if lists[key].stage_for(name) is None)
        if unknown:
            raise SystemExit(json.dumps({"refused": "stage_not_on_list", "stages": unknown}))
    if seller is not None:
        rep = await db.get(LeadRep, (tenant_id, seller.id))
        report["seller_rules"] = {"role": member, "taking_leads": rep.available if rep else True}
    report["auto_reassign"] = {
        "on": bool(config.get("auto_reassign")),
        "minutes": config.get("reassign_minutes"),
    }
    report["before"] = await _readback(db, tenant_id, labels)
    # Every row of every batch, in the order the forms were received.
    queue: list[tuple[datetime, int, int, dict[str, str], dict[str, Any]]] = []
    for number, batch in enumerate(batches):
        for index, raw in enumerate(batch.get("rows") or [], start=1):
            record = record_of(dict(raw), mapping, batch.get("add"))
            moment, _ = received_at(dict(raw).get("created_time"))
            queue.append(
                (moment or datetime.max.replace(tzinfo=UTC), number, index, record, dict(raw))
            )
    queue.sort(key=lambda item: (item[0], item[1], item[2]))
    counts: dict[str, Counter[str]] = {label: Counter() for label in labels}
    flags: dict[str, dict[str, list[int]]] = {
        label: {
            "repeat_by_email": [],
            "email_hint": [],
            "date_typed": [],
            "header_row": [],
            "not_here": [],
        }
        for label in labels
    }
    for _, number, index, record, raw in queue:
        label, pipeline, side = labels[number], pipelines[number], sides[number]
        step = uuid5(command_id, f"{number}:{index}")
        if await desk._command_seen(step) is not None:
            # This run's row went in before (a repeat's history line): never twice.
            counts[label]["done_before"] += 1
            continue
        if header_row(record):
            flags[label]["header_row"].append(index)
            counts[label]["header_row"] += 1
            continue
        found = extract(record, mapping, default_country=config["default_country"])
        if found.email and EMAIL_HINTS.search(found.email):
            flags[label]["email_hint"].append(index)
        if TYPED in record:
            flags[label]["date_typed"].append(index)
        existing = merges[number] == "existing"
        if existing:
            # Only a lead already here: by its phone, else (no phone) its email.
            here = None
            if found.phone:
                here = await db.scalar(
                    select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.phone == found.phone)
                )
            elif found.email:
                here = await db.scalar(
                    select(Lead.id).where(Lead.tenant_id == tenant_id, Lead.email == found.email)
                )
            if here is None:
                flags[label]["not_here"].append(index)
                counts[label]["not_here"] += 1
                continue
        elif found.email:
            # The app dedupes by phone; a different number with an email already on a lead
            # is the same person, left out and counted.
            same = await db.scalar(
                select(Lead.id).where(
                    Lead.tenant_id == tenant_id,
                    Lead.email == found.email,
                    (Lead.phone.is_(None)) | (Lead.phone != (found.phone or "")),
                )
            )
            if same is not None:
                flags[label]["repeat_by_email"].append(index)
                counts[label]["repeat_by_email"] += 1
                continue
        history = side == HISTORY
        # Old leads kept as history are given to nobody, as in the app's own import; so
        # are a no-owner batch's.
        to_seller = not history and assigns[number] == "seller" and seller is not None
        moment, _ = received_at(raw.get("created_time"))
        lead, outcome = await desk.ingest(
            record,
            source="csv",
            source_label=label,
            source_ref=content_ref(record),
            mapping=mapping,
            assign="person" if to_seller else "none",
            person_id=seller.id if to_seller and seller is not None else None,
            actor=actor.id,
            pipeline=pipeline,
            command_id=step,
            side=HISTORY if history else None,
            received_at=moment,
            as_is=existing,
        )
        # A row an earlier file brought in comes back "known" (same source reference;
        # _stage and _notes aren't part of it): in a merge batch it is a merge too, so its
        # stage and notes still go in, each once (their own command ids).
        if existing and outcome in ("repeat", "known"):
            outcome = "merged"
        counts[label][outcome] += 1
        if lead is None or outcome not in ("created", "repeat", "merged"):
            continue
        wanted = raw.get(ROW_STAGE) or batches[number].get("stage")
        if outcome == "merged" and raw.get(ROW_STAGE):
            which = lead.pipeline_key or "main"
            if which not in lists:
                lists[which] = await journeys.read(db, tenant_id, which)
            journey = lists[which]
            stage = journey.stage_for(str(raw[ROW_STAGE]))
            at = journey.resolve(lead.stage, lead.step)
            # Only a lead nobody has moved yet: the sheet never undoes work done here.
            if (
                stage is not None
                and (at is None or at.kind == "new")
                and (at is None or at.key != stage.key)
                and await desk._command_seen(uuid5(step, "stage")) is None
            ):
                desk.to_stage(
                    lead,
                    journey,
                    stage,
                    note=None,
                    command_id=uuid5(step, "stage"),
                    source="import",
                    via="api",
                    actor=None,
                )
                counts[label]["staged"] += 1
            elif stage is not None:
                counts[label]["stage_kept"] += 1
        if outcome == "created":
            lead.pipeline = side
            journey = lists[pipeline]
            stage = journey.stage_for(str(wanted)) if wanted else None
            at = journey.resolve(lead.stage, lead.step)
            if stage is not None and (at is None or at.key != stage.key):
                # Where the sheet says the lead stands: nobody's move today.
                desk.to_stage(
                    lead,
                    journey,
                    stage,
                    note=None,
                    command_id=uuid5(step, "stage"),
                    source="import",
                    via="api",
                    actor=None,
                )
                counts[label]["staged"] += 1
        for place, note in enumerate(raw.get(ROW_NOTES) or []):
            words = str(note.get("text") or "").strip()[:2000]
            if not words:
                continue
            dated = note.get("at")
            noted = uuid5(step, f"note:{place}")
            # A merged row leaves no event of its own: its notes say whether it went in.
            if existing and await desk._command_seen(noted) is not None:
                counts[label]["notes_before"] += 1
                continue
            desk._event(
                lead,
                "note",
                {"note": words, "source": "import"},
                actor=actor.id,
                command_id=noted,
                at=datetime.fromisoformat(dated) if dated else None,
            )
            counts[label]["notes"] += 1
    await db.flush()
    total = sum((counter for counter in counts.values()), Counter())
    # A run that changed nothing (a rerun) leaves no audit event.
    report["audited"] = bool(total["created"] + total["repeat"] + total["notes"] + total["staged"])
    if report["audited"]:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner request: import a workbook's leads for one seller",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "batches": [
                    {"label": label, "pipeline": pipeline, "counts": dict(counts[label])}
                    for label, pipeline in zip(labels, pipelines, strict=True)
                ],
                "seller_person_id": str(seller.id) if seller is not None else None,
                "approver": spec.get("approver"),
                "counts": dict(total),
            },
        )
    report["batches"] = [
        {
            "label": label,
            "pipeline": pipeline,
            "side": side,
            "rows": len(batch.get("rows") or []),
            "counts": dict(counts[label]),
            **{name: rows for name, rows in flags[label].items() if rows},
        }
        for label, pipeline, side, batch in zip(labels, pipelines, sides, batches, strict=True)
    ]
    report["counts"] = dict(total)
    report["after"] = await _readback(db, tenant_id, labels)
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
