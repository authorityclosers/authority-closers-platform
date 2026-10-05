"""Fictional HTTP two-call identity confirmation, privacy and admission proof."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspect,
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.reports import parse_report_draft
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call, store
from tests.unit.conversation_intelligence.test_reports import _payload, _transcript

PREFIX = "/v1/conversation/prospects"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def snapshot(
    setup: Any,
    submission: UUID,
    *,
    role: str = "prospect",
    value: str = "Fictional Studio",
    corrupt: bool = False,
) -> UUID:
    async with setup.sessions() as db, db.begin():
        identifier = await db.scalar(
            select(ConversationGuestSubmission.recording_id).where(
                ConversationGuestSubmission.submission_id == submission
            )
        )
        rec = await db.get(ConversationRecording, identifier)
        assert rec is not None
        transcript = _transcript(count=1)
        transcript["source_sha256"] = rec.source_sha256
        transcript["revision"] = "fictional-" + str(rec.id)
        transcript["segments"][0]["text"] = "Native line 1: I run Fictional Studio."
        report = parse_report_draft(_payload(transcript), transcript).model_dump(mode="json")
        report["call_map"] = {
            "version": "call-map/1",
            "verdict_line": "Stated company detail.",
            "call_purpose": {"kind": "unclear", "evidence": []},
            "speakers": [{"speaker_id": "speaker_1", "role": role}],
            "phases": [{"name": "opening", "start_ms": 0}],
            "time_promise": None,
            "outcome": {
                "kind": "none",
                "next_step_rung": "none",
                "next_step_when": None,
                "evidence": [],
            },
            **{
                key: []
                for key in [
                    "signals",
                    "pitch_items",
                    "pains",
                    "money",
                    "claims",
                    "qualification_gaps",
                    "qualification_confirmed",
                    "prospect_tasks",
                    "seller_tasks",
                    "objections",
                ]
            },
            "prospect_facts": [
                {
                    "key": "company",
                    "text": value,
                    "evidence": [{"segment_id": "s1", "quote": "I run Fictional Studio."}],
                }
            ],
        }
        built = {}
        for stage, parents, payload in [
            ("C0", [], {}),
            ("C1", ["C0"], {}),
            ("C2", ["C0"], transcript),
            ("C3", ["C1", "C2"], {}),
            ("C4", ["C2", "C3"], {}),
            ("C5", ["C4"], report),
        ]:
            cp = build_checkpoint(
                binding_for(rec),
                stage,
                "fictional-confirmation-v1",
                {},
                [built[p] for p in parents],
                content_hash(payload),
            )
            built[stage] = cp
            row = ConversationCheckpoint(
                id=uuid4(),
                tenant_id=rec.tenant_id,
                person_id=rec.person_id,
                recording_id=rec.id,
                stage=stage,
                cache_key=cp.cache_key,
                manifest_sha256=cp.manifest_sha256,
                payload_sha256="0" * 64 if corrupt and stage == "C5" else cp.payload_sha256,
                feature_blob_id=None,
                manifest=cp.as_dict(),
                payload=payload,
                created_at=setup.state.now,
            )
            db.add(row)
        return rec.id


def test_two_call_suggestion_confirmation_is_explicit_idempotent_and_audited(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second = await direct_call(setup), await direct_call(setup)
            await snapshot(setup, first)
            await snapshot(setup, second)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app),
                base_url=ORIGIN,
                headers={"Origin": ORIGIN},
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                created = await client.post(
                    f"{PREFIX}/calls/{first}/create", json={"display_name": "Mehta Example"}
                )
                assert created.status_code == 201, created.text
                prospect_id = created.json()["membership"]["prospect_id"]
                response = await client.get(f"{PREFIX}/calls/{second}/suggestions")
                assert response.status_code == 200, response.text
                page = response.json()
                assert page["membership"] is None and len(page["suggestions"]) == 1
                suggestion = page["suggestions"][0]
                assert suggestion["prospect_id"] == prospect_id and suggestion["confirmed"] is False
                assert suggestion["previous_call_at"] and "confidence" not in suggestion
                detail = suggestion["details"][0]
                assert detail["key"] == "company" and detail["text"] == "Fictional Studio"
                assert detail["current"]["submission_id"] == str(second)
                assert detail["previous"]["submission_id"] == str(first)
                assert detail["current"]["evidence"][0]["quote"] == "I run Fictional Studio."
                assert (await client.get(PREFIX + f"/{prospect_id}")).json()["prospect"][
                    "call_count"
                ] == 1
                body = {"prospect_id": prospect_id, "expected_membership_id": None}
                assert (
                    await client.post(
                        f"{PREFIX}/calls/{second}/confirm",
                        json={**body, "expected_membership_id": str(uuid4())},
                    )
                ).status_code == 409
                confirmed = await client.post(f"{PREFIX}/calls/{second}/confirm", json=body)
                assert confirmed.status_code == 200, confirmed.text
                repeated = await client.post(f"{PREFIX}/calls/{second}/confirm", json=body)
                assert repeated.json() == confirmed.json()
                history = (await client.get(PREFIX + f"/{prospect_id}")).json()
                assert history["prospect"]["call_count"] == 2
                assert {c["submission_id"] for c in history["calls"]} == {str(first), str(second)}
                assert (await client.get(f"{PREFIX}/calls/{second}/suggestions")).json()[
                    "suggestions"
                ] == []
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(ConversationProspectMembership)
                        )
                        == 2
                    )
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(AuditEvent)
                            .where(AuditEvent.action == "conversation.prospect_call_linked")
                        )
                        == 2
                    )
                    assert (await verify_audit_chain(db, tenant_id=setup.state.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_confirmation_denies_foreign_calls_prospects_and_unsafe_admission(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            own = await direct_call(setup)
            other = await seed(setup.engine, tenant_id=setup.state.tenant_id, role="member")
            foreign = await seed(setup.engine)
            hidden = await direct_call(setup, other.actor)
            foreign_call = uuid4()
            async with setup.sessions() as db, db.begin():
                hidden_prospect = await store(setup, db).create_from_call(
                    other.actor, hidden, display_name="Hidden Example"
                )
                foreign_prospect = ConversationProspect(
                    id=uuid4(),
                    tenant_id=foreign.tenant_id,
                    display_name="Foreign Example",
                    created_by_person_id=foreign.person_id,
                    owner_person_id=foreign.person_id,
                    revision=1,
                    created_at=foreign.now,
                    updated_at=foreign.now,
                )
                db.add(foreign_prospect)
                # Organisation-wide read permission must not become write authority.
                db.add(
                    Organisation(
                        tenant_id=setup.state.tenant_id,
                        created_by_person_id=setup.state.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="fictional-token-" * 4,
                    )
                )
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == setup.state.tenant_id,
                        Membership.person_id == setup.state.person_id,
                    )
                    .values(role="admin")
                )
                hidden_id, foreign_id = hidden_prospect.id, foreign_prospect.id
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                path = f"{PREFIX}/calls/{own}/confirm"
                body = {"prospect_id": str(hidden_id), "expected_membership_id": None}
                assert (
                    await client.post(path, json=body, headers={"Origin": ORIGIN})
                ).status_code == 401
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await client.post(path, json=body)).status_code == 403
                assert (
                    await client.post(
                        path, json=body, headers={"Origin": "https://evil.example.test"}
                    )
                ).status_code == 403
                client.headers["Origin"] = ORIGIN
                for target in [hidden_id, foreign_id]:
                    assert (
                        await client.post(path, json={**body, "prospect_id": str(target)})
                    ).status_code == 404
                assert (await client.get(PREFIX + f"/{hidden_id}")).status_code == 200
                for call in [hidden, foreign_call]:
                    assert (
                        await client.get(f"{PREFIX}/calls/{call}/suggestions")
                    ).status_code == 404
                    assert (
                        await client.post(f"{PREFIX}/calls/{call}/confirm", json=body)
                    ).status_code == 404
                assert (
                    await client.post(path + "?tenant_id=" + str(setup.state.tenant_id), json=body)
                ).status_code == 422
                assert (
                    await client.post(path, json={**body, "person_id": str(other.person_id)})
                ).status_code == 422
                assert (
                    await client.post(path, json={"prospect_id": str(hidden_id)})
                ).status_code == 422
                assert (
                    await client.post(
                        path,
                        content='{"prospect_id":"'
                        + str(hidden_id)
                        + '","name":"'
                        + "x" * 3000
                        + '"}',
                        headers={"content-type": "application/json"},
                    )
                ).status_code == 413
                assert (
                    await client.post("https://learner.example.test" + path, json=body)
                ).status_code == 404
                assert (
                    await client.get(f"{PREFIX}/calls/{own}/suggestions?offset=0&offset=1")
                ).status_code == 422
                client.cookies.set(setup.settings.session_cookie_name, await _session(setup, other))
                assert (await client.get(PREFIX)).json()["total"] == 1
                client.cookies.set(
                    setup.settings.session_cookie_name, await _session(setup, foreign)
                )
                assert (await client.post(path, json=body)).status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_suggestion_query_count_is_fixed_and_older_page_keeps_matches(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    import ac_platform.conversation_intelligence.prospect_suggestions as service

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        statements: list[str] = []

        def count(
            _conn: Any, _cursor: Any, statement: str, _parameters: Any, _context: Any, _many: Any
        ) -> None:
            statements.append(statement)

        try:
            current = await direct_call(setup)
            await snapshot(setup, current)
            event.listen(setup.engine.sync_engine, "before_cursor_execute", count)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                counts = []
                for size in range(3):
                    if size:
                        previous = await direct_call(setup)
                        await snapshot(setup, previous)
                        async with setup.sessions() as db, db.begin():
                            await store(setup, db).create_from_call(
                                setup.state.actor, previous, display_name=f"Fictional {size}"
                            )
                    statements.clear()
                    page = await client.get(f"{PREFIX}/calls/{current}/suggestions")
                    assert page.status_code == 200, page.text
                    counts.append(len(statements))
                    assert len(page.json()["suggestions"]) == size
                assert len(set(counts)) == 1 and counts[0] <= 45
                monkeypatch.setattr(service, "PAGE_SIZE", 1)
                first = (await client.get(f"{PREFIX}/calls/{current}/suggestions")).json()
                second = (await client.get(f"{PREFIX}/calls/{current}/suggestions?offset=1")).json()
                assert first["next_offset"] == 1 and second["next_offset"] is None
                assert len(first["suggestions"]) == len(second["suggestions"]) == 1
                assert (
                    first["suggestions"][0]["prospect_id"]
                    != second["suggestions"][0]["prospect_id"]
                )
        finally:
            event.remove(setup.engine.sync_engine, "before_cursor_execute", count)
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("change", ["seller", "unsupported", "corrupt", "withheld"])
def test_suggestions_require_supported_private_source_details(
    postgres_harness: Any, tmp_path: Path, change: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first, second = await direct_call(setup), await direct_call(setup)
            rec_id = await snapshot(
                setup,
                first,
                role="seller" if change == "seller" else "prospect",
                value="Invented Ltd" if change == "unsupported" else "Fictional Studio",
                corrupt=change == "corrupt",
            )
            await snapshot(setup, second)
            async with setup.sessions() as db, db.begin():
                await store(setup, db).create_from_call(
                    setup.state.actor, first, display_name="Fictional Example"
                )
                if change == "withheld":
                    await SensitiveSegmentsStore(db).mark(
                        setup.state.actor,
                        recording_id=rec_id,
                        transcript_revision="fictional-" + str(rec_id),
                        segments=[("s1", "SENSITIVE_FINANCIAL")],
                        reason_ref="AUT-1069",
                        idempotency_key="fictional-confirm-privacy",
                    )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                response = await client.get(f"{PREFIX}/calls/{second}/suggestions")
                assert response.status_code == 200, response.text
                assert response.json()["suggestions"] == []
        finally:
            await setup.engine.dispose()

    run(exercise())
