# ruff: noqa: E501, S608 - SQL templates, one clause per line; every value put in is checked first (a UUID, hex SHA-256s, an aware time)
"""Read back what the server made of each test call, and judge it against the scenario.

Reads go through the logged, read-only query path on ac (``/home/suyash/costq/q.sh``: the
session is forced read-only, every file is logged in ``QUERY-LOG.txt``). The checker matches
only rows whose source SHA-256 is one of this run's files, so it never reads another call.

Two kinds of result per scenario:

- **gate** (the pipeline works): the phone uploaded the call through the app, the server
  finished it, and the result is what the scenario expects: a complete report (summary,
  verdict, strengths, an improvement, 8 dimensions, 9 sections, a next-call focus) or the
  expected hold (``ai_short_call`` / ``ai_no_conversation``).
- **detect** (sales or not): what the server decided against the scenario's ``sales``. A
  hold means "not a conversation". A report counts as a sales verdict unless it stores a call
  purpose (``call_map.call_purpose.kind``); on 13 Nov 2026 production stored none, so every
  report is coached as a sales call. That is a known gap, reported but not gating by default.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

APP_HOST = "https://salesxray.authorityclosers.com"
HOLDS = {"ai_short_call": "short_call", "ai_no_conversation": "no_conversation"}
SAFE_PURPOSE = re.compile(r"[^A-Za-z0-9 ,.;:()/_+=-]")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHA = re.compile(r"[0-9a-f]{64}")


def _uuid(value: str) -> str:
    if not UUID.fullmatch(value):
        raise ValueError("uuid")
    return value


def _moment(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("aware time")
    return value.isoformat(timespec="seconds")


def preflight_sql(lead_id: str) -> str:
    """The QA lead's workspace, phone and creation, the workspace's work hours, the seller's
    minute account and the seller's call times in the last 8 days (times only)."""
    lead = _uuid(lead_id)
    return f"""-- call testing preflight: QA lead, work hours, QA seller minutes and call times (read-only)
SELECT json_build_object(
  'lead_id', l.id, 'tenant_id', l.tenant_id, 'name', l.name, 'phone', l.phone,
  'created_at', l.created_at, 'seller', l.owner_person_id,
  'work_hours', s.config -> 'work_hours',
  'minutes', m.snapshot,
  'calls', (SELECT coalesce(json_agg(json_build_object('at', e.created_at, 'seconds', e.data ->> 'duration_seconds')), '[]'::json)
            FROM lead_desk_events e
            WHERE e.tenant_id = l.tenant_id AND e.kind = 'call' AND e.actor_person_id = l.owner_person_id
              AND e.created_at > now() - interval '8 days'))
FROM lead_desk_leads l
LEFT JOIN lead_desk_settings s ON s.tenant_id = l.tenant_id
LEFT JOIN conversation_minute_accounts m ON m.tenant_id = l.tenant_id AND m.person_id = l.owner_person_id
WHERE l.id = '{lead}';
"""


