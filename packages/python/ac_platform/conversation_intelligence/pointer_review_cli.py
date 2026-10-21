"""Operator runner: AI pointer reviews for a workspace's latest saved reports.

Owner decision 16 Oct 2026 (rulebook 693645b0): test the Report's AI scores by
reviewing the owner's last 5 dev calls. Dry run by default; ``--apply`` makes
one Gemini call per report and saves the validated review (append-only).

Every paid call is admitted first (AUT-2010, ``pointer_review_admission``):
one runner per database, the call's consent, erasure and source checked
before the call and again before saving, and each attempt recorded in the
workspace's append-only audit chain, so timeouts, unreadable answers and
crashes count against the daily cap and the two-attempt limit.

Our own test calls are never scored (owner, 17 Oct cost step 1): the canary
and the QA smoke accounts upload the bundled canary fixture, and paying
Gemini to score that same 44-second file cost more than any customer call.

The outer process reads the worker's service config, then re-runs itself
inside ``infisical run`` so the Gemini key exists only in the child's
environment. Nothing here prints transcript text, prompts or credentials.

    python -m ac_platform.conversation_intelligence.pointer_review_cli \\
        --service-config /etc/authority-closers/development/service-live.json \\
        --database-url-file /etc/authority-closers/development/database-url-live \\
        --tenant <workspace tenant id> --limit 5 [--apply] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

INNER = "--inner"
AUTOMATIC = "automatic:pointer-review"
OPERATOR = "operator:report-ui-20261016"
_PROVIDER = "gemini"
# Automatic mode reads this many newest candidates and admits up to --limit.
_CANDIDATES = 50


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pointer_review_cli")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--tenant", type=UUID, help="one workspace's latest reports")
    target.add_argument(
        "--erase-erased-calls",
        action="store_true",
        help="one-off cleanup: empty reviews of already erased calls (dry run without --apply)",
    )
    target.add_argument(
        "--recent-hours",
        type=int,
        help="automatic mode: unreviewed reports from the last N hours, every workspace",
    )
    parser.add_argument(
        "--not-before",
        type=datetime.fromisoformat,
        help="automatic mode: only reports finished after this moment (new calls only)",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--unscored-only",
        action="store_true",
        help="workspace mode: the newest reports that have no saved review yet",
    )
    parser.add_argument(
        "--daily-cap",
        type=int,
        default=200,
        help="stop once this many paid attempts of this mode ran in 24 hours",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="accepted for older wrappers; attempts now live in the audit ledger",
    )
    parser.add_argument(
        "--force", action="store_true", help="operator mode: review again even if saved"
    )
    # Outside the worker's mount namespace the identity token and Infisical
    # live at their host paths (the worker bind-mounts them read-only).
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.limit <= 50:
        parser.error("--limit must be 1-50")
    if arguments.recent_hours is not None and not 1 <= arguments.recent_hours <= 168:
        parser.error("--recent-hours must be 1-168")
    if arguments.recent_hours is not None and arguments.not_before is None:
        parser.error("--recent-hours needs --not-before: automatic mode never backfills")
    if arguments.not_before is not None and arguments.not_before.tzinfo is None:
        parser.error("--not-before needs a time zone, e.g. 2026-10-16T00:00:00+00:00")
    if arguments.unscored_only and arguments.tenant is None:
        parser.error("--unscored-only is for one workspace (--tenant)")
    if arguments.recent_hours is not None and arguments.force:
        parser.error("--force is for one workspace's reports, never automatic mode")
    if not 1 <= arguments.daily_cap <= 500:
        parser.error("--daily-cap must be 1-500")
    return arguments


def _gemini_provider(config: Path) -> dict[str, Any]:
    service = json.loads(config.read_text())
    for provider in service.get("providers") or []:
        if provider.get("provider_id") == _PROVIDER:
            return dict(provider)
    raise SystemExit("pointer_review_provider_missing")


def _reexec_inside_infisical(argv: list[str], arguments: argparse.Namespace) -> None:
    provider = _gemini_provider(arguments.service_config)
    token_file = arguments.token_file or Path(provider["token_file_ref"])
    token = token_file.read_text().strip()
    if token.startswith("INFISICAL_TOKEN="):
        token = token[len("INFISICAL_TOKEN=") :]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONUNBUFFERED"}
    }
    environment["INFISICAL_TOKEN"] = token
    command = [
        str(arguments.infisical or provider["executable"]),
        "run",
        "--include-imports=false",
        "--expand=false",
        "--silent",
        "--telemetry=false",
        "--log-level=error",
        "--projectId",
        str(provider["project_ref"]),
        "--env",
        str(provider["environment_ref"]),
        "--path",
        str(provider["secret_path_ref"]),
        "--",
        sys.executable,
        "-m",
        "ac_platform.conversation_intelligence.pointer_review_cli",
        *argv,
        INNER,
    ]
    os.execvpe(command[0], command, environment)  # noqa: S606 - fixed argv, no shell


def _latest_reports(
    connection: Any, tenant: UUID, limit: int, *, unscored_only: bool = False
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows = connection.execute(
        text(
            """
            SELECT s.submission_id, d.id AS draft_id, d.tenant_id, d.recording_id, d.run_id,
                   d.source_sha256, d.payload ->> 'transcript_revision' AS transcript_revision
            FROM conversation_guest_submissions s
            JOIN LATERAL (
                SELECT * FROM conversation_report_drafts d
                WHERE d.recording_id = s.recording_id AND d.erased_at IS NULL
                ORDER BY d.created_at DESC LIMIT 1
            ) d ON TRUE
            WHERE s.tenant_id = :tenant
              -- Scored: any unerased review of this exact run, source and revision.
              AND (
                NOT :unscored_only OR NOT EXISTS (
                  SELECT 1 FROM conversation_pointer_reviews r
                  WHERE r.run_id = d.run_id AND r.source_sha256 = d.source_sha256
                    AND r.transcript_revision = d.payload ->> 'transcript_revision'
                    AND r.erased_at IS NULL
                )
              )
            ORDER BY s.created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant": tenant, "limit": limit, "unscored_only": unscored_only},
    ).mappings()
    return [dict(row) for row in rows]


