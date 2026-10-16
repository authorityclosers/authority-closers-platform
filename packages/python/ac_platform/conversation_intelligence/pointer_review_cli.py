"""Operator runner: AI pointer reviews for a workspace's latest saved reports.

Owner decision 16 Oct 2026 (rulebook 693645b0): test the Report's AI scores by
reviewing the owner's last 5 dev calls. Dry run by default; ``--apply`` makes
one Gemini call per report and saves the validated review (append-only).

Every paid call is admitted first (AUT-2010, ``pointer_review_admission``):
one runner per database, the call's consent, erasure and source checked
before the call and again before saving, and each attempt recorded in the
workspace's append-only audit chain, so timeouts, unreadable answers and
crashes count against the daily cap and the two-attempt limit.

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


def _latest_reports(connection: Any, tenant: UUID, limit: int) -> list[dict[str, Any]]:
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
            ORDER BY s.created_at DESC
            LIMIT :limit
            """
        ),
        {"tenant": tenant, "limit": limit},
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


class _ProviderFailure(RuntimeError):
    def __init__(self, outcome: str, usage: dict[str, Any] | None = None) -> None:
        super().__init__(outcome)
        self.outcome, self.usage = outcome, usage


def _call_gemini(body: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from ac_platform.conversation_intelligence.pointer_review import MODEL_ID

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("pointer_review_credential_missing")
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json=body,
            timeout=httpx.Timeout(240.0, connect=20.0),
        )
    except httpx.TimeoutException:
        raise _ProviderFailure("timeout") from None
    except httpx.HTTPError:
        raise _ProviderFailure("transport_error") from None
    if response.status_code != 200:
        raise _ProviderFailure(f"provider_http_{response.status_code}")
    try:
        return dict(response.json())
    except ValueError:
        raise _ProviderFailure("unreadable_response") from None


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
        response = (call_provider or _call_gemini)(gemini_body(system, user))
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


async def _inner_async(arguments: argparse.Namespace, call_provider: Any = None) -> int:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
                                sync.connection(), arguments.tenant, arguments.limit
                            )
                        )
                print(json.dumps({"reports": len(reports), "apply": arguments.apply}))
                dispatched = 0
                for report in reports:
                    if dispatched >= arguments.limit:
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
            finally:
                if arguments.apply:
                    await admission.release_run_lock(lock)
    finally:
        await engine.dispose()
    return 1 if failures else 0


def _inner(arguments: argparse.Namespace) -> int:
    import asyncio

    return asyncio.run(_inner_async(arguments))


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