def status_sql(shas: Iterable[str], since: datetime) -> str:
    """One JSON line per uploaded test file: submission, plan and report facts (no transcript)."""
    picked = sorted({sha for sha in shas if SHA.fullmatch(sha)})
    if not picked:
        raise ValueError("no hashes")
    listed = ", ".join(f"'{sha}'" for sha in picked)
    return f"""-- call testing status: only this run's synthetic files, by SHA-256 (read-only)
SELECT json_build_object(
  'sha', s.source_sha256, 'submission_id', s.submission_id, 'recording_id', s.recording_id,
  'capture_source', s.capture_source, 'uploaded_at', s.created_at,
  'plan_state', p.state, 'failure_code', p.progress ->> 'failure_code',
  'skip_reason', p.progress ->> 'ai_skip_reason', 'stage', p.progress ->> 'current_stage',
  'plan_at', p.created_at,
  'report', d.id IS NOT NULL, 'report_at', d.created_at,
  'summary', length(coalesce(d.payload ->> 'summary', '')) > 0,
  'verdict', length(coalesce(d.payload ->> 'verdict', '')) > 0,
  'strengths', CASE WHEN json_typeof(d.payload -> 'strengths') = 'array' THEN json_array_length(d.payload -> 'strengths') END,
  'improvements', CASE WHEN json_typeof(d.payload -> 'improvements') = 'array' THEN json_array_length(d.payload -> 'improvements') END,
  'dimensions', CASE WHEN json_typeof(d.payload -> 'dimensions') = 'array' THEN json_array_length(d.payload -> 'dimensions') END,
  'sections', CASE WHEN json_typeof(d.payload -> 'report_sections') = 'array' THEN json_array_length(d.payload -> 'report_sections') END,
  'focus', d.payload -> 'overview' -> 'next_call_focus' ->> 'behavior',
  'practice', d.payload -> 'overview' -> 'practice' ->> 'instructions',
  'purpose', d.payload -> 'call_map' -> 'call_purpose' ->> 'kind',
  'summary_head', left(d.payload ->> 'summary', 240))
FROM conversation_guest_submissions s
LEFT JOIN LATERAL (
  SELECT * FROM conversation_processing_plans p
  WHERE p.recording_id = s.recording_id AND p.erased_at IS NULL
  ORDER BY p.generation DESC, p.created_at DESC LIMIT 1) p ON true
LEFT JOIN LATERAL (
  SELECT * FROM conversation_report_drafts d
  WHERE d.recording_id = s.recording_id AND d.erased_at IS NULL
  ORDER BY d.created_at DESC LIMIT 1) d ON true
WHERE s.source_sha256 IN ({listed}) AND s.created_at >= '{_moment(since)}'::timestamptz;
"""


def remote_sql(
    sql: str, *, env: str, name: str, purpose: str | None, host: str = "ac", timeout: float = 120
) -> list[dict[str, Any]]:
    """Run ``sql`` through ac's read-only query helper. ``purpose`` writes the QUERY-LOG line
    (once per file); each output line is one JSON object."""
    if env not in {"dev", "staging", "production"} or not re.fullmatch(
        r"ctp-[a-z0-9-]{1,60}", name
    ):
        raise ValueError("env or name")
    path = f"/home/suyash/costq/{name}.sql"
    log = ""
    if purpose:
        line = SAFE_PURPOSE.sub("", purpose)[:400]
        log = (
            f'echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) {name}.sql {env} ({line}) by laptop call-testing"'
            " >> /home/suyash/costq/QUERY-LOG.txt && "
        )
    command = f"cat > {path} && {log}bash /home/suyash/costq/q.sh {env} {path}"
    done = subprocess.run(  # noqa: S603 - ssh to our own host with a fixed command
        ["ssh", host, command],  # noqa: S607
        input=sql.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"query {name}: {done.stderr.decode('utf-8', 'replace')[:400]}")
    rows = []
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            rows.append(json.loads(line))
    return rows


def outcome_of(row: Mapping[str, Any] | None) -> str:
    """uploaded / analysing / report / short_call / no_conversation / held:<code> / failed:<state>
    / missing (not uploaded yet)."""
    if not row:
        return "missing"
    if row.get("report"):
        return "report"
    state = row.get("plan_state")
    code = row.get("failure_code")
    if state == "held":
        return HOLDS.get(str(code), f"held:{code or 'unknown'}")
    if state in {"failed", "cancelled", "expired"}:
        return f"failed:{state}"
    if state is None:
        return "uploaded"
    return "analysing"


TERMINAL_PREFIXES = ("report", "short_call", "no_conversation", "held:", "failed:")


def is_terminal(outcome: str) -> bool:
    return outcome.startswith(TERMINAL_PREFIXES)


