"""Offline, fixture-authored context/profile comparisons with measured receipts.

No provider, ASR, database, promotion, or training operation exists in this runner.
Its outcomes measure deterministic fixture expectations, not sales/model accuracy.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .checkpoints import SourceBinding, canonical, content_hash
from .context import SLOTS, compile_packet, project_profile, reduce_context, validate_transcript
from .review import development_cases

MAX_JSON_BYTES = 1_048_576
ADAPTER_REVISION = "context-profile-replay/1"


class BenchmarkError(ValueError):
    """Fixed public message; input text and exception details stay out of receipts."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FileRef(Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}\.json$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Case(Strict):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    participant_partition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    split: Literal["development", "calibration", "holdout"]
    permission_ref: str = Field(pattern=r"^fixture://[a-z0-9/_-]{1,160}$")
    manifest_revision: str = Field(min_length=1, max_length=80)
    input: FileRef | None


class Candidate(Strict):
    candidate_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    adapter: Literal["context-profile-replay/1"]
    revision: str = Field(min_length=1, max_length=80)
    profile: dict[str, Any]
    packet_budget_bytes: int = Field(ge=1_000, le=65_536)


class Suite(Strict):
    schema_id: Literal["ac.sales-xray.offline-benchmark/1"]
    data_class: Literal["synthetic_fixture"]
    manifest_revision: str = Field(min_length=1, max_length=80)
    cases: list[Case] = Field(min_length=1, max_length=64)
    selected_case_ids: list[str] = Field(min_length=1, max_length=32)
    candidates: list[Candidate] = Field(min_length=1, max_length=4)


class ExpectedSlot(Strict):
    status: Literal["unknown", "supported", "conflicted", "contradicted"]
    value: Any


class Fixture(Strict):
    data_class: Literal["synthetic_fixture"]
    transcript: dict[str, Any]
    observations: list[dict[str, Any]] = Field(max_length=64)
    as_of_ms: int = Field(ge=0)
    critical_ids: list[str] = Field(max_length=64)
    counterevidence_ids: list[str] = Field(max_length=64)
    expected_outcome: Literal["accepted", "rejected"]
    expected_rejection_stage: Literal["context", "packet"] | None
    expected_slots: dict[str, ExpectedSlot]
    expected_applicability: dict[
        str, Literal["applicable", "not_applicable", "insufficient_context"]
    ]


def bounded_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_JSON_BYTES:
        raise BenchmarkError("Benchmark input exceeds its byte limit.")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BenchmarkError("Duplicate JSON fields are not supported.")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique_pairs)
        remaining = [20_000]

        def check(node: Any, depth: int) -> None:
            remaining[0] -= 1
            if depth > 20 or remaining[0] < 0:
                raise BenchmarkError("Benchmark input exceeds its structure limit.")
            if isinstance(node, dict):
                for item in node.values():
                    check(item, depth + 1)
            elif isinstance(node, list):
                for item in node:
                    check(item, depth + 1)
            elif isinstance(node, float) and not math.isfinite(node):
                raise BenchmarkError("Nonfinite JSON numbers are not supported.")

        check(value, 0)
        if not isinstance(value, dict):
            raise BenchmarkError("Benchmark input must be an object.")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise BenchmarkError("Benchmark JSON is invalid or exceeds its limits.") from exc


def selected_cases(suite: Suite) -> tuple[Case, ...]:
    """Validate all metadata before any fixture file is opened; never inspect holdout."""
    if len({c.candidate_id for c in suite.candidates}) != len(suite.candidates):
        raise BenchmarkError("Candidate identities must be unique.")
    for candidate in suite.candidates:
        try:
            criteria = candidate.profile.get("criteria")
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 32:
                raise ValueError("bounded criteria required")
            projection = project_profile(
                candidate.profile,
                {
                    "slots": {slot: {"status": "unknown"} for slot in SLOTS},
                    "fact_state_hash": "0" * 64,
                },
            )
            held = projection["numeric_publication"]
            if (held["declared_total"], held["actual_source_total"]) != (100, 95):
                raise ValueError("This fixture protocol preserves the unresolved 95/100 source.")
        except (ValueError, TypeError, KeyError) as exc:
            raise BenchmarkError("Candidate profile is invalid.") from exc
    for case in suite.cases:
        if case.manifest_revision != suite.manifest_revision:
            raise BenchmarkError("Dataset revisions do not match.")
        if (case.split == "holdout") != (case.input is None):
            raise BenchmarkError("Holdout must be metadata-only; development needs an input.")
    try:
        selected = development_cases(
            [case.model_dump(exclude={"input"}) for case in suite.cases],
            suite.selected_case_ids,
        )
    except ValueError as exc:
        raise BenchmarkError("Dataset partition or selection is invalid.") from exc
    by_id = {case.case_id: case for case in suite.cases}
    return tuple(by_id[item["case_id"]] for item in selected)


