"""Operator runner: AI pointer reviews for a workspace's latest saved reports.

Owner decision 16 Oct 2026 (rulebook 693645b0): test the Report's AI scores by
reviewing the owner's last 5 dev calls. Dry run by default; ``--apply`` makes
one Gemini call per report and saves the validated review (append-only).

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
from uuid import UUID, uuid4

INNER = "--inner"
_PROVIDER = "gemini"


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pointer_review_cli")
    parser.add_argument("--service-config", required=True, type=Path)
    parser.add_argument("--database-url-file", required=True, type=Path)
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true", help="review again even if saved")
    # Outside the worker's mount namespace the identity token and Infisical
    # live at their host paths (the worker bind-mounts them read-only).
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--infisical", type=Path)
    parser.add_argument(INNER, action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.limit <= 10:
        parser.error("--limit must be 1-10")
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
                   d.source_sha256, d.payload ->> 'transcript_revision' AS transcript_revision,
                   d.transcript -> 'normalized' -> 'segments' AS segments
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


def _already_reviewed(connection: Any, report: dict[str, Any]) -> bool:
    from sqlalchemy import text

    return bool(
        connection.execute(
            text(
                "SELECT 1 FROM conversation_pointer_reviews WHERE run_id = :run"
                " AND source_sha256 = :source AND transcript_revision = :revision LIMIT 1"
            ),
            {
                "run": report["run_id"],
                "source": report["source_sha256"],
                "revision": report["transcript_revision"],
            },
        ).first()
    )


def _call_gemini(body: dict[str, Any]) -> dict[str, Any]:
    import httpx

    from ac_platform.conversation_intelligence.pointer_review import MODEL_ID

    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("pointer_review_credential_missing")
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_ID}:generateContent",
        headers={"x-goog-api-key": key, "content-type": "application/json"},
        json=body,
        timeout=httpx.Timeout(240.0, connect=20.0),
    )
    if response.status_code != 200:
        raise RuntimeError(f"provider_http_{response.status_code}")
    return dict(response.json())


def _inner(arguments: argparse.Namespace) -> int:
    from sqlalchemy import create_engine, insert

    from ac_platform.conversation_intelligence.pointer_review import (
        MODEL_ID,
        VERSION,
        PointerReviewError,
        build_prompt,
        decode_gemini,
        gemini_body,
        parse_review,
        payload_sha256,
        prompt_sha256,
    )
    from ac_platform.conversation_intelligence.pointer_review_models import (
        ConversationPointerReview,
    )

    url = arguments.database_url_file.read_text().strip()
    engine = create_engine(url, pool_pre_ping=True)
    failures = 0
    with engine.connect() as connection:
        reports = _latest_reports(connection, arguments.tenant, arguments.limit)
        print(json.dumps({"reports": len(reports), "apply": arguments.apply}))
        for report in reports:
            line: dict[str, Any] = {"submission": str(report["submission_id"])}
            withheld = _withheld(connection, report["recording_id"], report["transcript_revision"])
            segments = [
                segment
                for segment in (report["segments"] or [])
                if str(segment.get("id")) not in withheld
            ]
            line["segments"] = len(segments)
            if not arguments.force and _already_reviewed(connection, report):
                line["skipped"] = "already_reviewed"
                print(json.dumps(line))
                continue
            try:
                system, user = build_prompt(segments, {})
            except PointerReviewError as error:
                line["error"] = str(error)
                failures += 1
                print(json.dumps(line))
                continue
            if not arguments.apply:
                line["dry_run"] = True
                line["prompt_chars"] = len(system) + len(user)
                print(json.dumps(line))
                continue
            try:
                response = _call_gemini(gemini_body(system, user))
                review = parse_review(decode_gemini(response), segments)
            except (PointerReviewError, RuntimeError) as error:
                line["error"] = str(error)
                failures += 1
                print(json.dumps(line))
                continue
            usage = response.get("usageMetadata") or {}
            connection.execute(
                insert(ConversationPointerReview).values(
                    id=uuid4(),
                    tenant_id=report["tenant_id"],
                    recording_id=report["recording_id"],
                    run_id=report["run_id"],
                    report_draft_id=report["draft_id"],
                    source_sha256=report["source_sha256"],
                    transcript_revision=report["transcript_revision"],
                    version=VERSION,
                    model_id=MODEL_ID,
                    prompt_sha256=prompt_sha256(system, user),
                    payload=review,
                    payload_sha256=payload_sha256(review),
                    input_tokens=usage.get("promptTokenCount"),
                    output_tokens=usage.get("candidatesTokenCount"),
                    created_by="operator:report-ui-20261016",
                    created_at=datetime.now(UTC),
                )
            )
            connection.commit()
            line["overall"] = review["overall"]["score"]
            line["scored"] = review["overall"]["scored_pointers"]
            line["statuses"] = {
                status: sum(1 for p in review["pointers"] if p["status"] == status)
                for status in {p["status"] for p in review["pointers"]}
            }
            line["tokens"] = [usage.get("promptTokenCount"), usage.get("candidatesTokenCount")]
            print(json.dumps(line))
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    arguments = _arguments(raw)
    if arguments.inner:
        return _inner(arguments)
    if not arguments.apply:
        # A dry run needs no provider key: read and report only.
        return _inner(arguments)
    _reexec_inside_infisical([item for item in raw if item != INNER], arguments)
    return 0  # pragma: no cover - execvpe replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
