"""Deleting chosen leads for good (owner, 21 Oct 2026), through the HTTP API on PostgreSQL.

Only owners and admins delete. One confirm is one command: a retry returns the same
answer and writes one audit event. The lead goes with its history, breaches and read
marks; messages, AI drafts and stage sends lose their words and bodies but keep their
ids and results; a send still waiting is dropped, one in flight is left to its sweep.
The audit event holds ids and counts, never a name, number or word.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.chats.models import LeadChatRead
from ac_platform.lead_desk.models import (
    Lead,
    LeadAiReply,
    LeadConversion,
    LeadConversionAttempt,
    LeadEvent,
    LeadMetaConversion,
    LeadSlaBreach,
    LeadSocialAccount,
    LeadSocialMessage,
    LeadWhatsAppMessage,
    LeadWhatsAppNumber,
)
from ac_platform.partner_events.models import PartnerLeadEvent, PartnerWebhookEndpoint
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_lead_desk_postgresql import _organisation

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/lead-desk"
NAMES = (
    "Asha Fictional",
    "Ravi Fictional",
    "Test Lead One",
    "Test Lead Two",
    "<test lead: dummy data for full_name>",  # Meta's Lead Ads Testing Tool
)
PHONE = "98765 43210"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _linked_rows(setup: Any, a: UUID, b: UUID) -> dict[str, UUID]:
    """Rows other parts of the product keep about leads A and B (fictional values)."""
    tenant, person, now = setup.state.tenant_id, setup.state.person_id, datetime.now(UTC)
    ids = {name: uuid4() for name in ("number", "page", "endpoint")}
    async with setup.sessions() as db, db.begin():
        db.add(
            LeadWhatsAppNumber(
                id=ids["number"],
                tenant_id=tenant,
                waba_id="1000000001",
                phone_number_id="2000000001",
                display_number="+91 90000 00000",
                token={"sealed": "fictional"},
                status="active",
                config={},
                connected_by_person_id=person,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            LeadSocialAccount(
                id=ids["page"],
                tenant_id=tenant,
                page_id="3000000001",
                page_name="Fictional Homes",
                token={"sealed": "fictional"},
                status="active",
                config={},
                connected_by_person_id=person,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            PartnerWebhookEndpoint(
                id=ids["endpoint"],
                tenant_id=tenant,
                url="https://partner.example.test/hook",
                secret_ref="AC_PARTNER_WEBHOOK_SECRET__FICTIONAL",  # noqa: S106 (a variable name)
                events=["lead.created", "lead.stage_changed"],
                status="active",
                events_since=now - timedelta(days=1),
                created_by="test",
                reason="fictional partner",
                created_at=now,
            )
        )
        await db.flush()
        ids["wa"] = uuid4()
        db.add(
            LeadWhatsAppMessage(
                id=ids["wa"],
                tenant_id=tenant,
                number_id=ids["number"],
                lead_id=a,
                wa_id="919000000001",
                direction="in",
                kind="text",
                body="Fictional words about a flat",
                media={"id": "5550000001"},
                status="received",
                meta_time=now,
                created_at=now,
            )
        )
        ids["social"] = uuid4()
        db.add(
            LeadSocialMessage(
                id=ids["social"],
                tenant_id=tenant,
                account_id=ids["page"],
                lead_id=a,
                channel="messenger",
                user_id="7000000001",
                user_name=NAMES[0],
                direction="in",
                mid="m_fictional_1",
                kind="text",
                body="Fictional words on Messenger",
                status="received",
                meta_time=now,
                created_at=now,
            )
        )
        ids["ai"] = uuid4()
        db.add(
            LeadAiReply(
                id=ids["ai"],
                tenant_id=tenant,
                lead_id=a,
                channel="whatsapp",
                mode="suggest",
                outcome="drafted",
                draft="A fictional draft reply",
                provider="gemini",
                model="fictional-model",
                input_tokens=120,
                output_tokens=40,
                cost_inr=Decimal("0.0123"),
                created_at=now,
            )
        )
        db.add(
            LeadSlaBreach(
                id=uuid4(),
                tenant_id=tenant,
                lead_id=a,
                kind="first_response",
                started_at=now - timedelta(minutes=20),
                due_at=now - timedelta(minutes=15),
                breached_at=now - timedelta(minutes=14),
                alerted=[],
                created_at=now,
            )
        )
        db.add(
            LeadChatRead(
                id=uuid4(),
                tenant_id=tenant,
                person_id=person,
                channel="whatsapp",
                account_id=ids["number"],
                lead_id=a,
                read_to=now - timedelta(minutes=1),
                created_at=now,
            )
        )
        conversion = {
            "tenant_id": tenant,
            "provider": "meta",
            "destination": "100000000000001",
            "stage_key": "new",
            "event_name": "Lead",
            "event_time": now,
            "payload": {"lead_id": "fictional"},
            "payload_sha256": "a" * 64,
            "test": False,
            "created_at": now,
        }
        ids["waiting"], ids["sent"] = uuid4(), uuid4()
        db.add(
            LeadConversion(
                id=ids["waiting"],
                lead_id=a,
                status="pending",
                attempts=0,
                next_attempt_at=now + timedelta(hours=1),
                **conversion,
            )
        )
        db.add(
            LeadConversion(
                id=ids["sent"],
                lead_id=b,
                status="delivered",
                attempts=1,
                next_attempt_at=now,
                delivered_at=now,
                last_http_status=200,
                **conversion,
            )
        )
        ids["meta"] = uuid4()
        db.add(
            LeadMetaConversion(
                id=ids["meta"],
                tenant_id=tenant,
                lead_id=a,
                source_event_id=uuid4(),
                dataset_id="100000000000001",
                stage="new",
                event_name="Lead",
                event_time=now,
                payload={"lead_id": "fictional"},
                payload_sha256="b" * 64,
                status="delivered",
                attempts=1,
                next_attempt_at=now,
                delivered_at=now,
                last_http_status=200,
                created_at=now,
            )
        )
        partner = {
            "endpoint_id": ids["endpoint"],
            "tenant_id": tenant,
            "payload": {"lead": "fictional"},
            "payload_sha256": "c" * 64,
            "attempts": 0,
            "replayed_attempts": 0,
            "next_attempt_at": now + timedelta(minutes=5),
            "occurred_at": now,
            "created_at": now,
        }
        ids["partner_waiting"], ids["partner_busy"], ids["partner_sent"] = (
            uuid4(),
            uuid4(),
            uuid4(),
        )
        db.add(
            PartnerLeadEvent(
                id=ids["partner_waiting"],
                lead_id=a,
                source_event_id=uuid4(),
                event_type="lead.created",
                status="pending",
                **partner,
            )
        )
        # A send in flight right now: its lease runs, so it is left to its sweep.
        db.add(
            PartnerLeadEvent(
                id=ids["partner_busy"],
                lead_id=a,
                source_event_id=uuid4(),
                event_type="lead.stage_changed",
                status="pending",
                leased_until=now + timedelta(minutes=10),
                **partner,
            )
        )
        db.add(
            PartnerLeadEvent(
                id=ids["partner_sent"],
                lead_id=b,
                source_event_id=uuid4(),
                event_type="lead.created",
                status="delivered",
                delivered_at=now,
                last_http_status=200,
                **{**partner, "attempts": 1},
            )
        )
        await db.flush()
        db.add(
            LeadConversionAttempt(
                conversion_id=ids["sent"],
                attempt=1,
                started_at=now,
                finished_at=now,
                http_status=200,
                duration_ms=120,
            )
        )
        # A recorded call on B: the call itself stays in Calls.
        db.add(
            LeadEvent(
                id=uuid4(),
                tenant_id=tenant,
                lead_id=b,
                kind="call",
                actor_person_id=person,
                data={"submission_id": str(uuid4()), "simulated": False},
                created_at=now,
            )
        )
    return ids


def test_owners_and_admins_delete_chosen_leads_for_good(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            manager = await seed(setup.engine, tenant_id=tenant, role="manager")
            manager_token = await _session(setup, manager)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def post(path: str, body: dict[str, Any]) -> httpx.Response:
                    return await client.post(f"{BASE}{path}", json=body, headers=WRITE)

                as_(setup.token)
                leads: list[UUID] = []
                for index, name in enumerate(NAMES):
                    added = await post(
                        "/leads",
                        {
                            "command_id": str(uuid4()),
                            "name": name,
                            "phone": PHONE if index == 0 else None,
                            "city": "Pune",
                            "assign": "me",
                        },
                    )
                    assert added.status_code == 201, added.text
                    leads.append(UUID(added.json()["lead"]["lead_id"]))
                a, b, c, d, meta_test = leads
                noted = await post(f"/leads/{a}/notes", {"command_id": str(uuid4()), "note": "x"})
                assert noted.status_code == 200, noted.text
                async with setup.sessions() as db, db.begin():
                    await db.execute(update(Lead).where(Lead.id.in_([c, d])).values(test_data=True))
                ids = await _linked_rows(setup, a, b)

                # Test leads, and Meta's testing-tool leads, are one filter away.
                tests = (await client.get(f"{BASE}/leads?scope=team&test=only")).json()
                assert {row["lead_id"] for row in tests["leads"]} == {
                    str(c),
                    str(d),
                    str(meta_test),
                }
                assert (await client.get(f"{BASE}/leads?test=all")).status_code == 422

                # Sellers can't delete, not even a lead of their own.
                as_(seller_token)
                refused = await post(
                    "/leads/delete", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert refused.status_code == 403
                assert refused.json()["detail"] == "Only owners and admins delete leads."
                one = await post(f"/leads/{a}/delete", {"command_id": str(uuid4())})
                assert one.status_code == 403
                # Sales managers manage the team's leads but don't delete them (Roles B).
                as_(manager_token)
                refused = await post(
                    "/leads/delete", {"command_id": str(uuid4()), "lead_ids": [str(a)]}
                )
                assert refused.status_code == 403
                assert refused.json()["detail"] == "Only owners and admins delete leads."

                as_(setup.token)
                assert (
                    await post("/leads/delete", {"command_id": str(uuid4()), "lead_ids": []})
                ).status_code == 422
                too_many = [str(uuid4()) for _ in range(deletion.MAX_LEADS + 1)]
                assert (
                    await post("/leads/delete", {"command_id": str(uuid4()), "lead_ids": too_many})
                ).status_code == 422
                without_origin = await client.post(
                    f"{BASE}/leads/{a}/delete", json={"command_id": str(uuid4())}
                )
                assert without_origin.status_code == 403

                # One lead from its own sheet; the same confirm again changes nothing.
                first = str(uuid4())
                gone = await post(f"/leads/{a}/delete", {"command_id": first})
                assert gone.status_code == 200, gone.text
                assert gone.json() == {
                    "schema": "lead-desk/1",
                    "deleted": 1,
                    "lead_ids": [str(a)],
                    "not_found": 0,
                }
                again = await post(f"/leads/{a}/delete", {"command_id": first})
                assert again.status_code == 200 and again.json() == gone.json()
                missing = await post(f"/leads/{a}/delete", {"command_id": str(uuid4())})
                assert missing.status_code == 404
                assert (await client.get(f"{BASE}/leads/{a}")).status_code == 404

                # Many at once: leads already gone or from elsewhere are only counted.
                second = str(uuid4())
                bulk = await post(
                    "/leads/delete",
                    {
                        "command_id": second,
                        "lead_ids": [str(b), str(c), str(a), str(uuid4()), str(b)],
                    },
                )
                assert bulk.status_code == 200, bulk.text
                assert bulk.json()["deleted"] == 2
                assert bulk.json()["lead_ids"] == [str(b), str(c)]
                assert bulk.json()["not_found"] == 2
                page = (await client.get(f"{BASE}/leads?scope=team")).json()
                assert {row["lead_id"] for row in page["leads"]} == {str(d), str(meta_test)}

            async with setup.sessions() as db:
                gone_ids = [a, b, c]
                assert await db.scalar(select(func.count()).select_from(Lead)) == 2
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(LeadEvent)
                        .where(LeadEvent.lead_id.in_(gone_ids))
                    )
                    == 0
                )
                assert await db.scalar(select(func.count()).select_from(LeadSlaBreach)) == 0
                assert await db.scalar(select(func.count()).select_from(LeadChatRead)) == 0

                wa = await db.get(LeadWhatsAppMessage, ids["wa"])
                assert wa is not None and wa.body is None and wa.media is None
                assert wa.erased_at is not None and wa.status == "received"
                social = await db.get(LeadSocialMessage, ids["social"])
                assert social is not None and social.body is None and social.user_name is None
                assert social.mid == "m_fictional_1" and social.erased_at is not None
                ai = await db.get(LeadAiReply, ids["ai"])
                assert ai is not None and ai.draft is None and ai.erased_at is not None
                assert ai.cost_inr == Decimal("0.0123") and ai.output_tokens == 40

                waiting = await db.get(LeadConversion, ids["waiting"])
                assert waiting is not None and waiting.status == "dropped"
                assert waiting.last_error_code == "lead_gone" and waiting.payload is None
                sent = await db.get(LeadConversion, ids["sent"])
                assert sent is not None and sent.status == "delivered" and sent.payload is None
                assert sent.last_error_code is None and sent.erased_at is not None
                assert await db.scalar(select(func.count()).select_from(LeadConversionAttempt)) == 1
                meta = await db.get(LeadMetaConversion, ids["meta"])
                assert meta is not None and meta.status == "delivered" and meta.payload is None

                partner_waiting = await db.get(PartnerLeadEvent, ids["partner_waiting"])
                assert partner_waiting is not None and partner_waiting.status == "dropped"
                assert partner_waiting.last_error_code == "lead_gone"
                assert partner_waiting.payload is None and partner_waiting.erased_at is not None
                busy = await db.get(PartnerLeadEvent, ids["partner_busy"])
                assert busy is not None and busy.status == "pending" and busy.payload is not None
                partner_sent = await db.get(PartnerLeadEvent, ids["partner_sent"])
                assert partner_sent is not None and partner_sent.status == "delivered"
                assert partner_sent.payload is None

                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant,
                            AuditEvent.action == deletion.AUDIT_ACTION,
                        )
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [event.resource_id for event in events] == [first, second]
                single, many = events
                assert single.actor_person_id == setup.state.person_id
                assert single.session_id == setup.state.session_id
                assert single.resource_type == deletion.AUDIT_RESOURCE
                assert single.payload["lead_ids"] == [str(a)]
                assert single.payload["removed"] == {
                    "events": 3,
                    "sla_breaches": 1,
                    "chat_reads": 1,
                    "task_reminders": 0,
                    "tasks": 0,
                    "meetings": 0,
                    "leads": 1,
                }
                assert single.payload["emptied"] == {
                    "whatsapp_messages": 1,
                    "social_messages": 1,
                    "ai_replies": 1,
                    "stage_events": 1,
                    "meta_stage_events": 1,
                    "partner_events": 1,
                }
                assert many.payload["deleted"] == 2 and many.payload["not_found"] == 2
                assert many.payload["kept"] == {"call_facts": 0, "recorded_calls": 1}
                assert many.payload["emptied"]["stage_events"] == 1
                assert many.payload["emptied"]["partner_events"] == 1
                words = json.dumps([single.payload, many.payload])
                for private in (*NAMES, "Pune", "9876543210", "Fictional words", "draft"):
                    assert private not in words
                assert (await verify_audit_chain(db, tenant)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())
