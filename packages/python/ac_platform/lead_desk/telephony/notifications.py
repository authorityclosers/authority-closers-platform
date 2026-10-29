"""Report-ready push using the existing lead-alert Firebase app and registered phones.

Android already accepts sx_open launch extras for /analysis/calls. A notification
payload lets Android display it while backgrounded; foreground uses the web badge.
Names and call content remain in the authenticated in-app notification only.
Failed sends are retried; successful tokens are recorded by digest, never by value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, select

from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import LeadDevice
from ac_platform.lead_desk.push import Fcm, config
from ac_platform.lead_desk.telephony import ledger
from ac_platform.tenancy.models import Membership

SENT = "lead_desk.company_call.report_push_sent.v1"


class ReportFcm(Fcm):
    async def report(self, client: httpx.AsyncClient, token: str, submission: UUID) -> str:
        try:
            response = await client.post(
                f"https://fcm.googleapis.com/v1/projects/{self.cfg.project_id}/messages:send",
                json={
                    "message": {
                        "token": token,
                        "notification": {
                            "title": "Your call is analysed",
                            "body": "Open the report and coaching in Sales X-Ray.",
                        },
                        "data": {
                            "type": "company_call_report",
                            "sx_open": f"/analysis/calls/{submission}",
                        },
                        "android": {
                            "priority": "HIGH",
                            "ttl": "7200s",
                            "notification": {
                                "channel_id": "lead_alerts",
                                "tag": f"company-report-{submission}",
                            },
                        },
                    }
                },
                headers={"Authorization": f"Bearer {await self._token()}"},
                timeout=15,
            )
        except (httpx.HTTPError, OSError):
            return "failed"
        if response.status_code == 200:
            return "sent"
        if response.status_code == 404:
            return "gone"
        return "failed"


async def dispatch(
    pipeline: Any,
    call: ledger.CompanyCall,
    submission: UUID,
    *,
    fcm: Any = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    cfg = config() if fcm is None else None
    if fcm is None:
        if cfg is None:
            return 0
        fcm = ReportFcm(cfg)
    async with pipeline.sessions() as db, db.begin():
        active = await db.scalar(
            select(Membership.person_id)
            .join(Person, Person.id == Membership.person_id)
            .where(
                Person.status == "active",
                Membership.tenant_id == call.tenant_id,
                Membership.person_id == call.seller_person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if active is None:
            return 0
        events = await pipeline.events(db, call)
        ready = events.get("lead_desk.company_call.report_ready.v1", {})
        if int(datetime.now(UTC).timestamp()) - ready.get("ready_at_epoch", 0) > 7200:
            return 0
        delivered = set(events.get(SENT, {}).get("devices", []))
        devices = (
            await db.execute(
                select(LeadDevice.token, LeadDevice.token_sha256).where(
                    LeadDevice.tenant_id == call.tenant_id,
                    LeadDevice.person_id == call.seller_person_id,
                )
            )
        ).all()
    owned_client = client is None
    client = client or httpx.AsyncClient()
    sent = 0
    try:
        for token, digest in devices:
            if digest in delivered:
                continue
            result = await fcm.report(client, token, submission)
            if result == "gone":
                async with pipeline.sessions() as db, db.begin():
                    await db.execute(
                        delete(LeadDevice).where(
                            LeadDevice.tenant_id == call.tenant_id,
                            LeadDevice.person_id == call.seller_person_id,
                            LeadDevice.token_sha256 == digest,
                        )
                    )
            if result == "sent":
                sent += 1
                delivered.add(digest)
                async with pipeline.sessions() as db, db.begin():
                    await pipeline.append(
                        db,
                        call,
                        SENT,
                        {"devices": sorted(delivered), "submission_id": str(submission)},
                    )
    finally:
        if owned_client:
            await client.aclose()
    return sent