def _recent_unreviewed(
    connection: Any, hours: int, not_before: datetime, limit: int
) -> list[dict[str, Any]]:
    from sqlalchemy import text

    rows = connection.execute(
        text(
            """
            SELECT s.submission_id, d.id AS draft_id, d.tenant_id, d.recording_id, d.run_id,
                   d.source_sha256, d.payload ->> 'transcript_revision' AS transcript_revision
            FROM conversation_report_drafts d
            JOIN conversation_guest_submissions s ON s.recording_id = d.recording_id
            WHERE d.erased_at IS NULL
              AND d.created_at > now() - make_interval(hours => :hours)
              AND d.created_at > :not_before
              AND NOT EXISTS (
                SELECT 1 FROM conversation_pointer_reviews r
                WHERE r.run_id = d.run_id AND r.source_sha256 = d.source_sha256
                  AND r.transcript_revision = d.payload ->> 'transcript_revision'
              )
              AND d.created_at = (
                SELECT max(n.created_at) FROM conversation_report_drafts n
                WHERE n.recording_id = d.recording_id AND n.erased_at IS NULL
              )
            ORDER BY d.created_at DESC
            LIMIT :limit
            """
        ),
        {"hours": hours, "not_before": not_before, "limit": limit},
    ).mappings()
    return [dict(row) for row in rows]


def _test_source_shas(connection: Any) -> set[str]:
    """Sources that are our own test calls: every bundled canary fixture and any
    fixture a canary ever submitted. Matching the source covers the canary and
    the QA smoke accounts, which upload the same file."""
    import hashlib
    from importlib import resources

    from sqlalchemy import text

    shas = {
        str(sha)
        for sha in connection.execute(
            text("SELECT DISTINCT fixture_sha256 FROM conversation_canary_submissions")
        ).scalars()
    }
    fixtures = resources.files("ac_platform.conversation_intelligence") / "canary_fixture"
    for item in fixtures.iterdir():
        if item.name.endswith(".wav"):
            shas.add(hashlib.sha256(item.read_bytes()).hexdigest())
    return shas