def _fixture(raw: bytes, case: Case) -> Fixture:
    if case.input is None or hashlib.sha256(raw).hexdigest() != case.input.sha256:
        raise BenchmarkError("Fixture digest does not match the selected manifest.")
    try:
        fixture = Fixture.model_validate(bounded_json(raw))
        if (fixture.expected_outcome == "rejected") != (
            fixture.expected_rejection_stage is not None
        ):
            raise ValueError("explicit expected rejection stage required")
        if not fixture.expected_slots and fixture.expected_outcome == "accepted":
            raise ValueError("fixture needs explicit expectations")
        if not fixture.expected_slots.keys() <= SLOTS:
            raise ValueError("unsupported expected slot")
        segments = fixture.transcript.get("segments")
        if not isinstance(segments, list) or len(segments) > 128:
            raise ValueError("bounded segment list required")
        if any(not isinstance(s, dict) or len(s.get("text", "")) > 8_000 for s in segments):
            raise ValueError("bounded segment text required")
        if fixture.transcript.get("source_sha256") != case.source_sha256:
            raise ValueError("source mismatch")
        # Full tenant/source identity stays in the private fixture. There is no
        # production authorization implied by possessing this local fixture.
        SourceBinding(
            **{
                key: fixture.transcript[key]
                for key in ("tenant_id", "recording_id", "source_sha256", "source_revision")
            }
        )
        return fixture
    except (ValueError, TypeError, KeyError) as exc:
        raise BenchmarkError("Selected fixture is invalid.") from exc


