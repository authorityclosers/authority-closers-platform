"""Send the day's digest and the two-hourly sweep now, to one test organisation's phones
(orchestrator, 25 Oct 2026: test the demo's workflows 10 and 11 tonight).

The same code as the schedule (``digest_push.collect`` then ``push.send``), forced to each kind
asked for, in its own slot (this moment), whatever the clock and work hours say. Each seller
with a phone gets one push per kind, with a count and no lead or words; the app reads the words
on the seller's own session (``GET /v1/lead-desk/alert?kind=digest|sweep``). A kind with nothing
to say for a seller is written to the ledger and not sent, as on schedule.

Only a test organisation: every lead it holds is test data (or it has none), or it is a
sandbox. Any other organisation is refused unless the input says ``"real_organisation": true``.

A dry run (the default) writes the ledger rows in its transaction, prints who would get what
and rolls back; nothing is sent. ``--apply`` commits the ledger rows, then sends. One audit
event naming the approver and the issue.

Run inside the API container with the deployed settings (FCM included):
    docker exec -i <api> python - '<input JSON>' [--apply] < send-digests-now.py
input: {"tenant" (its id or first 8 characters), "kinds": ["digest", "sweep"],
        "approver_email", "issue", "real_organisation"?}
Prints counts and masked ids only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import get_settings
from ac_platform.audit.service import append_audit_event
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person
from ac_platform.lead_desk import digest_push, digests, push
from ac_platform.lead_desk.models import Lead

Mode = Literal["dry-run", "apply"]
ACTION = "lead_desk.digest_sent_on_demand"
NAMESPACE = UUID("6f1c3b0e-8a52-4d0e-9a7c-6d2b1f7a9e31")


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


async def plan(
    db: AsyncSession, spec: dict[str, Any], now: datetime
) -> tuple[UUID, UUID, list[digest_push.DigestAlert], dict[str, Any]]:
    """The ledger rows and pushes, inside the caller's transaction."""
    wanted = [str(kind) for kind in spec.get("kinds") or ("digest", "sweep")]
    if not wanted or any(kind not in ("digest", "sweep") for kind in wanted):
        raise SystemExit(json.dumps({"refused": "kinds_are_digest_or_sweep"}))
    kinds: list[digests.Kind] = ["digest" if kind == "digest" else "sweep" for kind in wanted]
    tenant_id = await _tenant(db, str(spec["tenant"]))
    approver = await db.scalar(
        select(Person.id).where(func.lower(Person.email) == str(spec["approver_email"]).lower())
    )
    if approver is None:
        raise SystemExit(json.dumps({"refused": "approver_not_found"}))
    real = int(
        await db.scalar(
            select(func.count()).where(Lead.tenant_id == tenant_id, Lead.test_data.is_(False))
        )
        or 0
    )
    sandbox = await db.scalar(
        select(ConversationSandboxOrganisation.tenant_id).where(
            ConversationSandboxOrganisation.tenant_id == tenant_id
        )
    )
    if real and sandbox is None and spec.get("real_organisation") is not True:
        raise SystemExit(json.dumps({"refused": "not_a_test_organisation", "real_leads": real}))
    alerts: list[digest_push.DigestAlert] = []
    for kind in kinds:
        alerts += await digest_push.collect(db, now, tenants=[tenant_id], forced=kind)
    report = {
        "tenant": str(tenant_id)[:8],
        "kinds": kinds,
        "pushes": [
            {
                "person": str(alert.person_id)[:8],
                "kind": alert.kind,
                "count": alert.count,
                "phones": len(alert.tokens),
            }
            for alert in alerts
        ],
    }
    return tenant_id, approver, alerts, report


async def execute(
    sessions: async_sessionmaker[AsyncSession], spec: dict[str, Any], *, mode: Mode, now: datetime
) -> dict[str, Any]:
    async with sessions() as db:
        try:
            tenant_id, approver, alerts, report = await plan(db, spec, now)
            if mode == "apply":
                await append_audit_event(
                    db,
                    tenant_id=tenant_id,
                    actor_person_id=approver,
                    actor_type="operator",
                    action=ACTION,
                    resource_type="tenant",
                    resource_id=tenant_id,
                    request_id=str(uuid5(NAMESPACE, f"{tenant_id}:{now.isoformat()}")),
                    reason=f"On-demand digest test, {spec.get('issue')}",
                    payload={"issue": spec.get("issue"), **report},
                )
        except BaseException:
            await db.rollback()
            raise
        if mode != "apply":
            await db.rollback()
            report["status"] = "rehearsed_and_rolled_back"
            return report
        await db.commit()
    cfg = push.config()
    if cfg is None:
        report["status"] = "ledger_written_but_fcm_not_configured"
        return report
    async with httpx.AsyncClient() as client:
        sent, gone = await push.send(alerts, push.Fcm(cfg), client)
    report["sent"] = sent
    report["phones_gone"] = len(gone)
    report["status"] = "sent"
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
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(asyncio.run(main(args[0], "apply" if "--apply" in flags else "dry-run")))