def _segments(connection: Any, draft_id: UUID) -> list[dict[str, Any]]:
    from sqlalchemy import text

    value = connection.execute(
        text(
            "SELECT transcript -> 'normalized' -> 'segments' FROM conversation_report_drafts"
            " WHERE id = :id AND erased_at IS NULL"
        ),
        {"id": draft_id},
    ).scalar()
    return list(value) if isinstance(value, list) else []


def _withheld(connection: Any, recording_id: UUID, revision: str) -> set[str]:
    from sqlalchemy import text

    rows = connection.execute(
        text(
            """
            SELECT DISTINCT ON (segment_id) segment_id, action
            FROM conversation_sensitive_segment_marks
            WHERE recording_id = :recording AND transcript_revision = :revision
            ORDER BY segment_id, created_at DESC
            """
        ),
        {"recording": recording_id, "revision": revision},
    ).mappings()
    return {str(row["segment_id"]) for row in rows if row["action"] == "mark"}


def _one_pass_waiting(connection: Any, environment: str, reports: list[dict[str, Any]]) -> set[Any]:
    """Recordings whose review one pass is about to publish (one_pass.publish)."""
    from ac_platform.one_pass import publish

    handoff = publish.handoff(connection, environment)
    if handoff is None:
        return set()
    now = datetime.now(UTC)
    return {
        report["recording_id"]
        for report in reports
        if report["transcript_revision"]
        and handoff.waits(
            connection,
            report["recording_id"],
            str(report["transcript_revision"]),
            kind="review",
            now=now,
        )
    }


class _ProviderFailure(RuntimeError):
    def __init__(self, outcome: str, usage: dict[str, Any] | None = None) -> None:
        super().__init__(outcome)
        self.outcome, self.usage = outcome, usage


def _call_gemini(body: dict[str, Any], *, flex: bool = False) -> dict[str, Any]:
    """One review request. On Flex (when the active provider configuration runs on Gemini
    Flex, gemini_tiers) it asks for Flex for up to five minutes, then once on standard."""
    import httpx

    from ac_platform.conversation_intelligence import gemini_tiers
    from ac_platform.conversation_intelligence.pointer_review import MODEL_ID

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("pointer_review_credential_missing")

    def post(payload: dict[str, Any], seconds: float) -> Any:
        try:
            return httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent",
                headers={"x-goog-api-key": key, "content-type": "application/json"},
                json=payload,
                timeout=httpx.Timeout(seconds, connect=20.0),
            )
        except httpx.TimeoutException:
            raise _ProviderFailure("timeout") from None
        except httpx.HTTPError:
            raise _ProviderFailure("transport_error") from None

    response = None
    if flex:
        try:
            response = post(
                {**body, "service_tier": "flex"}, float(gemini_tiers.FLEX_WINDOW_SECONDS)
            )
        except _ProviderFailure:
            response = None
        if response is not None and response.status_code in gemini_tiers.FLEX_RETRY_STATUSES:
            response = None
    if response is None:
        response = post(body, 240.0)
    if response.status_code != 200:
        raise _ProviderFailure(f"provider_http_{response.status_code}")
    try:
        return dict(response.json())
    except ValueError:
        raise _ProviderFailure("unreadable_response") from None


def _active_flex(connection: Any) -> bool:
    """Whether the newest provider activation runs any route on Gemini Flex."""
    from sqlalchemy import text

    configuration = connection.execute(
        text(
            """
            SELECT c.configuration FROM conversation_provider_activations a
            JOIN conversation_provider_configurations c ON c.id = a.configuration_id
            ORDER BY a.created_at DESC LIMIT 1
            """
        )
    ).scalar()
    routes = configuration.get("routes") if isinstance(configuration, dict) else None
    return any(
        isinstance(route, dict) and str(route.get("model_id") or "").endswith(":flex")
        for route in routes or []
    )


def _est_paise(usage: dict[str, Any]) -> int:
    # Operator log only, never a charge: Gemini 3.8 Flash list price
    # (admin_pricing) $0.75 in, $3.75 out per M tokens; Rs 100/$.
    return round(
        (
            int(usage.get("promptTokenCount") or 0) * 0.75
            + int(usage.get("candidatesTokenCount") or 0) * 3.75
        )
        * 100
        * 100
        / 1_000_000
    )


