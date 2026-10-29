"""Owner order 29 Oct 2026: CRM organisation, leads and call history, no AI.

Run with deployed settings, --data-dir pointing to the private export and an
explicit existing --owner-email. Dry-run by default; --apply commits the single
transaction; --read is read-only. Recording upload/consent is a separate app step.
--tenant-id imports into an organisation that already exists (production has one
since 29 Oct 2026); the operator must be its active owner or admin, and none is created.
--calls-only (with --tenant-id) adds only the call history, each call on the one existing lead
with exactly its phone number: production's leads arrived by CSV on 28 Oct, so no lead is
created or changed. Calls without exactly one such lead are counted, never guessed.
Never prints personal fields, source rows, filenames or credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant

COMMAND = UUID("eb82c251-b228-59cd-aabe-fd98f583b299")
APPROVER = "owner, chat order 29 Oct 2026"
WORK_ITEM = "ea-sales-20261029"
NAME = "Estate Autopilots"
# Source statuses are retained verbatim. Low budget alone does not mean closed lost.
STAGES = {
    "": "new",
    "New": "new",
    "Call Not Received": "not_connected",
    "Attempted Contact": "not_connected",
    "Contacted": "follow_up",
    "Nurturing": "follow_up",
    "Low Budget": "follow_up",
    "Interested": "interested",
    "Qualified": "interested",
    "Converted": "won",
    "Lost – Closed Lost": "lost",
    "Lost – Unqualified": "lost",
}
STAGE_TIME = {
    "won": "booked_at",
    "lost": "lost_at",
    "interested": "qualified_at",
    "follow_up": "first_contacted_at",
}
MAPPING = {
    "name": "name",
    "phone": "phone_e164",
    "email": "email",
    "company": "company",
    "city": "location",
}


def moment(value: str) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Source timestamp has no time zone")
    return parsed.isoformat()


def prepare(rows: list[dict[str, str]]) -> dict[str, Any]:
    ids = [r["lead_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate CRM source ids")
    history = []
    # Later dated CRM observations supersede earlier ones, with each kept as history.
    for row in sorted(rows, key=lambda r: (r.get("last_updated") or r["created_at"], r["lead_id"])):
        if row["status_raw"] not in STAGES:
            raise ValueError("Unmapped CRM status")
        stage = STAGES[row["status_raw"]]
        system = row["source_system"]
        if system not in {"neeti_crm_export", "meta_form_sheet"}:
            raise ValueError("Unmapped source system")
        label = "Neeti CRM" if system == "neeti_crm_export" else "Meta form"
        record = {**row, "Owner in Neeti": row["owner"], "Source system": label}
        history.append(
            {
                "id": row["lead_id"],
                "record": record,
                "label": (label + (" / " + row["campaign"] if row["campaign"] else ""))[:120],
                "received_at": moment(row["created_at"]),
                "stage": stage,
                "stage_at": moment(row.get(STAGE_TIME.get(stage, ""), "")),
                "first_contact_at": moment(row["first_contacted_at"]),
                "next_action_at": moment(row["next_followup_at"])
                if stage not in {"won", "lost"}
                else None,
            }
        )
    return {"command_id": str(COMMAND), "mapping": MAPPING, "history_rows": history}


def load_data(directory: Path) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    rows = list(csv.DictReader((directory / "clean/leads.csv").open(encoding="utf-8-sig")))
    calls = list(csv.DictReader((directory / "clean/calls.csv").open(encoding="utf-8-sig")))
    spec = prepare(rows)
    ids = {r["lead_id"] for r in rows}
    if len({c["call_id"] for c in calls}) != len(calls):
        raise ValueError("Duplicate call source ids")
    for call in calls:
        if call["lead_id"] not in ids or int(call["duration_sec"]) < 0:
            raise ValueError("Call has no source lead or invalid duration")
        moment(call["started_at"])
    digest = hashlib.sha256(json.dumps([spec, calls], sort_keys=True).encode()).hexdigest()
    return spec, calls, digest


def importer() -> Any:
    loader = importlib.util.spec_from_file_location(
        "leads_file_import", Path(__file__).with_name("import-leads-file.py")
    )
    assert loader and loader.loader
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


async def counts(db: AsyncSession, tenant: UUID | None) -> dict[str, Any]:
    if tenant is None:
        return {"organisations": 0, "leads": 0, "source_rows": 0, "calls": 0, "duration_seconds": 0}
    leads = list(await db.scalars(select(Lead).where(Lead.tenant_id == tenant)))
    events = list(await db.scalars(select(LeadEvent).where(LeadEvent.tenant_id == tenant)))
    calls = [e for e in events if e.kind == "call" and e.data.get("crm_import") == WORK_ITEM]
    return {
        "organisations": 1,
        "leads": len(leads),
        "source_rows": sum("crm_sha256" in e.data for e in events),
        "calls": len(calls),
        "duration_seconds": sum(e.data["duration_seconds"] for e in calls),
        "assigned_leads": sum(lead.owner_person_id is not None for lead in leads),
        "by_stage": dict(Counter(lead.stage for lead in leads)),
    }


async def run(
    db: AsyncSession,
    spec: dict[str, Any],
    calls: list[dict[str, str]],
    *,
    owner_email: str,
    mode: str,
    digest: str,
    now: datetime,
    tenant_id: UUID | None = None,
    calls_only: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    if mode == "read":
        await db.execute(text("SET TRANSACTION READ ONLY"))
    else:
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": COMMAND.int % (2**63)})
    owner = await db.scalar(select(Person).where(func.lower(Person.email) == owner_email.lower()))
    if owner is None or owner.status != "active":
        raise ValueError("Owner must be an existing active account")
    prior = await db.scalar(select(Organisation).where(Organisation.creation_command_id == COMMAND))
    before = await counts(db, tenant_id or (prior.tenant_id if prior else None))
    if mode == "read":
        return {"mode": mode, "source_sha256": digest, "after": before}
    if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
        raise ValueError("Deployment tenant boundaries are required")
    if calls_only and tenant_id is None:
        raise ValueError("Calls only needs an existing organisation")
    if tenant_id is not None:
        found = await db.get(Organisation, tenant_id)
        if found is None:
            raise ValueError("No organisation for that tenant")
        org = found
        member = await db.get(Membership, (org.tenant_id, owner.id))
        if (
            member is None
            or member.status != "active"
            or member.role not in ("owner", "admin")
            or member.ended_at
        ):
            raise ValueError("Operator must be an active owner or admin of that organisation")
    else:
        if prior is None and await db.scalar(select(Tenant.id).where(Tenant.name == NAME)):
            raise ValueError(
                "Organisation name already exists outside this command; reconcile first"
            )
        org = await OrganisationService(
            db,
            operations_tenant_id=settings.operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
        ).create(NAME, owner.id, COMMAND, APPROVER, reason=WORK_ITEM)
        member = await db.get(Membership, (org.tenant_id, owner.id))
        if member is None or member.status != "active" or member.role != "owner" or member.ended_at:
            raise ValueError("Owner membership is no longer active")
    result = (
        {"calls_only": True}
        if calls_only
        else await importer().import_unassigned_history(
            db, spec, tenant_id=org.tenant_id, actor_id=owner.id, now=now
        )
    )
    changed_calls = 0
    unmatched_calls = 0
    for call in calls:
        command = uuid5(COMMAND, "call:" + call["call_id"])
        existing = await db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == org.tenant_id, LeadEvent.command_id == command
            )
        )
        fingerprint = hashlib.sha256(json.dumps(call, sort_keys=True).encode()).hexdigest()
        if existing:
            if existing.data.get("source_sha256") != fingerprint:
                raise ValueError("Call source changed; refusing to overwrite history")
            continue
        if calls_only:
            matches = list(
                await db.scalars(
                    select(Lead.id).where(
                        Lead.tenant_id == org.tenant_id, Lead.phone == call["phone_e164"]
                    )
                )
            )
            if not call["phone_e164"] or len(matches) != 1:
                unmatched_calls += 1
                continue
            lead_id = matches[0]
        else:
            capture = await db.scalar(
                select(LeadEvent).where(
                    LeadEvent.tenant_id == org.tenant_id,
                    LeadEvent.command_id == uuid5(COMMAND, "crm:" + call["lead_id"]),
                )
            )
            if capture is None:
                raise ValueError("Call lead was not imported")
            lead_id = capture.lead_id
        call_time = datetime.fromisoformat(str(moment(call["started_at"])))
        desk = LeadDesk(
            db, Viewer(owner.id, org.tenant_id, member.role, "Data import"), now=call_time
        )
        await desk.record_call(
            lead_id,
            command_id=command,
            submission_id=None,
            simulated=False,
            duration_seconds=int(call["duration_sec"]),
        )
        event = await db.scalar(
            select(LeadEvent).where(
                LeadEvent.tenant_id == org.tenant_id, LeadEvent.command_id == command
            )
        )
        assert event is not None
        event.actor_person_id = None  # imported caller has no account; never credit the operator
        event.data = {
            **event.data,
            "note": "Imported call. Original seller: " + call["agent"],
            "crm_import": WORK_ITEM,
            "source_sha256": fingerprint,
            "original_agent": call["agent"],
            "direction": call["direction"] or "unknown",
            "recording_pending_consent": True,
        }
        lead = await db.get(Lead, lead_id)
        assert lead is not None
        lead.updated_at = now
        changed_calls += 1
    await db.flush()
    after = await counts(db, org.tenant_id)
    changed = result.get("created", 0) + result.get("repeat", 0) + changed_calls
    if changed:
        await append_audit_event(
            db,
            tenant_id=org.tenant_id,
            actor_person_id=owner.id,
            actor_type="operator",
            action="lead_desk.crm_history_data_change",
            resource_type="tenant",
            resource_id=org.tenant_id,
            request_id=str(uuid5(COMMAND, digest)),
            reason=APPROVER,
            payload={
                "issue": WORK_ITEM,
                "approver": APPROVER,
                "source_sha256": digest,
                "before": before,
                "after": after,
                "command_id": str(COMMAND),
            },
        )
    return {
        "mode": mode,
        "source_sha256": digest,
        "tenant_id": str(org.tenant_id),
        "before": before,
        "after": after,
        "rows": result,
        "new_calls": changed_calls,
        "unmatched_calls": unmatched_calls,
        "analysis_started": 0,
        "recordings_uploaded": 0,
        "committed": mode == "apply",
    }


async def main(args: argparse.Namespace) -> int:
    spec, calls, digest = load_data(args.data_dir)
    settings = get_settings()
    if settings.environment != args.environment:
        raise ValueError("Explicit environment must match deployment settings")
    engine = create_async_engine(settings.database_url, echo=False)
    mode = "apply" if args.apply else "read" if args.read else "dry-run"
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            try:
                report = await run(
                    db,
                    spec,
                    calls,
                    owner_email=args.owner_email,
                    mode=mode,
                    digest=digest,
                    now=datetime.now(UTC),
                    tenant_id=args.tenant_id,
                    calls_only=args.calls_only,
                )
                if args.apply:
                    await db.commit()
                else:
                    await db.rollback()
            except BaseException:
                await db.rollback()
                raise
    finally:
        await engine.dispose()
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--tenant-id", type=UUID, help="import into this existing organisation")
    parser.add_argument(
        "--calls-only", action="store_true", help="only call history, on existing leads by phone"
    )
    parser.add_argument(
        "--environment", choices=("development", "production", "test"), required=True
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--read", action="store_true")
    try:
        raise SystemExit(asyncio.run(main(parser.parse_args())))
    except Exception:
        # Driver exceptions may embed SQL parameters containing personal data.
        print(json.dumps({"refused": "Import failed; transaction rolled back; inspect privately"}))
        sys.exit(1)