def _percentile(values: list[int], fraction: float) -> int:
    """Nearest-rank diagnostic across cases, never across overlapping audio frames."""
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def compare(
    suite: Suite,
    inputs: dict[str, bytes],
    *,
    run_id: UUID,
    implementation_sha256: str,
) -> dict[str, Any]:
    cases = selected_cases(suite)
    if set(inputs) != {case.case_id for case in cases}:
        raise BenchmarkError("Inputs must exactly match selected development cases.")
    # Parse all selected input before running the first comparison.
    fixtures = {case.case_id: _fixture(inputs[case.case_id], case) for case in cases}
    if len(implementation_sha256) != 64 or any(
        c not in "0123456789abcdef" for c in implementation_sha256
    ):
        raise BenchmarkError("An exact implementation digest is required.")
    rows: list[dict[str, Any]] = []
    context_executions = 0
    profile_executions = 0
    deadline = time.perf_counter() + 60
    for case in cases:
        fixture = fixtures[case.case_id]
        begin = time.perf_counter_ns()
        context: dict[str, Any] | None = None
        try:
            validate_transcript(fixture.transcript)
            context_executions += 1
            context = reduce_context(fixture.observations, fixture.transcript, fixture.as_of_ms)
        except (ValueError, TypeError, KeyError):
            pass
        context_ns = time.perf_counter_ns() - begin
        for candidate in suite.candidates:
            if time.perf_counter() > deadline:
                raise BenchmarkError("Offline comparison exceeded its deadline.")
            begin = time.perf_counter_ns()
            failed_checks: list[str] = []
            projection: dict[str, Any] | None = None
            packet: dict[str, Any] | None = None
            candidate_context = deepcopy(context)
            state_before = (
                content_hash(candidate_context) if candidate_context is not None else None
            )
            rejection_stage = "context" if context is None else "packet"
            try:
                if candidate_context is None:
                    raise ValueError("invalid context input")
                profile_executions += 1
                projection = project_profile(deepcopy(candidate.profile), candidate_context)
                packet = compile_packet(
                    fixture.transcript,
                    candidate_context,
                    critical_ids=fixture.critical_ids,
                    counterevidence_ids=fixture.counterevidence_ids,
                    max_bytes=candidate.packet_budget_bytes,
                )
                for slot, expected in fixture.expected_slots.items():
                    actual = candidate_context["slots"][slot]
                    if actual["status"] != expected.status or canonical(
                        actual["value"]
                    ) != canonical(expected.value):
                        failed_checks.append("context_slot_mismatch")
                actual_applicability = {
                    item["criterion_id"]: item["applicability"] for item in projection["checks"]
                }
                if actual_applicability != fixture.expected_applicability:
                    failed_checks.append("profile_applicability_mismatch")
                if projection["numeric_publication"]["state"] != "withheld":
                    failed_checks.append("numeric_publication_not_withheld")
                if content_hash(candidate_context) != state_before:
                    failed_checks.append("profile_mutated_context")
                if fixture.expected_outcome != "accepted":
                    failed_checks.append("unexpected_acceptance")
                outcome = "accepted"
            except (ValueError, TypeError, KeyError):
                outcome = "rejected"
                if fixture.expected_outcome != "rejected":
                    failed_checks.append("unexpected_rejection")
                elif fixture.expected_rejection_stage != rejection_stage:
                    failed_checks.append("wrong_rejection_stage")
            if time.perf_counter() > deadline:
                raise BenchmarkError("Offline comparison exceeded its deadline.")
            rows.append(
                {
                    "case_id": case.case_id,
                    "split": case.split,
                    "candidate_id": candidate.candidate_id,
                    "candidate_sha256": content_hash(candidate.model_dump()),
                    "source_sha256": case.source_sha256,
                    "input_sha256": hashlib.sha256(inputs[case.case_id]).hexdigest(),
                    "transcript_sha256": content_hash(fixture.transcript),
                    "context_sha256": state_before,
                    "projection_sha256": content_hash(projection)
                    if projection is not None
                    else None,
                    "packet_sha256": content_hash(packet) if packet is not None else None,
                    "context_elapsed_ns": context_ns,
                    "candidate_elapsed_ns": time.perf_counter_ns() - begin,
                    "outcome": outcome,
                    "rejection_stage": rejection_stage if outcome == "rejected" else None,
                    "state": "failed" if failed_checks else "passed",
                    "failed_checks": sorted(set(failed_checks)),
                    "packet_bytes": len(canonical(packet)) if packet is not None else None,
                    "coverage": packet["coverage"] if packet is not None else None,
                }
            )
    summaries = []
    for candidate in suite.candidates:
        selected = [r for r in rows if r["candidate_id"] == candidate.candidate_id]
        times = [int(r["candidate_elapsed_ns"]) for r in selected]
        summaries.append(
            {
                "candidate_id": candidate.candidate_id,
                "cases": len(selected),
                "passed": sum(r["state"] == "passed" for r in selected),
                "failed": sum(r["state"] == "failed" for r in selected),
                "elapsed_ns_p50": _percentile(times, 0.50),
                "elapsed_ns_p95": _percentile(times, 0.95),
                "latency_basis": "all_cases_including_rejections_nearest_rank",
            }
        )
    body = {
        "schema": "ac.sales-xray.offline-benchmark-receipt/1",
        "run_id": str(run_id),
        "adapter_revision": ADAPTER_REVISION,
        "implementation_sha256": implementation_sha256,
        "suite_sha256": content_hash(suite.model_dump()),
        "state": "passed" if all(row["state"] == "passed" for row in rows) else "failed",
        "selected_cases": len(cases),
        "comparison_count": len(rows),
        "input_artifacts": len(inputs),
        "context_executions": context_executions,
        "profile_case_executions": profile_executions,
        "provider_calls": 0,
        "asr_calls": 0,
        "provider_cost_paise": 0,
        "measurement_scope": "synthetic_context_profile_replay_only",
        "model_quality_measured": False,
        "human_adjudicated": False,
        "holdout_content_opened": False,
        "numeric_publication": "withheld",
        "automatic_retraining": False,
        "production_mutated": False,
        "summaries": summaries,
        "rows": rows,
    }
    return {**body, "receipt_sha256": content_hash(body)}


def implementation_digest() -> str:
    """Bind the runner and every pure implementation it invokes, not a caller label."""
    root = Path(__file__).parent
    return content_hash(
        {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (
                "benchmark.py",
                "benchmark_cli.py",
                "context.py",
                "checkpoints.py",
                "review.py",
            )
        }
    )