async def _publish_one_pass(
    sessions: Any,
    report: dict[str, Any],
    arguments: argparse.Namespace,
    storage_root: Path,
    *,
    saved: list[dict[str, Any]],
    withheld: set[str],
) -> dict[str, Any] | None:
    """A report whose plan ran C4 as the one-pass request: its review and deep call data
    come from that read (one_pass.plan_publish), with no provider call. None when the
    report's C4 was today's fact chunks or its answer can't be read."""
    from sqlalchemy import text

    from ac_platform.one_pass import plan_publish

    async with sessions() as session:
        read = await session.run_sync(lambda sync: plan_publish.c4_read(sync.connection(), report))
    if read is None:
        return None
    found = plan_publish.answer(storage_root, read)
    if found is None:
        return {"one_pass": str(read.run_id), "review": "unusable:answer_unreadable"}
    if not arguments.apply:
        return {"one_pass": str(read.run_id), "dry_run": True}
    segments = [segment for segment in saved if str(segment.get("id")) not in withheld]
    async with sessions() as session, session.begin():
        # The pointer review's own per-call lock: one saver at a time.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"ac.pointer_review:{report['recording_id']}"},
        )
        return dict(
            await session.run_sync(
                lambda sync: plan_publish.publish(
                    sync.connection(),
                    report=report,
                    read=read,
                    answer=found,
                    segments=segments,
                    withheld=withheld,
                    storage_root=storage_root,
                )
            )
        )


async def _review_one(
    sessions: Any,
    report: dict[str, Any],
    arguments: argparse.Namespace,
    *,
    mode: str,
    created_by: str,
    call_provider: Any = None,
) -> dict[str, Any]:
    """Admit, call the provider once, then save or record why not (AUT-2010)."""
    from ac_platform.conversation_intelligence import pointer_review_admission as admission
    from ac_platform.conversation_intelligence.pointer_review import (
        PointerReviewError,
        admission_refusal,
        build_prompt,
        decode_gemini,
        gemini_body,
        parse_review,
        prompt_sha256,
    )

    line: dict[str, Any] = {"submission": str(report["submission_id"])}
    async with sessions() as session:
        saved = await session.run_sync(
            lambda sync: _segments(sync.connection(), report["draft_id"])
        )
        withheld = await session.run_sync(
            lambda sync: _withheld(
                sync.connection(), report["recording_id"], report["transcript_revision"]
            )
        )
    segments = [segment for segment in saved if str(segment.get("id")) not in withheld]
    line["segments"] = len(segments)
    storage_root = getattr(arguments, "storage_root", None)
    if storage_root is not None:
        published = await _publish_one_pass(
            sessions, report, arguments, storage_root, saved=saved, withheld=withheld
        )
        if published is not None:
            line.update(published)
            # Only a review part that can't be used is left to today's review below.
            if not str(published.get("review", "")).startswith("unusable"):
                return line
    try:
        system, user = build_prompt(segments, {})
    except PointerReviewError as error:
        line["error"] = str(error)
        return line
    digest = prompt_sha256(system, user)
    if not arguments.apply:
        async with sessions() as session, session.begin():
            refusal = await session.run_sync(
                lambda sync: admission_refusal(sync.connection(), report, datetime.now(UTC))
            )
        line["dry_run"] = True
        line["prompt_chars"] = len(system) + len(user)
        if refusal is not None:
            line["would_refuse"] = refusal
        return line
    async with sessions() as session, session.begin():
        claimed = await admission.claim(
            session,
            report,
            mode=mode,
            created_by=created_by,
            forced=arguments.force,
            prompt_digest=digest,
            daily_cap=arguments.daily_cap,
            now=datetime.now(UTC),
        )
    if claimed.attempt is None:
        line["skipped"] = claimed.refused
        return line
    # The start is committed: from here on this attempt counts as paid.
    line["attempt"] = str(claimed.attempt)
    usage: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    outcome = "runner_error"
    try:
        body = gemini_body(system, user)
        response = (
            call_provider(body)
            if call_provider is not None
            else _call_gemini(body, flex=bool(getattr(arguments, "flex", False)))
        )
        usage = dict(response.get("usageMetadata") or {})
        try:
            review = parse_review(decode_gemini(response), segments)
        except PointerReviewError:
            raise _ProviderFailure("parse_failed", usage) from None
        async with sessions() as session, session.begin():
            outcome = await admission.save(
                session,
                report,
                claimed.attempt,
                mode=mode,
                review=review,
                prompt_digest=digest,
                usage=usage,
                created_by=created_by,
                now=datetime.now(UTC),
            )
    except _ProviderFailure as failure:
        outcome, usage = failure.outcome, failure.usage or usage
    finally:
        if outcome != "saved" and not outcome.startswith("refused_"):
            # A provider or runner failure. If this write fails too, the start
            # without an outcome stays an uncertain attempt, counted as spent.
            async with sessions() as session, session.begin():
                await admission.finish(
                    session,
                    report,
                    claimed.attempt,
                    mode=mode,
                    outcome=outcome,
                    usage=usage,
                    now=datetime.now(UTC),
                )
    line["outcome"] = outcome
    if usage:
        line["tokens"] = [usage.get("promptTokenCount"), usage.get("candidatesTokenCount")]
        line["est_paise"] = _est_paise(usage)
    if outcome == "saved" and review is not None:
        line["overall"] = review["overall"]["score"]
        line["scored"] = review["overall"]["scored_pointers"]
        line["statuses"] = {
            status: sum(1 for p in review["pointers"] if p["status"] == status)
            for status in {p["status"] for p in review["pointers"]}
        }
    return line


