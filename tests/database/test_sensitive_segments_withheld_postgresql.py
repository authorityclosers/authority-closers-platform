"""Every reader surface withholds marked-segment text (AUT-519 D3–D5, AUT-521), on PostgreSQL.

Runs on the offline review fixture (fictional audio and transcript). Proof is by
counts, markers and hashes; the marked segment's text is never asserted on.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence import sensitive_segments_cli as cli
from ac_platform.conversation_intelligence import sensitive_segments_store as store_module
from ac_platform.conversation_intelligence.admin_reports import AdminConversationReports
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
)
from ac_platform.conversation_intelligence.report_export import report_docx_bytes
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    grams,
    markers,
    shared_grams,
)
from ac_platform.conversation_intelligence.sensitive_segments_cli import docx_text
from ac_platform.conversation_intelligence.sensitive_segments_store import SensitiveSegmentsStore
from tests.database.test_conversation_inference_postgresql import FakeBroker
from tests.database.test_conversation_reviews_postgresql import (
    ReviewCase,
    _build_report_case,
    _create_assignment,
    _service,
    run,
)
from tests.database.test_conversation_reviews_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_reviews_postgresql import (
    review_case as review_case,
)


async def _surfaces(
    database: AsyncSession, case: ReviewCase, assignment_id: UUID
) -> dict[str, Any]:
    app = ConversationApplication(database, clock=lambda: case.prepared.state.now)
    reports = ConversationReports(app)
    run_view = await reports.get(case.source_actor, case.report_run_id)
    recording_id = UUID(run_view["recording_id"])
    report = ReportDraft.model_validate(run_view["report"])
    envelope = project_bound_report(
        report,
        access=ReportAccess.ACCOUNT,
        source=ReportSourceBinding(
            recording_id, case.report_run_id, report.source_sha256, report.transcript_revision
        ),
    )
    return {
        "run_report": run_view,
        "run_report_docx": docx_text(report_docx_bytes(envelope)),
        "transcript": await reports.transcript(case.source_actor, recording_id),
        "checkpoints": await app.checkpoints(case.source_actor, recording_id),
        "admin_report": await AdminConversationReports(
            app,
            case.operations_tenant_id,
            recording_tenant_ids=(case.prepared.state.tenant_id,),
        ).get(case.admin_actor, case.report_run_id),
        "review_assignment": await _service(database, case).get(case.reviewer_actor, assignment_id),
    }


def _paths_of(payload: Any, text: str, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(payload, str):
        if payload == text:
            found.append(prefix)
    elif isinstance(payload, dict):
        for key, item in payload.items():
            found.extend(_paths_of(item, text, f"{prefix}.{key}"))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found.extend(_paths_of(item, text, f"{prefix}[{index}]"))
    return found


def _quotes_for(payload: Any, segment_id: str) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        if payload.get("segment_id") == segment_id and isinstance(payload.get("quote"), str):
            found.append(payload["quote"])
        for item in payload.values():
            found.extend(_quotes_for(item, segment_id))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_quotes_for(item, segment_id))
    return found


def test_marked_segment_is_withheld_on_every_surface_and_released_reads_are_identical(
    review_case: ReviewCase,
) -> None:
    case = review_case

    async def exercise() -> None:
        assignment_id = UUID((await _create_assignment(case, key="withheld-assignment"))["id"])
        async with case.sessions() as database, database.begin():
            before = await _surfaces(database, case, assignment_id)
            c2 = await database.get(ConversationCheckpoint, case.checkpoint_id)
            assert c2 is not None and isinstance(c2.payload, dict)
            marked_text = next(s["text"] for s in c2.payload["segments"] if s["id"] == case.span_id)
            revision = str(before["transcript"]["revision"])
        marked = grams(marked_text)
        baseline = canonical(before)
        assert markers(before) == 0
        assert any(s["id"] == case.span_id for s in before["transcript"]["segments"])

        async with case.sessions() as database, database.begin():
            (mark,) = await SensitiveSegmentsStore(database).mark(
                case.admin_actor,
                recording_id=case.prepared.recording_id,
                transcript_revision=revision,
                segments=[(case.span_id, "SENSITIVE_FINANCIAL")],
                reason_ref="AUT-521 test",
                idempotency_key="withheld-mark-1",
            )
            mark_id = mark.id
        async with case.sessions() as database, database.begin():
            guarded = await _surfaces(database, case, assignment_id)
        for name, payload in guarded.items():
            assert shared_grams(payload, marked) == 0, name
            leftover = _paths_of(payload, marked_text)
            # Rule C needs four tokens. The fixture's marked line is shorter, so the C2
            # payload's whole-transcript ``raw_text`` keeps it (checkpoints, reviewer); a
            # real marked segment of four or more words shares a 4-gram with ``raw_text``
            # and withholds it.
            if not marked:
                assert all(path.endswith("raw_text") for path in leftover), (name, leftover)
            else:
                assert leftover == [], name
        assert markers(guarded) >= 2
        for name in ("transcript",):
            texts = {s["id"]: s["text"] for s in guarded[name]["segments"]}
            assert texts[case.span_id] == WITHHELD_MARKER
        spans = {s["span_id"]: s["text"] for s in guarded["review_assignment"]["evidence_spans"]}
        assert spans[case.span_id] == WITHHELD_MARKER
        for name in ("run_report", "admin_report", "review_assignment"):
            quotes = _quotes_for(guarded[name]["report"], case.span_id)
            assert all(quote == WITHHELD_MARKER for quote in quotes), name
        assert [c["id"] for c in guarded["checkpoints"]] == [c["id"] for c in before["checkpoints"]]
        assert guarded["run_report"]["id"] == before["run_report"]["id"]

        async with case.sessions() as database, database.begin():
            await SensitiveSegmentsStore(database).release(
                case.admin_actor,
                mark_id=mark_id,
                reason_ref="AUT-521 test",
                idempotency_key="withheld-release-1",
            )
        async with case.sessions() as database, database.begin():
            released = await _surfaces(database, case, assignment_id)
        assert canonical(released) == baseline

    run(exercise())


@pytest.fixture
def generation_harness():
    # The review factory provisions one fixed admin address per disposable schema.
    yield from postgres_harness.__wrapped__()


@pytest.mark.parametrize("mode", ["hit", "no_hit", "error"])
def test_generation_is_atomic_with_publication_and_replay_respects_release(
    generation_harness,
    tmp_path,
    monkeypatch,
    mode,
):
    original_execute, original_finish = FakeBroker.execute, ReportingPipeline.finish
    captured = {}

    async def execute(self, reservation, payload):
        result = await original_execute(self, reservation, payload)
        if mode != "no_hit":
            data = {
                **result.data,
                "text": "cash only",
                "words": [
                    {**word, "text": text}
                    for word, text in zip(result.data["words"], ("cash", "only"), strict=True)
                ],
            }
            raw = canonical(data)
            result = replace(
                result, data=data, raw_json=raw, response_sha256=sha256(raw).hexdigest()
            )
        return result

    async def finish(self, recording, task, report_run, *args):
        captured.update(recording_id=recording.id, run_id=report_run.id, args=args)
        self.database.add(
            ConversationProcessingPrincipal(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                operator_reference="AUT-916 fictional",
                created_at=recording.created_at,
            )
        )
        await self.database.flush()
        await original_finish(self, recording, task, report_run, *args)
        # Another connection sees neither the report nor marks before the caller commits.
        async with AsyncSession(self.database.bind) as observer:
            for model in (ConversationReportDraft, ConversationSensitiveSegmentMark):
                assert (
                    await observer.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(
                            model.recording_id == recording.id,
                        )
                    )
                    == 0
                )

    monkeypatch.setattr(FakeBroker, "execute", execute)
    monkeypatch.setattr(ReportingPipeline, "finish", finish)
    if mode == "error":

        def broken(_segments):
            raise RuntimeError("fictional detector failure")

        monkeypatch.setattr(
            "ac_platform.conversation_intelligence.sensitive_segments_store.detect_sensitive_terms",
            broken,
        )

    async def exercise():
        if mode == "error":
            with pytest.raises(AssertionError):
                await _build_report_case(generation_harness, tmp_path)
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(generation_harness.url)
            try:
                async with AsyncSession(engine) as database:
                    report_run = await database.get(ConversationRun, captured["run_id"])
                    assert report_run.state == "failed" and report_run.completed_at is not None
                    for model in (ConversationReportDraft, ConversationSensitiveSegmentMark):
                        assert (
                            await database.scalar(
                                select(func.count())
                                .select_from(model)
                                .where(
                                    model.recording_id == captured["recording_id"],
                                )
                            )
                            == 0
                        )
            finally:
                await engine.dispose()
            return
        case = await _build_report_case(generation_harness, tmp_path)
        try:
            async with case.sessions() as database, database.begin():
                app = ConversationApplication(database, clock=lambda: case.prepared.state.now)
                before = await ConversationReports(app).get(case.source_actor, case.report_run_id)
                rows = (
                    await database.scalars(
                        select(ConversationSensitiveSegmentMark).where(
                            ConversationSensitiveSegmentMark.recording_id
                            == case.prepared.recording_id,
                        )
                    )
                ).all()
                assert len(rows) == (1 if mode == "hit" else 0)
                if mode == "no_hit":
                    assert markers(before) == 0
                if rows:
                    assert rows[0].source == "generation"
                    assert rows[0].reason_ref == "sensitive_terms_v1:cash_only"
                    assert _quotes_for(before["report"], case.span_id) == [WITHHELD_MARKER]
                    await SensitiveSegmentsStore(database).release(
                        case.admin_actor,
                        mark_id=rows[0].id,
                        reason_ref="AUT-916 fictional release",
                        idempotency_key="generation-release",
                    )
                released = await ConversationReports(app).get(case.source_actor, case.report_run_id)
                from ac_platform.conversation_intelligence.inference import ConversationInference

                pipeline = ReportingPipeline(ConversationInference(app))
                recording = await database.get(ConversationRecording, case.prepared.recording_id)
                task = await database.get(ConversationInferenceTask, case.report_run_id)
                report_run = await database.get(ConversationRun, case.report_run_id)
                await original_finish(pipeline, recording, task, report_run, *captured["args"])
                assert canonical(
                    await ConversationReports(app).get(case.source_actor, case.report_run_id)
                ) == canonical(released)
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(
                            ConversationReportDraft.run_id == case.report_run_id,
                        )
                    )
                    == 1
                )
                assert await database.scalar(
                    select(func.count())
                    .select_from(ConversationSensitiveSegmentMark)
                    .where(
                        ConversationSensitiveSegmentMark.recording_id == recording.id,
                    )
                ) == (2 if mode == "hit" else 0)
        finally:
            await case.engine.dispose()

    run(exercise())


def test_census_dry_run_apply_and_replay_commit_reference_only_marks(
    generation_harness,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AC_ENVIRONMENT", "test")

    def hits(segments):
        segment_id, _text = next(iter(segments))
        return ((segment_id, "SENSITIVE_FINANCIAL", "cash_only"),)

    async def exercise():
        case = await _build_report_case(generation_harness, tmp_path)
        monkeypatch.setattr(
            cli, "_database_url", lambda: case.engine.url.render_as_string(hide_password=False)
        )
        for module in (cli, store_module):
            monkeypatch.setattr(module, "detect_sensitive_terms", hits)
        async with case.sessions() as database, database.begin():
            database.add(
                ConversationProcessingPrincipal(
                    id=uuid4(),
                    tenant_id=case.prepared.state.tenant_id,
                    person_id=case.prepared.state.person_id,
                    operator_reference="AUT-916 fictional",
                    created_at=case.prepared.state.now,
                )
            )

        async def marks():
            async with case.sessions() as database:
                return (
                    await database.scalars(
                        select(ConversationSensitiveSegmentMark).where(
                            ConversationSensitiveSegmentMark.recording_id
                            == case.prepared.recording_id,
                        )
                    )
                ).all()

        args = cli.parser().parse_args(
            ["census", "--recording-id", str(case.prepared.recording_id)]
        )
        assert await cli.census(args) and await marks() == []
        args.apply, args.environment = True, "test"
        await cli.census(args)
        (first,) = await marks()
        assert first.source == "generation"
        assert first.reason_ref == "AUT-524 census sensitive_terms_v1:cash_only"
        await cli.census(args)
        assert [m.id for m in await marks()] == [first.id]
        await case.engine.dispose()

    run(exercise())
