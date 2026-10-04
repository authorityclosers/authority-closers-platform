"""Whole-library counts cost admission, one authority check and one count statement."""

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
from sqlalchemy import event, select

from ac_platform.conversation_intelligence.acquisition_library import account_library_summary
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationPermission,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.providers import ProviderResult, scribe_transcript
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from ac_platform.conversation_intelligence.retained_c5_recovery import (
    RetainedC5Correction,
    RetainedC5CorrectionIntent,
    RetainedC5RecoveryService,
)
from tests.database.test_conversation_account_library_postgresql import (
    _session,
    _upload,
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL fixture
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reports_postgresql import _intent
from tests.database.test_conversation_retained_c5_recovery_postgresql import (
    _seed_guest_retained_case,
)
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup

COUNTS = {"total": 25, "processing": 2, "completed": 2, "needs_attention": 1}
PLAN_BUCKETS = {"active": "processing", "held": "needs_attention"}


async def _mixed_library(case, client, postgres, tmp_path):
    """One row table drives buckets, excluded rows, and the all-page drift proof."""
    setup = case["setup"]
    correction = RetainedC5Correction(
        path="/strengths/0/evidence/0/quote",
        old_sha256=hashlib.sha256(b"Wrong quote").hexdigest(),
        new_text="Buyer asks about price and timing.",
        source_segment_ids=("seg-1",),
        rationale="Fictional transcript supplies the exact quote.",
    )
    async with setup.sessions() as db, db.begin():
        recovered = await RetainedC5RecoveryService(
            ConversationApplication(db, clock=lambda: setup.clock[0]),
            recording_tenant_ids=(setup.state.tenant_id,),
        ).revalidate(
            replace(setup.state.actor, permissions=frozenset({"admin_surface"})),
            case["run_id"],
            original_raw_sha256=case["raw_sha256"],
            key="summary-retained",
            storage=setup.runtime.storage,
            correction=RetainedC5CorrectionIntent(
                original_raw_sha256=case["raw_sha256"],
                corrections=(correction,),
                correction_payload_sha256=content_hash([correction.model_dump(mode="json")]),
            ),
        )
        assert recovered["report"] is not None
        await setup.factory(db).claim(setup.guest.token, setup.state.actor)
    expected = {str(case["submission_id"]): "completed"}
    # 25 visible rows: retained-only guest, draft, all plan states, and no plan.
    cases = [
        ("draft", "active"),
        *[
            ("direct", state)
            for state in ("active", "active", "held", "quoted", "cancelled", "completed")
        ],
        *[("direct", None)] * 17,
        *[(excluded, None) for excluded in ("revoked", "expired", "deleting", "deleted")],
    ]
    for kind, state in cases:
        upload = await _upload(client)
        async with setup.sessions() as db, db.begin():
            link = await db.scalar(
                select(ConversationGuestSubmission).where(
                    ConversationGuestSubmission.submission_id == UUID(upload["submission_id"])
                )
            )
            recording = await db.get(ConversationRecording, link.recording_id)
            permission = await db.get(ConversationPermission, recording.permission_id)
            binding = dict(
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
            )
            if state:
                command = await db.scalar(
                    select(ConversationCommand).where(
                        ConversationCommand.tenant_id == recording.tenant_id,
                        ConversationCommand.person_id == recording.person_id,
                    )
                )
                db.add(
                    ConversationProcessingPlan(
                        id=uuid4(),
                        **binding,
                        processing_lease_id=link.processing_lease_id,
                        generation=recording.generation,
                        plan_sha256="a" * 64,
                        manifest={},
                        acceptance_command_id=command.id if state == "active" else None,
                        state=state,
                        progress={},
                        next_check_at=setup.clock[0],
                        created_at=setup.clock[0],
                        expires_at=setup.clock[0] + timedelta(hours=1),
                    )
                )
            if kind == "draft":
                intent = _intent(recording.source_sha256)
                raw = intent.raw_transcription_json.encode()
                normalized = scribe_transcript(
                    ProviderResult(
                        provider="elevenlabs",
                        model="scribe_v2",
                        request_id=None,
                        response_sha256=intent.receipt.transcription_response_sha256,
                        raw_json=raw,
                        data=json.loads(raw),
                        input_sha256=recording.source_sha256,
                    ),
                    duration_ms=1000,
                    source_sha256=recording.source_sha256,
                )
                normalized["duration_ms"] = 1000
                payload = parse_report_draft(
                    intent.report, normalized, source_label="Your sales call"
                ).model_dump(mode="json")
                transcript = {
                    "native_json": intent.raw_transcription_json,
                    "normalized": normalized,
                }
                receipt = intent.receipt.model_dump(mode="json")
                local_run = await db.scalar(
                    select(ConversationRun).where(ConversationRun.recording_id == recording.id)
                )
                db.add(
                    ConversationReportDraft(
                        id=uuid4(),
                        **binding,
                        run_id=local_run.id,
                        source_revision=recording.source_revision,
                        source_sha256=recording.source_sha256,
                        report_sha256=content_hash(payload),
                        transcript_sha256=content_hash(transcript),
                        profile_sha256=content_hash(load_report_profile()),
                        evidence_receipt_sha256=content_hash(receipt),
                        payload=payload,
                        transcript=transcript,
                        evidence_receipt=receipt,
                        created_at=setup.clock[0],
                    )
                )
            if kind == "revoked":
                permission.revoked_at = setup.clock[0]
            elif kind == "expired":
                permission.retention_until = setup.clock[0] + timedelta(seconds=1)
            elif kind in {"deleting", "deleted"}:
                recording.state = kind
            else:
                expected[upload["submission_id"]] = (
                    "completed" if kind == "draft" else PLAN_BUCKETS.get(state, "total_only")
                )
    # Valid uploads outside this account and tenant must not affect the counts.
    other = await seed(setup.engine, tenant_id=setup.state.tenant_id)
    client.cookies.set("ac_session", await _session(setup, other))
    await _upload(client)
    client.cookies.set("ac_session", setup.token)
    (tmp_path / "foreign").mkdir()
    foreign = await _setup(postgres, tmp_path / "foreign")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=foreign.app), base_url=ORIGIN
        ) as stranger:
            stranger.cookies.set("ac_session", foreign.token)
            await _upload(stranger)
    finally:
        await foreign.engine.dispose()
    setup.clock[0] += timedelta(seconds=2)
    return expected