async def _inner_async(
    arguments: argparse.Namespace,
    call_provider: Any = None,
    *,
    spend_environment: str | None = None,
) -> int:
    """``spend_environment`` turns the AI spend guard on (owner, 20 Oct 2026): the real
    runner always passes it; tests with a fake provider may leave it out. Operator runs
    for a workspace are bulk re-scores, so they need the backfill cap."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.conversation_intelligence import pointer_review_admission as admission
    from ac_platform.conversation_intelligence.pointer_review import (
        erase_reviews_of_erased_calls,
    )

    if (
        arguments.apply
        and not arguments.erase_erased_calls
        and call_provider is None
        and not os.environ.get("GEMINI_API_KEY")
    ):
        # Checked before any claim, so a missing key never records an attempt.
        raise SystemExit("pointer_review_credential_missing")
    url = arguments.database_url_file.read_text().strip()
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    failures = 0
    try:
        if arguments.erase_erased_calls:
            async with engine.begin() as connection:
                result = await connection.run_sync(
                    lambda sync: erase_reviews_of_erased_calls(sync, apply=arguments.apply)
                )
            print(json.dumps({"erase_erased_calls": result, "apply": arguments.apply}))
            return 0
        automatic = arguments.recent_hours is not None
        mode, created_by = ("automatic", AUTOMATIC) if automatic else ("operator", OPERATOR)
        async with engine.connect() as lock:
            # One runner per database, whichever entrypoint started it.
            if arguments.apply and not await admission.try_run_lock(lock):
                print(json.dumps({"reports": 0, "stopped": "another_runner"}))
                return 0
            try:
                async with sessions() as session:
                    if automatic:
                        reports = await session.run_sync(
                            lambda sync: _recent_unreviewed(
                                sync.connection(),
                                arguments.recent_hours,
                                arguments.not_before,
                                _CANDIDATES,
                            )
                        )
                    else:
                        reports = await session.run_sync(
                            lambda sync: _latest_reports(
                                sync.connection(),
                                arguments.tenant,
                                arguments.limit,
                                unscored_only=arguments.unscored_only,
                            )
                        )
                    test_sources = await session.run_sync(
                        lambda sync: _test_source_shas(sync.connection())
                    )
                    # The owner's Flex switch (the active provider configuration) covers
                    # this background review too.
                    arguments.flex = await session.run_sync(
                        lambda sync: _active_flex(sync.connection())
                    )
                    skipped_tenants = (
                        await session.run_sync(
                            lambda sync: spend_guard.skipped_tenants(
                                sync.connection(), spend_environment
                            )
                        )
                        if spend_environment is not None
                        else set()
                    )
                found = len(reports)
                reports = [r for r in reports if r["source_sha256"] not in test_sources]
                print(json.dumps({"reports": len(reports), "apply": arguments.apply}))
                if found > len(reports):
                    print(json.dumps({"test_reports_skipped": found - len(reports)}))
                sandbox = [r for r in reports if r["tenant_id"] in skipped_tenants]
                if sandbox:
                    reports = [r for r in reports if r["tenant_id"] not in skipped_tenants]
                    print(json.dumps({"sandbox_reports_skipped": len(sandbox)}))
                if automatic and reports and spend_environment is not None:
                    # When the environment publishes one-pass results, a report is left
                    # to one pass only while it works on that call (Handoff).
                    async with sessions() as session:
                        waiting = await session.run_sync(
                            lambda sync: _one_pass_waiting(
                                sync.connection(), spend_environment, reports
                            )
                        )
                    if waiting:
                        reports = [r for r in reports if r["recording_id"] not in waiting]
                        print(json.dumps({"left_to_one_pass": len(waiting)}))
                dispatched = 0
                for report in reports:
                    if dispatched >= arguments.limit:
                        break
                    if spend_environment is not None and arguments.apply:
                        async with sessions() as session:
                            refusal = await spend_guard.check_async(
                                session,
                                "pointer_review",
                                environment=spend_environment,
                                trigger="auto" if automatic else "backfill",
                            )
                        if refusal is not None:
                            print(json.dumps(refusal.line()))
                            break
                    line = await _review_one(
                        sessions,
                        report,
                        arguments,
                        mode=mode,
                        created_by=created_by,
                        call_provider=call_provider,
                    )
                    print(json.dumps(line))
                    dispatched += "attempt" in line
                    outcome = str(line.get("outcome") or "saved")
                    failures += "error" in line or not (
                        outcome == "saved" or outcome.startswith("refused_")
                    )
                    if line.get("skipped") == "daily_cap":
                        break
                # Brain 4.0's shadow reads only in a pass that reviewed nothing, so they
                # never hold up a new call's review.
                if (
                    automatic
                    and arguments.apply
                    and spend_environment is not None
                    and not dispatched
                ):
                    await _brain4_shadow(
                        sessions,
                        spend_environment,
                        call_provider=call_provider,
                        flex=bool(getattr(arguments, "flex", False)),
                        test_sources=test_sources,
                        skipped_tenants=skipped_tenants,
                    )
            finally:
                if arguments.apply:
                    await admission.release_run_lock(lock)
    finally:
        await engine.dispose()
    return 1 if failures else 0


async def _brain4_shadow(sessions: Any, environment: str, **options: Any) -> None:
    """Brain 4.0's shadow reads (brain4_shadow): a beta beside this job, behind its own
    spend guard feature (₹0 until raised). Its failures never fail the pointer review."""
    from ac_platform.conversation_intelligence import brain4_shadow

    try:
        lines = await brain4_shadow.run(sessions, environment=environment, **options)
    except Exception as error:  # noqa: BLE001 - a beta must not stop the review job
        lines = [{"brain4_shadow": "error", "type": type(error).__name__}]
    for line in lines:
        print(json.dumps(line))


def _inner(arguments: argparse.Namespace) -> int:
    import asyncio

    from ac_platform.ai_spend import guard as spend_guard
    from ac_platform.ai_spend.policy import SettingsError

    service = json.loads(arguments.service_config.read_text())
    try:
        spend_environment = spend_guard.service_environment(service)
    except SettingsError:
        raise SystemExit("pointer_review_environment_missing") from None
    # Where the worker keeps provider responses: a one-pass plan's review is published
    # from its C4 answer there (one_pass.plan_publish).
    root = service.get("sales_xray_storage_root") if isinstance(service, dict) else None
    arguments.storage_root = Path(root) if isinstance(root, str) and root else None
    return asyncio.run(_inner_async(arguments, spend_environment=spend_environment))


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner:
        return _inner(arguments)
    if not arguments.apply or arguments.erase_erased_calls:
        # A dry run and the erasure cleanup need no provider key.
        return _inner(arguments)
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # pragma: no cover - execvpe replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
