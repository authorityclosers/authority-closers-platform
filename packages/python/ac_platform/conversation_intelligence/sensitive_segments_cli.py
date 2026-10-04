"""Reference-only receipts and legal-exposure census (AUT-519 §4, AUT-915).

``receipt`` renders every reader surface of one recording through the same
post-authorization functions the routes use, as the owner projection, inside a
transaction that is always rolled back. ``overlap`` checks a body fetched over
HTTP (JSON or ``.docx``). Both print JSON lines with counts and hashes only;
no segment text, quote or report prose is ever printed. ``census`` detects word
patterns in retained C2 transcripts; its optional request file contains API
paths and mark bodies for review. Dry run is the default; ``census --apply``
appends generation marks in one transaction per recording.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import io
import json
import os
import sys
import zipfile
from collections import Counter
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.asyncio_runtime import run_async
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.admin_reports import AdminConversationReports
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
    ConversationReportDraft,
    ConversationReviewAssignment,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
)
from ac_platform.conversation_intelligence.report_export import report_docx_bytes
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.conversation_intelligence.sensitive_segments import (
    WITHHELD_MARKER,
    Gram,
    at_path,
    markers,
    shared_grams,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import (
    SensitiveSegmentsStore,
    _effective_statement,
    marks_in_force,
    withheld_plan_for,
)
from ac_platform.conversation_intelligence.sensitive_terms import VERSION, detect_sensitive_terms
from ac_platform.kernel.authz import ActorContext

_WORD_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


class CommandError(RuntimeError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:
        raise CommandError(message)


def parser() -> argparse.ArgumentParser:
    root = _Parser(prog="sensitive-segments", description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    receipt = commands.add_parser("receipt", help="render every surface; print counts and hashes")
    receipt.add_argument("--recording-id", type=UUID, required=True)
    receipt.add_argument(
        "--path", action="append", default=[], help="e.g. dimensions[1].evidence[1]"
    )
    overlap = commands.add_parser("overlap", help="count shared 4-grams in a fetched body")
    overlap.add_argument("--recording-id", type=UUID, required=True)
    overlap.add_argument("--file", required=True)
    census = commands.add_parser("census", help="candidate IDs and report citation counts")
    census.add_argument("--recording-id", type=UUID, action="append", default=[])
    census.add_argument("--requests-out", type=Path)
    census.add_argument("--apply", action="store_true")
    census.add_argument(
        "--environment", choices=("local", "test", "development", "staging", "production")
    )
    census.add_argument("--allow-production", action="store_true")
    return root


def docx_text(document: bytes) -> str:
    """Join the text runs of a ``.docx`` body; nothing else in the archive carries prose."""

    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        # The body comes from this service's own report export, never from a third party.
        tree = ET.fromstring(archive.read("word/document.xml"))  # noqa: S314
    return "\n".join(node.text or "" for node in tree.iter(_WORD_TEXT))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _database_url() -> str:
    url = os.getenv("AC_DATABASE_URL", "").strip()
    if not url:
        raise CommandError("An explicit AC_DATABASE_URL is required.")
    return url


async def _marked_grams(database: AsyncSession, recording_id: UUID) -> frozenset[Gram]:
    """Grams of every effective mark's text, read from the C2 checkpoints in-process."""

    return (await withheld_plan_for(database, recording_id=recording_id)).grams