def test_mixed_summary_matches_all_pages_in_one_read_only_statement(postgres_harness, tmp_path):  # noqa: F811
    async def exercise():
        case = await _seed_guest_retained_case(postgres_harness, tmp_path)
        setup = case["setup"]
        statements = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                assert (await client.get(PREFIX + "/submissions/summary")).json() == dict.fromkeys(
                    COUNTS, 0
                )
                expected = await _mixed_library(case, client, postgres_harness, tmp_path)
                async with setup.sessions() as db, db.begin():
                    ownership = GuestOwnership(setup.factory(db))
                    await ownership.sessions._owner(
                        None, setup.state.actor, await ownership.sessions._admit()
                    )

                    def capture(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)

                    event.listen(setup.engine.sync_engine, "before_cursor_execute", capture)
                    try:
                        await ownership.sessions._owner(
                            None, setup.state.actor, await ownership.sessions._admit()
                        )
                        admission = len(statements)
                        statements.clear()
                        counts = await account_library_summary(ownership, setup.state.actor)
                    finally:
                        event.remove(setup.engine.sync_engine, "before_cursor_execute", capture)
                    assert len(statements) == admission + 2
                    authority = " ".join(statements[admission].lower().split())
                    assert "from memberships join organisations" in authority
                    assert "memberships.person_id =" in authority
                    assert "memberships.tenant_id =" in authority
                    assert authority.endswith("for share")
                    assert statements[-1].lstrip().upper().startswith("SELECT COUNT(")
                    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
                assert counts == COUNTS
                assert (await client.get(PREFIX + "/submissions/summary")).json() == counts
                actual, page_sizes, cursor = {}, [], None
                while True:
                    response = await client.get(
                        PREFIX + "/submissions", params={"before": cursor} if cursor else {}
                    )
                    assert response.status_code == 200
                    page = response.json()
                    page_sizes.append(len(page["submissions"]))
                    for row in page["submissions"]:
                        actual[row["submission_id"]] = (
                            "completed"
                            if row["has_report"]
                            else PLAN_BUCKETS.get(row["state"], "total_only")
                        )
                    cursor = page["next_cursor"]
                    if cursor is None:
                        break
                assert page_sizes == [20, 5] and actual == expected
                assert counts == {
                    "total": len(actual),
                    **{
                        bucket: sum(value == bucket for value in actual.values())
                        for bucket in ("processing", "completed", "needs_attention")
                    },
                }
        finally:
            await setup.engine.dispose()

    run(exercise())
