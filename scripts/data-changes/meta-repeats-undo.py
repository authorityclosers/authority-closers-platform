"""Put back the leads a Meta Page's older-leads run filed as repeats although they were the same
enquiries, imported first (an approved data change; bug report #10, 25 Oct 2026).

On 25 Oct 2026 at 18:24Z an organisation's own Page was switched on before the fix that links
such leads (workbench 2560bca21). Its run filed the Page's leads as repeats onto the leads the
team had imported from a file. Each lead's follow-up time was reset to that moment, its repeat
count went up by one, empty details were filled from Meta's form, and its history says "Asked
again from Meta · …". This leaves each lead as the fix would have:
- the follow-up time, the repeat count and the details the repeat filled come back from the
  snapshot taken before (``before``: lead id -> next_action_at, repeats, and which details were
  empty), only where the lead still holds what the repeat set;
- a lead with any activity after the repeat, or changed since, is left alone and listed;
- the lead gets the fix's own note, under the fix's command id, saying what was put back, so
  later runs find the link and a rerun of this script changes nothing;
- the repeat lines stay in the history (audit history is never rewritten).
Only the named organisation and Page, and only repeats inside the given window. Dry run by
default (everything rolled back); --apply commits. One audit event names the approver and the
card.

Usage (inside the API container): python meta-repeats-undo.py spec.json before.json [--apply]
spec: {"command_id", "tenant_id", "org_name", "source_label", "from", "to", "approver_email",
"issue"}.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.tenancy.models import Tenant

ACTION: Final = "lead_desk.meta_repeats_undone"
# The repeat set the follow-up to the moment it ran; a second either way is that moment.
SAME_MOMENT: Final = timedelta(seconds=2)
# The details a repeat fills where the lead has none (LeadDesk._repeat).
FILLED: Final = ("email", "company", "city", "language", "interest")
WORDS: Final = {
    "next_action_at": "the follow-up time",
    "repeats": "the repeat count",
    "email": "the email",
    "company": "the company",
    "city": "the city",
    "language": "the language",
    "interest": "the interest",
}


def _input(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise refusal("input_not_an_object", path=path)
    return value


def refusal(reason: str, **facts: Any) -> SystemExit:
    return SystemExit(json.dumps({"refused": reason, **facts}))


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) and value else None


def plan(lead: Any, repeat_at: datetime, old: dict[str, Any]) -> dict[str, Any]:
    """What to put back on one lead: the follow-up time where the repeat reset it, the repeat
    count where the repeat raised it, and the details it filled where they were empty. Empty
    when the lead holds none of those."""
    changes: dict[str, Any] = {}
    reset = lead.next_action_at is not None and abs(lead.next_action_at - repeat_at) < SAME_MOMENT
    was = _when(old.get("next_action_at"))
    if reset and lead.next_action_at != was:
        changes["next_action_at"] = was
    repeats = old.get("repeats")
    if isinstance(repeats, int) and lead.repeats == repeats + 1:
        changes["repeats"] = repeats
    for name in FILLED:
        if name in (old.get("empty") or ()) and getattr(lead, name) is not None:
            changes[name] = None
    return changes


async def run(
    db: AsyncSession, spec: dict[str, Any], before: dict[str, Any], *, apply: bool
) -> dict[str, Any]:
    """The change or its rehearsal, inside the caller's transaction."""
    command_id = UUID(spec["command_id"])
    tenant_id = UUID(spec["tenant_id"])
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or tenant.name != spec["org_name"] or tenant.status != "active":
        raise refusal("not_the_named_active_organisation", tenant_id=str(tenant_id))
    approver = await db.scalar(
        select(Person).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise refusal("approver_not_found")
    start, end, label = _when(spec["from"]), _when(spec["to"]), str(spec["source_label"])
    if start is None or end is None or not timedelta(0) < end - start <= timedelta(hours=1):
        raise refusal("window_must_be_under_an_hour")
    repeats = [
        event
        for event in (
            await db.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.tenant_id == tenant_id,
                    LeadEvent.kind == "repeat",
                    LeadEvent.created_at >= start,
                    LeadEvent.created_at < end,
                )
                .order_by(LeadEvent.created_at)
            )
        ).all()
        if (event.data or {}).get("source") == "meta"
        and (event.data or {}).get("source_label") == label
    ]
    now = datetime.now(UTC)
    desk = LeadDesk(
        db,
        Viewer(person_id=approver.id, tenant_id=tenant_id, role="admin", name="Sales X-Ray"),
        now=now,
    )
    fields: Counter[str] = Counter()
    left: Counter[str] = Counter()
    report: dict[str, Any] = {
        "repeats": len(repeats),
        "leads_restored": 0,
        "links": 0,
        "already_done": 0,
    }
    for event in repeats:
        payload = (event.data or {}).get("payload") or {}
        ref = str(payload.get("leadgen_id") or "")
        old = before.get(str(event.lead_id))
        link = uuid5(tenant_id, f"meta-link:{ref}")
        if ref and await db.scalar(
            select(LeadEvent.id).where(
                LeadEvent.tenant_id == tenant_id, LeadEvent.command_id == link
            )
        ):
            report["already_done"] += 1
            continue
        lead = await db.get(Lead, event.lead_id, with_for_update=True)
        if lead is None or not ref:
            left["missing"] += 1
            continue
        if not isinstance(old, dict):
            left["not_in_snapshot"] += 1
            continue
        # Anything a person (or the desk) did after the repeat keeps the lead as it is.
        after = await db.scalar(
            select(func.count())
            .select_from(LeadEvent)
            .where(
                LeadEvent.tenant_id == tenant_id,
                LeadEvent.lead_id == event.lead_id,
                LeadEvent.created_at > event.created_at + SAME_MOMENT,
            )
        )
        if after or lead.updated_at > event.created_at + SAME_MOMENT:
            left["touched_since"] += 1
            continue
        changes = plan(lead, event.created_at, old)
        for name, value in changes.items():
            setattr(lead, name, value)
            fields[name] += 1
        if changes:
            lead.revision += 1
            lead.updated_at = now
            report["leads_restored"] += 1
        put_back = ", ".join(WORDS[name] for name in changes)
        sent = (payload.get("meta") or {}).get("created_time")
        desk._event(
            lead,
            "note",
            {
                "note": f"Also on {label}: their form was sent before this lead was added, so it "
                "is the same enquiry. A run on 25 Oct filed it as asked again by mistake"
                + (f"; put back: {put_back}." if put_back else "."),
                "source": "meta",
                "source_label": label,
                "source_ref": ref,
                "submitted_at": sent if isinstance(sent, str) else None,
                "linked": True,
                "repaired": sorted(changes),
            },
            actor=None,
            command_id=link,
        )
        report["links"] += 1
    report["fields_restored"] = dict(sorted(fields.items()))
    report["left"] = dict(sorted(left.items()))
    if report["leads_restored"] or report["links"]:
        await append_audit_event(
            db,
            tenant_id=tenant_id,
            actor_person_id=approver.id,
            actor_type="operator",
            action=ACTION,
            resource_type="tenant",
            resource_id=tenant_id,
            request_id=str(uuid5(command_id, "audit")),
            reason="Owner approval: put back the leads a Meta Page's run filed as repeats",
            payload={
                "issue": spec.get("issue"),
                "command_id": str(command_id),
                "source_label": label,
                "window": [spec["from"], spec["to"]],
                **{key: report[key] for key in ("repeats", "leads_restored", "links")},
                "fields_restored": report["fields_restored"],
                "left": report["left"],
            },
        )
    report["mode"] = "apply" if apply else "dry-run"
    report["status"] = "applied" if apply else "rehearsed_and_rolled_back"
    return report


async def main(spec_path: str, before_path: str, apply: bool) -> int:
    settings = get_settings()
    engine_ = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine_, expire_on_commit=False)() as db:
            try:
                report = await run(db, _input(spec_path), _input(before_path), apply=apply)
            except BaseException:
                await db.rollback()
                raise
            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await engine_.dispose()
    print(json.dumps(report, default=str))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(asyncio.run(main(args[0], args[1], "--apply" in flags)))
