#!/usr/bin/env python3
"""Fictional fixture for the isolated AWS rehearsal, never a live-data seed.

Uses the ORM fixture pattern from tests/database/test_conversation_postgresql.py
and the production private storage adapter. Dev seed executables deliberately
reject this hostname; their guards are preserved. Run in an API-image one-shot
with /fixture pointing at the rehearsal directory and a fictional marker.
"""

import asyncio
import hashlib
import hmac
import io
import json
import os
import secrets
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.storage import (
    PrivateLocalRecordingStorage,
    SourceAudioKey,
)
from ac_platform.identity.models import Person, Session
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.integrations.models import (
    IntegrationOAuthClient,
    IntegrationOAuthGrant,
    IntegrationOAuthToken,
)
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.tenancy.models import Membership, Organisation, Tenant


async def main():
    root = Path("/fixture")
    if (
        not (root / "FICTIONAL-ONLY").is_file()
        or os.environ.get("AC_REHEARSAL_ACK") != "fictional-aws-only"
    ):
        raise SystemExit("Refusing non-rehearsal fixture")
    url = os.environ["AC_DATABASE_URL"]
    if "@pgbouncer:6432/ac_platform" not in url:
        raise SystemExit("Only the isolated Compose pooler is allowed")
    ids = json.loads((root / "fixture-ids.json").read_text())
    tenant, owner = UUID(ids["tenant"]), UUID(ids["owner"])
    engine = create_async_engine(url, hide_parameters=True)
    now = datetime.now(UTC)
    sellers = [owner] + [uuid4() for _ in range(9)]
    principal_person, principal = uuid4(), uuid4()
    cookies, bearers = [], []
    async with AsyncSession(engine) as db, db.begin():
        if await db.scalar(select(func.count()).select_from(Tenant)):
            raise SystemExit("Refusing fixture insertion into a nonempty database")
        db.add(Tenant(id=tenant, slug="fictional-aws-rehearsal", name="Fictional AWS Rehearsal"))
        await db.flush()
        for i, person in enumerate([*sellers, principal_person]):
            db.add(
                Person(
                    id=person,
                    email=f"fictional-seller-{i}@example.test",
                    display_name=f"Fictional Seller {i}",
                    email_verified_at=now,
                )
            )
        await db.flush()
        for i, person in enumerate([*sellers, principal_person]):
            db.add(
                Membership(tenant_id=tenant, person_id=person, role="admin" if i == 0 else "member")
            )
            db.add(SalesXrayProfile(person_id=person, phone_number_e164=f"+1415555{100 + i:04d}"))
        await db.flush()
        db.add(
            Organisation(
                tenant_id=tenant,
                created_by_person_id=owner,
                creation_command_id=uuid4(),
                domain_verification_token=secrets.token_hex(32),
            )
        )
        db.add(
            ConversationProcessingPrincipal(
                id=principal,
                tenant_id=tenant,
                person_id=principal_person,
                operator_reference="ref:rehearsal:fictional",
                created_at=now,
            )
        )
        client_id = "rehearsal-" + secrets.token_hex(10)
        db.add(
            IntegrationOAuthClient(
                id=uuid4(),
                client_id=client_id,
                tenant_id=None,
                name="Fictional Rehearsal",
                redirect_uris=["https://fictional.example.test/callback"],
                created_at=now,
            )
        )
        await db.flush()
        for person in sellers:
            token = secrets.token_urlsafe(32)
            cookies.append(token)
            db.add(
                Session(
                    id=uuid4(),
                    person_id=person,
                    selected_tenant_id=tenant,
                    token_hash=hmac.new(
                        os.environ["AC_SESSION_TOKEN_PEPPER"].encode(),
                        token.encode(),
                        hashlib.sha256,
                    ).digest(),
                    expires_at=now + timedelta(days=1),
                )
            )
            grant, bearer = uuid4(), "sxa_" + secrets.token_hex(20)
            bearers.append(bearer)
            db.add(
                IntegrationOAuthGrant(
                    id=grant,
                    client_id=client_id,
                    tenant_id=tenant,
                    person_id=person,
                    scopes=["calls:write", "calls:read", "leads:read"],
                    created_at=now,
                )
            )
            await db.flush()
            db.add(
                IntegrationOAuthToken(
                    id=uuid4(),
                    grant_id=grant,
                    kind="access",
                    token_sha256=hashlib.sha256(bearer.encode()).hexdigest(),
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
        await db.flush()
        lead_ids = []
        for i in range(2000):
            lead = uuid4()
            lead_ids.append(lead)
            person = sellers[i % 10]
            db.add(
                Lead(
                    id=lead,
                    tenant_id=tenant,
                    revision=1,
                    source="synthetic",
                    source_ref=f"fictional-{i}",
                    source_label="AWS rehearsal",
                    payload={"fictional": True},
                    name=f"Fictional Lead {i}",
                    phone=f"+1415555{i:04d}",
                    email=f"lead-{i}@example.test",
                    stage="new",
                    owner_person_id=person,
                    owner_reason="Fictional capacity fixture",
                    assigned_at=now,
                    next_action_at=now,
                    attempts=0,
                    calls=0,
                    repeats=0,
                    test_data=True,
                    created_by_person_id=owner,
                    created_at=now,
                    updated_at=now,
                )
            )
        await db.flush()
        events = []
        for i, lead in enumerate(lead_ids):
            for j in range(5):
                events.append(
                    dict(
                        id=uuid4(),
                        tenant_id=tenant,
                        lead_id=lead,
                        kind="note",
                        actor_person_id=sellers[i % 10],
                        command_id=uuid4(),
                        data={"note": "Fictional rehearsal note", "fixture": True},
                        created_at=now - timedelta(minutes=j),
                    )
                )
        await db.execute(LeadEvent.__table__.insert(), events)
        storage = PrivateLocalRecordingStorage(Path(os.environ["AC_SALES_XRAY_STORAGE_ROOT"]))
        for i in range(300):
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(bytes([i % 256, 0]) * 8000)
            raw = buffer.getvalue()
            sha = hashlib.sha256(raw).hexdigest()
            storage.put(
                SourceAudioKey(tenant, sha), [raw], expected_sha256=sha, expected_bytes=len(raw)
            )
            permission, recording, usage, lease, submission = (uuid4() for _ in range(5))
            db.add(
                ConversationPermission(
                    id=permission,
                    tenant_id=tenant,
                    person_id=principal_person,
                    source_sha256=sha,
                    provider="local",
                    permission_reference="synthetic-fixture:local-analysis",
                    retention_reference="synthetic-fixture:delete-after-test",
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                    retention_until=now + timedelta(days=2),
                )
            )
            await db.flush()
            db.add(
                ConversationRecording(
                    id=recording,
                    tenant_id=tenant,
                    person_id=principal_person,
                    permission_id=permission,
                    request_key=f"fictional-{i}",
                    intent_sha256=sha,
                    source_sha256=sha,
                    source_bytes=len(raw),
                    content_type="audio/wav",
                    source_revision=1,
                    generation=1,
                    state="ready",
                    created_at=now,
                )
            )
            db.add(
                ConversationAcquisitionUsage(
                    id=usage,
                    tenant_id=tenant,
                    person_id=sellers[i % 10],
                    submission_id=submission,
                    source_sha256=sha,
                    duration_evidence_sha256=sha,
                    reserved_seconds=1,
                    policy_revision="fictional-rehearsal-v1",
                    created_at=now,
                )
            )
            await db.flush()
            db.add(
                ConversationProcessingLease(
                    id=lease,
                    principal_id=principal,
                    tenant_id=tenant,
                    person_id=principal_person,
                    usage_id=usage,
                    created_at=now,
                    expires_at=now + timedelta(days=1),
                )
            )
            await db.flush()
            db.add(
                ConversationGuestSubmission(
                    tenant_id=tenant,
                    submission_id=submission,
                    person_id=principal_person,
                    recording_id=recording,
                    processing_lease_id=lease,
                    usage_id=usage,
                    source_sha256=sha,
                    capture_source="web_upload",
                    created_at=now,
                )
            )
    # Private tunnel-only test adapter injects credentials here; k6 on ac never gets them.
    routes = []
    for i, (cookie, bearer) in enumerate(zip(cookies, bearers, strict=True)):
        routes.append(f"""@seller{i} header X-Rehearsal-Seller {i}
handle @seller{i} {{
 reverse_proxy api:8000 {{
  header_up Host salesxray.authorityclosers.com
  header_up Cookie "__Host-ac_session={cookie}"
  header_up Authorization "Bearer {bearer}"
 }}
}}
""")
    (root / "auth.caddy").write_text("\n".join(routes))
    (root / "auth.caddy").chmod(0o600)
    (root / "fixture-summary.json").write_text(
        json.dumps(dict(sellers=10, processing_principals=1, leads=2000, events=10000, calls=300))
    )
    await engine.dispose()
    print(
        "Fictional seed committed: 10 sellers + nonlogin principal; "
        "2000 leads; 10000 events; 300 tiny WAV calls"
    )


if __name__ == "__main__":
    asyncio.run(main())