async def render_surfaces(
    database: AsyncSession, recording_id: UUID, paths: list[str]
) -> list[dict[str, Any]]:
    """Every §2 surface as the owner sees it; returns receipt lines, never payloads."""

    recording = await database.scalar(
        select(ConversationRecording).where(ConversationRecording.id == recording_id)
    )
    if recording is None:
        raise CommandError("Recording not found.")
    if not await marks_in_force(database, recording_id=recording.id):
        raise CommandError("Recording has no in-force marks.")
    marked = await _marked_grams(database, recording.id)
    app = ConversationApplication(database)
    owner = ActorContext(recording.person_id, uuid4(), recording.tenant_id)
    now = datetime.now(UTC)
    acquisition = AcquisitionReports(
        GuestOwnership(
            AcquisitionSessions(database, tenant_id=recording.tenant_id, policy_revision="receipt")
        )
    )
    reports = ConversationReports(app)
    review = ConversationReviewService(app, operations_tenant_id=recording.tenant_id)
    runs = (
        await database.scalars(
            select(ConversationRun)
            .where(ConversationRun.recording_id == recording.id)
            .order_by(ConversationRun.created_at.desc(), ConversationRun.id.desc())
        )
    ).all()
    assignments = (
        await database.scalars(
            select(ConversationReviewAssignment).where(
                ConversationReviewAssignment.recording_id == recording.id
            )
        )
    ).all()

    async def run_report(run: ConversationRun) -> dict[str, Any]:
        return await reports.render_report(await app._run_view(owner, run.id), recording)

    async def run_docx(run: ConversationRun) -> bytes:
        payload = await run_report(run)
        report = ReportDraft.model_validate(payload["report"])
        envelope = project_bound_report(
            report,
            access=ReportAccess.ACCOUNT,
            source=ReportSourceBinding(
                recording.id, run.id, report.source_sha256, report.transcript_revision
            ),
        )
        return report_docx_bytes(envelope)

    async def admin_report(run: ConversationRun) -> Any:
        recovered = await RetainedC5RecoveryService(app).render_admin_report(run.id)
        if recovered is not None:
            return recovered
        return await AdminConversationReports(app, recording.tenant_id).render(
            review, owner, run.id, now
        )

    async def assignment(row: ConversationReviewAssignment) -> dict[str, Any]:
        view = await review._view(row, now)
        evidence = await review._evidence(row.run_id, now, report_id=row.report_id)
        return await review.render(view, evidence)

    async def acquisition_docx() -> bytes:
        return report_docx_bytes(
            await acquisition.render_report(
                recording, submission_id=recording.id, access=ReportAccess.ACCOUNT
            )
        )

    surfaces: list[tuple[str, Callable[[], Coroutine[Any, Any, Any]]]] = [
        (
            "acquisition_report",
            lambda: acquisition.render_report(
                recording, submission_id=recording.id, access=ReportAccess.ACCOUNT
            ),
        ),
        ("acquisition_report_docx", acquisition_docx),
        ("acquisition_transcript", lambda: acquisition.render_transcript(recording)),
        ("recording_transcript", lambda: reports.render_transcript(recording)),
        (
            "checkpoints",
            lambda: app.render_checkpoints(
                recording.id, tenant_id=recording.tenant_id, person_id=recording.person_id
            ),
        ),
    ]
    for run in runs:
        surfaces.append((f"run_report:{run.id}", functools.partial(run_report, run)))
        surfaces.append((f"run_report_docx:{run.id}", functools.partial(run_docx, run)))
        surfaces.append((f"admin_report:{run.id}", functools.partial(admin_report, run)))
    for row in assignments:
        surfaces.append((f"review_assignment:{row.id}", functools.partial(assignment, row)))

    lines: list[dict[str, Any]] = []
    rendered: dict[str, Any] = {}
    for name, render in surfaces:
        try:
            payload = await render()
        except (ConversationError, ValueError, KeyError, TypeError) as error:
            lines.append({"surface": name, "error": type(error).__name__})
            continue
        if isinstance(payload, bytes):
            text = docx_text(payload)
            digest, body = _sha256(payload), text
        else:
            encoded = canonical(payload)
            digest, body = _sha256(encoded), payload
        rendered[name] = payload
        lines.append(
            {
                "surface": name,
                "sha256": digest,
                "shared_4grams": shared_grams(body, marked),
                "markers": markers(body),
            }
        )
    report = rendered.get("acquisition_report")
    content = report.get("report", {}).get("content") if isinstance(report, dict) else None
    for path in paths:
        item = at_path(content, path) if content is not None else None
        lines.append(
            {
                "path": path,
                "segment_id": item.get("segment_id") if isinstance(item, dict) else None,
                "quote_is_marker": isinstance(item, dict) and item.get("quote") == WITHHELD_MARKER,
            }
        )
    return lines


async def receipt(args: argparse.Namespace) -> list[dict[str, Any]]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin() as transaction:
            try:
                return await render_surfaces(database, args.recording_id, list(args.path))
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def overlap_line(body: bytes, marked: frozenset[Gram]) -> dict[str, Any]:
    """Shared 4-grams between a fetched body (JSON, text or ``.docx``) and the marked text."""

    if zipfile.is_zipfile(io.BytesIO(body)):
        payload: Any = docx_text(body)
    else:
        try:
            payload = json.loads(body)
        except ValueError:
            payload = body.decode("utf-8", errors="replace")
    return {"file_sha256": _sha256(body), "shared_4grams": shared_grams(payload, marked)}


async def overlap(args: argparse.Namespace, body: bytes) -> list[dict[str, Any]]:
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as database, database.begin() as transaction:
            try:
                marked = await _marked_grams(database, args.recording_id)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
    return [overlap_line(body, marked)]