def report_gaps(row: Mapping[str, Any]) -> list[str]:
    """What a complete report lacks (empty when complete)."""
    gaps = []
    if not row.get("summary"):
        gaps.append("no summary")
    if not row.get("verdict"):
        gaps.append("no verdict")
    if not (row.get("strengths") or 0) >= 1:
        gaps.append("no strength")
    if not (row.get("improvements") or 0) >= 1:
        gaps.append("no improvement")
    if row.get("dimensions") != 8:
        gaps.append(f"dimensions {row.get('dimensions')} of 8")
    if row.get("sections") != 9:
        gaps.append(f"sections {row.get('sections')} of 9")
    if not row.get("focus"):
        gaps.append("no next-call focus (coaching mission)")
    return gaps


def detected_sales(row: Mapping[str, Any] | None) -> tuple[bool | None, str]:
    """What the server decided: (is it a sales call?, how we know)."""
    outcome = outcome_of(row)
    if outcome in {"short_call", "no_conversation"}:
        return False, f"held as {outcome.replace('_', ' ')}: not analysed as a sales conversation"
    if outcome != "report" or row is None:
        return None, "no decision yet"
    purpose = row.get("purpose")
    if purpose:
        return purpose == "sales", f"stored call purpose: {purpose}"
    return True, "no call purpose stored: coached as a sales call"


def judge(
    scenario: Mapping[str, Any], row: Mapping[str, Any] | None, *, final: bool
) -> dict[str, Any]:
    """Gate and detection results for one scenario. ``final``: the wait is over, so anything
    unfinished fails rather than stays pending."""
    expect = scenario["expect"]
    want = expect["outcome"]
    got = outcome_of(row)
    notes: list[str] = []
    gate = "pending"
    if row and row.get("capture_source") not in (None, "android_dialer_pickup"):
        notes.append(f"captured as {row.get('capture_source')}, not the dialler pickup")
    if is_terminal(got):
        if got == "report":
            gaps = report_gaps(row or {})
            notes.extend(gaps)
            fits = want in {"report", "any"} and not gaps
            if want in {"short_call", "no_conversation", "held"}:
                notes.append(f"expected a hold ({want}), got a full report")
        elif got in {"short_call", "no_conversation"}:
            fits = want in {got, "held", "any"}
            if not fits:
                notes.append(f"expected {want}, held as {got}")
        else:
            fits = False
            notes.append(got)
        gate = "pass" if fits and not any("captured as" in n for n in notes) else "fail"
    elif final:
        gate = "fail"
        notes.append(
            {"missing": "never uploaded", "uploaded": "uploaded, never planned"}.get(
                got, f"still {got}"
            )
        )
    sales, how = detected_sales(row)
    if sales is None:
        detect = "pending" if not final else "n/a"
    else:
        detect = "pass" if sales == bool(expect["sales"]) else "fail"
        purpose = (row or {}).get("purpose")
        if purpose and expect.get("purpose") and purpose not in expect["purpose"]:
            notes.append(f"purpose {purpose}, expected one of {', '.join(expect['purpose'])}")
    seconds = None
    if row and row.get("report_at") and row.get("uploaded_at"):
        seconds = round((_parse(row["report_at"]) - _parse(row["uploaded_at"])).total_seconds())
    return {
        "outcome": got,
        "gate": gate,
        "detect": detect,
        "detected": how,
        "notes": notes,
        "report_seconds": seconds,
        "link": f"{APP_HOST}/analysis/calls/{row['submission_id']}"
        if row and row.get("submission_id")
        else None,
        "focus": (row or {}).get("focus"),
        "summary_head": (row or {}).get("summary_head"),
    }


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def run_verdict(
    results: Iterable[Mapping[str, Any]], *, crashes: list[str], app_alive: bool, strict: bool
) -> dict[str, Any]:
    rows = list(results)
    gate_fail = [r["id"] for r in rows if r["gate"] != "pass"]
    detect_fail = [r["id"] for r in rows if r["detect"] == "fail"]
    passed = not gate_fail and not crashes and app_alive and (not strict or not detect_fail)
    return {
        "passed": passed,
        "gate_failed": gate_fail,
        "detect_failed": detect_fail,
        "crashes": crashes,
        "app_alive": app_alive,
        "strict": strict,
    }
