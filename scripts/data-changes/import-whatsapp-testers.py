"""Bring the Sales X-Ray testers into the AC workspace as leads, with every message we already
sent them as their history (approved data change).

Owner, 22 Nov 2026 (through the Mac orchestrator): "every person we contact becomes a lead",
starting with the testers: the Play testers' Google Group and the SalesXray Insiders WhatsApp
group, merged so nobody is there twice. One transaction:
  1. each person is one lead through the app's own intake (``LeadDesk.ingest``): source
     "manual", the label given, ``source_ref`` "tester:<key>" (so a rerun finds it), no owner
     (the no-owner pool), received when we first wrote to them. A number (else an email)
     already a lead here comes back as it is (``as_is``): no "asked again", no new owner, no
     move; its tags and messages still go on it;
  2. a person with no known name goes in by their phone (or email) only (``display_name``);
     "Referred by" is kept in the lead's answers only where the input says so;
  3. tags by name through the v1.94 tags module (``tags._make`` and ``tags.apply``): one
     history line per lead whose tags change, never more than 10 on a lead;
  4. every message we sent them is one WhatsApp "message" line in the lead's history at its
     own time (UTC), by nobody (it went from the business number through the linked device,
     not from a seller), with the WhatsApp message id; its command id is
     ``uuid5(TOUCHES, "<tenant>:<message id>:<key>")``, so a rerun (with any command id)
     adds none twice. Nothing goes in the Chats screen's thread: those are Cloud API messages;
  5. a lead nobody had contacted yet takes its first message's time as its first contact;
  6. one audit event naming the approver, the issue and the snapshot (counts only).
Nothing is sent to anyone.

Input: a JSON file outside git (personal data), its path the first argument:
  {"command_id", "tenant" (its id or first 8 characters), "approver_email", "approver"
   (the words of the approval), "issue", "label", "pipeline"? (key or name, default main),
   "people": [{"key", "name"?, "phone"?, "email"?, "other_phones"?: [..],
               "other_emails"?: [..], "referred_by"?, "tags": [..],
               "touches": [{"at" (ISO, with zone), "message_id", "where" ("dm"|"group"),
                            "kind" ("text"|"video"|"image"|"document"|"invite"|"audio"),
                            "summary" (<= 80 characters, no personal data)}]}]}
Modes: a dry run (the default) makes the whole import in its transaction, reports it and rolls
it back; ``--apply`` commits (on production only with ``--production-snapshot-sha256 <sha>``
of the snapshot taken first: ``sudo /usr/local/sbin/ac-db-snapshot production
before-testers-import``); ``--read`` reads the result back. Inside the API container:
    docker cp input.json <api>:/tmp/testers.json
    docker exec -i <api> python - /tmp/testers.json [--apply --production-snapshot-sha256 <sha>] \
        < scripts/data-changes/import-whatsapp-testers.py
Prints counts only, never a name, number or email.
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
from ac_platform.lead_desk import tags as lead_tags
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadPipeline, LeadTag, LeadTagLink
from ac_platform.lead_desk.store import LeadDesk, Viewer

Mode = Literal["dry-run", "apply", "read"]
ACTION: Final = "lead_desk.testers_import_data_change"
# Every message line's command id lives under this, whatever the run's command id.
TOUCHES: Final = UUID("6f1f3a0e-2b7c-5d4e-9a61-7e2c0b9d4f10")
KINDS: Final = frozenset({"text", "video", "image", "document", "invite", "audio"})
WHERES: Final = frozenset({"dm", "group"})
SHA256: Final = re.compile(r"[0-9a-f]{64}")
KEY: Final = re.compile(r"[A-Za-z0-9:+@._-]{1,120}")
MAX_SUMMARY: Final = 80
SOURCE_REF: Final = "tester:"


def _input(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as file:
        return dict(json.load(file))


def _moment(value: Any) -> datetime:
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError("time_without_zone")
    return moment.astimezone(UTC)


def check(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """The people, checked before anything is read or written; refuses the whole run."""

    people = [dict(person) for person in spec.get("people") or []]
    if not people:
        raise SystemExit(json.dumps({"refused": "no_people"}))
    keys: Counter[str] = Counter()
    for person in people:
        key = str(person.get("key") or "")
        if not KEY.fullmatch(key):
            raise SystemExit(json.dumps({"refused": "bad_key"}))
        keys[key] += 1
        if not (person.get("phone") or person.get("email")):
            raise SystemExit(json.dumps({"refused": "person_without_phone_or_email"}))
        names = [str(name) for name in person.get("tags") or []]
        if len(set(names)) > lead_tags.MAX_ON_LEAD or any(not n.strip() for n in names):
            raise SystemExit(json.dumps({"refused": "tags_not_fit"}))
        for touch in person.get("touches") or []:
            try:
                _moment(touch["at"])
            except (KeyError, ValueError):
                raise SystemExit(json.dumps({"refused": "touch_time"})) from None
            if (
                str(touch.get("kind")) not in KINDS
                or str(touch.get("where")) not in WHERES
                or not str(touch.get("message_id") or "").strip()
                or not 0 < len(str(touch.get("summary") or "")) <= MAX_SUMMARY
            ):
                raise SystemExit(json.dumps({"refused": "touch_fields"}))
    if any(count > 1 for count in keys.values()):
        raise SystemExit(json.dumps({"refused": "key_twice"}))
    return people


def guard(environment: str, mode: Mode, snapshot: str | None) -> None:
    """Production is written only after a snapshot, named by its SHA-256."""

    if mode == "apply" and environment == "production" and not SHA256.fullmatch(snapshot or ""):
        raise SystemExit(json.dumps({"refused": "production_needs_snapshot_sha256"}))


def record_of(person: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": " ".join(str(person.get("name") or "").split())[:200] or None,
        "phone": person.get("phone") or None,
        "email": person.get("email") or None,
    }
    if person.get("referred_by"):
        record["referred_by"] = str(person["referred_by"])[:120]
    if person.get("other_phones"):
        record["Other phone"] = ", ".join(str(p) for p in person["other_phones"])
    if person.get("other_emails"):
        record["Other email"] = ", ".join(str(e) for e in person["other_emails"])
    return {key: value for key, value in record.items() if value}


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


async def _readback(db: AsyncSession, tenant_id: UUID, label: str) -> dict[str, Any]:
    leads = (
        await db.scalars(
            select(Lead.id).where(
                Lead.tenant_id == tenant_id,
                Lead.source == "manual",
                Lead.source_ref.like(f"{SOURCE_REF}%"),
            )
        )
    ).all()
    touches = await db.scalar(
        select(func.count())
        .select_from(LeadEvent)
        .where(
            LeadEvent.tenant_id == tenant_id,
            LeadEvent.kind == "message",
            LeadEvent.data["via"].as_string() == "linked_device",
            LeadEvent.data["source"].as_string() == "import",
        )
    )
    tagged = (
        await db.scalar(
            select(func.count(func.distinct(LeadTagLink.lead_id))).where(
                LeadTagLink.tenant_id == tenant_id, LeadTagLink.lead_id.in_(list(leads))
            )
        )
        if leads
        else 0
    )
    labelled = await db.scalar(
        select(func.count()).where(Lead.tenant_id == tenant_id, Lead.source_label == label)
    )
    return {
        "leads_made_here": len(leads),
        "with_label": int(labelled or 0),
        "tagged": int(tagged or 0),
        "touch_lines": int(touches or 0),
    }


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    environment: str,
    snapshot: str | None = None,
) -> dict[str, Any]:
    guard(environment, mode, snapshot)
    people = check(spec)
    command_id = UUID(str(spec["command_id"]))
    label = str(spec["label"])[:120]
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    tenant_id = await _tenant(db, str(spec["tenant"]))
    report: dict[str, Any] = {"mode": mode, "environment": environment, "people": len(people)}
    if mode == "read":
        report["after"] = await _readback(db, tenant_id, label)
        report["status"] = "read"
        return report
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found"}))
    wanted = str(spec.get("pipeline") or "main")
    found = (
        await db.execute(
            select(LeadPipeline.key).where(
                LeadPipeline.tenant_id == tenant_id,
                (LeadPipeline.key == wanted) | (func.lower(LeadPipeline.name) == wanted.lower()),
            )
        )
    ).first()
    if found is None and wanted != "main":
        raise SystemExit(json.dumps({"refused": "pipeline_not_found"}))
    pipeline = found.key if found is not None else "main"
    desk = LeadDesk(
        db,
        Viewer(person_id=approver.id, tenant_id=tenant_id, role="owner", name="Data change"),
        now=now,
    )
    report["before"] = await _readback(db, tenant_id, label)
    counts: Counter[str] = Counter()
    made: dict[str, LeadTag] = {}
    for person in people:
        key = str(person["key"])
        touches = sorted(person.get("touches") or [], key=lambda t: _moment(t["at"]))
        first = _moment(touches[0]["at"]) if touches else None
        lead, outcome = await desk.ingest(
            record_of(person),
            source="manual",
            source_label=label,
            source_ref=f"{SOURCE_REF}{key}",
            mapping={"name": "name", "phone": "phone", "email": "email"},
            assign="none",
            actor=approver.id,
            pipeline=pipeline,
            command_id=uuid5(command_id, f"lead:{key}"),
            received_at=first,
            as_is=True,
        )
        counts[outcome] += 1
        if lead is None:
            continue
        names = sorted({" ".join(str(name).split()) for name in person.get("tags") or []})
        wanted_tags = []
        for name in names:
            if name.lower() not in made:
                made[name.lower()] = await lead_tags._make(
                    desk, uuid5(command_id, f"tag:{name.lower()}"), name, None
                )
            wanted_tags.append(made[name.lower()])
        if wanted_tags:
            full: set[UUID] = set()
            changed = await lead_tags.apply(
                desk,
                [lead],
                add=wanted_tags,
                command_id=uuid5(command_id, f"tags:{key}:{'|'.join(names)}"),
                actor=approver.id,
                extra={"source": "import"},
                over="skip",
                full=full,
            )
            added = len(changed.get(lead.id, ([], []))[0])
            counts["tags_added"] += added
            counts["tags_full"] += len(full)
        for touch in touches:
            noted = uuid5(TOUCHES, f"{tenant_id}:{touch['message_id']}:{key}")
            if await desk._command_seen(noted) is not None:
                counts["touches_before"] += 1
                continue
            desk._event(
                lead,
                "message",
                {
                    "channel": "whatsapp",
                    "via": "linked_device",
                    "where": str(touch["where"]),
                    "wa_message_id": str(touch["message_id"])[:64],
                    "wa_kind": str(touch["kind"]),
                    "note": str(touch["summary"])[:MAX_SUMMARY],
                    "sent_by": "business number",
                    "source": "import",
                },
                actor=None,
                command_id=noted,
                at=_moment(touch["at"]),
            )
            counts["touches"] += 1
            counts[f"touches_{touch['kind']}"] += 1
        if first is not None and lead.first_contact_at is None:
            lead.first_contact_at = first
            counts["first_contact_set"] += 1
    await db.flush()
    report["audited"] = bool(counts["created"] + counts["touches"] + counts["tags_added"])
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
            reason="Owner order 22 Nov 2026: every tester becomes a lead, with what we sent them",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "approver": spec.get("approver"),
                "snapshot_sha256": snapshot,
                "label": label,
                "pipeline": pipeline,
                "counts": dict(counts),
            },
        )
    report["counts"] = dict(counts)
    report["after"] = await _readback(db, tenant_id, label)
    report["status"] = "applied" if mode == "apply" else "rehearsed_and_rolled_back"
    return report


async def execute(
    sessions: async_sessionmaker[AsyncSession],
    spec: dict[str, Any],
    *,
    mode: Mode,
    now: datetime,
    environment: str,
    snapshot: str | None = None,
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            report = await run(
                db, spec, mode=mode, now=now, environment=environment, snapshot=snapshot
            )
        except BaseException:
            await db.rollback()
            raise
        if mode == "apply":
            await db.commit()
        else:
            await db.rollback()
    return report


def parse(argv: list[str]) -> tuple[str, Mode, str | None]:
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    snapshot = None
    if "--production-snapshot-sha256" in argv:
        at = argv.index("--production-snapshot-sha256")
        given = argv[at + 1] if at + 1 < len(argv) else None
        snapshot = given.strip().lower() if given else None
        args = [a for a in args if a != given]
    if len(args) != 1:
        raise SystemExit("usage: import-whatsapp-testers.py <input.json> [--apply | --read]")
    mode: Mode = "apply" if "--apply" in flags else "read" if "--read" in flags else "dry-run"
    return args[0], mode, snapshot


async def main(argv: list[str]) -> int:
    path, mode, snapshot = parse(argv)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        report = await execute(
            async_sessionmaker(engine, expire_on_commit=False),
            _input(path),
            mode=mode,
            now=datetime.now(UTC),
            environment=str(settings.environment),
            snapshot=snapshot,
        )
    finally:
        await engine.dispose()
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