def _citations(value: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(value, dict):
        if isinstance(value.get("segment_id"), str):
            counts[value["segment_id"]] += 1
        for child in value.values():
            counts.update(_citations(child))
    elif isinstance(value, list):
        for child in value:
            counts.update(_citations(child))
    return counts


async def census_lines(database: AsyncSession, recording_ids: list[UUID]) -> list[dict[str, Any]]:
    """Three SELECTs; raw C2/report payloads stay in-process, never in output."""
    c2 = (
        select(ConversationCheckpoint)
        .where(ConversationCheckpoint.stage == "C2", ConversationCheckpoint.erased_at.is_(None))
        .order_by(ConversationCheckpoint.created_at, ConversationCheckpoint.id)
    )
    reports = (
        select(ConversationReportDraft)
        .where(ConversationReportDraft.erased_at.is_(None))
        .order_by(ConversationReportDraft.created_at, ConversationReportDraft.id)
    )
    if recording_ids:
        c2 = c2.where(ConversationCheckpoint.recording_id.in_(recording_ids))
        reports = reports.where(ConversationReportDraft.recording_id.in_(recording_ids))
    revisions = {}
    for checkpoint in await database.scalars(c2):
        payload = checkpoint.payload or {}
        if isinstance(payload.get("revision"), str) and isinstance(payload.get("segments"), list):
            revisions[checkpoint.recording_id, payload["revision"]] = payload["segments"]
    citations: dict[tuple[UUID, str], dict[str, Counter[str]]] = {}
    for report in await database.scalars(reports):
        revision = (report.transcript or {}).get("revision")
        if isinstance(revision, str) and report.payload is not None:
            runs = citations.setdefault((report.recording_id, revision), {})
            runs.setdefault(str(report.run_id), Counter()).update(_citations(report.payload))
    marked = {
        (m.recording_id, m.transcript_revision, m.segment_id)
        for m in await database.scalars(_effective_statement())
    }
    lines = []
    for (recording_id, revision), segments in revisions.items():
        hits = detect_sensitive_terms(
            (s["id"], s["text"])
            for s in segments
            if isinstance(s, dict)
            and isinstance(s.get("id"), str)
            and isinstance(s.get("text"), str)
        )
        runs = citations.get((recording_id, revision), {})
        bound_runs: list[tuple[str | None, Counter[str]]] = list(runs.items()) or [
            (None, Counter())
        ]
        for segment_id, category, rule_id in hits:
            for run_id, counts in bound_runs:
                lines.append(
                    {
                        "recording_id": str(recording_id),
                        "transcript_revision": revision,
                        "run_id": run_id,
                        "segment_id": segment_id,
                        "category": category,
                        "rule_id": rule_id,
                        "cited_in_report": counts[segment_id],
                        "already_marked": (recording_id, revision, segment_id) in marked,
                    }
                )
    return lines


async def census(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.apply:
        configured = os.getenv("AC_ENVIRONMENT", "").strip().lower()
        if not args.environment or args.environment != configured:
            raise CommandError("The explicit environment must match AC_ENVIRONMENT.")
        if configured == "production" and not args.allow_production:
            raise CommandError("Production requires --allow-production.")
    engine = create_async_engine(_database_url(), pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with sessions() as database, database.begin() as transaction:
            try:
                lines = await census_lines(database, args.recording_id)
            finally:
                await transaction.rollback()
        if args.apply:
            revisions: dict[UUID, set[str]] = {}
            for line in lines:
                revisions.setdefault(UUID(line["recording_id"]), set()).add(
                    line["transcript_revision"]
                )
            for recording_id, held in revisions.items():
                async with sessions() as database, database.begin():
                    store = SensitiveSegmentsStore(database)
                    for revision in sorted(held):
                        await store.mark_generation(
                            recording_id=recording_id,
                            transcript_revision=revision,
                            reason_prefix="AUT-524 census ",
                        )
        return lines
    finally:
        await engine.dispose()


def mark_requests(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests = {}
    for line in lines:
        if line["already_marked"]:
            continue
        key = (
            line["recording_id"],
            line["transcript_revision"],
            line["segment_id"],
            line["rule_id"],
        )
        requests[key] = {
            "path": f"/v1/platform/sensitive-segments/recordings/{line['recording_id']}/marks",
            "body": {
                "transcript_revision": line["transcript_revision"],
                "segments": [{"segment_id": line["segment_id"], "category": line["category"]}],
                "reason_ref": f"AUT-524 census {VERSION}:{line['rule_id']}",
            },
        }
    return list(requests.values())


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command == "receipt":
            lines = run_async(receipt(args))
        elif args.command == "census":
            lines = run_async(census(args))
            if args.requests_out:
                args.requests_out.write_text(
                    "".join(json.dumps(r, sort_keys=True) + "\n" for r in mark_requests(lines)),
                    encoding="utf-8",
                )
        else:
            lines = run_async(overlap(args, Path(args.file).read_bytes()))
    except CommandError as exc:
        print(f"Sensitive-segment receipt refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Database errors may carry credentials; segment text must never reach a terminal.
        print("Sensitive-segment receipt refused; check the database state.", file=sys.stderr)
        return 2
    for line in lines:
        print(json.dumps(line, sort_keys=True))
    if args.command == "receipt" and any(
        "path" in line and not line["quote_is_marker"] for line in lines
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
