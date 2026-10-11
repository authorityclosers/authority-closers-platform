"""Analysis health (AUT-1798): codes only, honest statistics, operations admission."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.admin_analysis_health import (
    AdminAnalysisHealth,
    _percentile,
    failed_job_view,
    failure_code,
    version_rows,
)
from ac_platform.conversation_intelligence.application import ConversationDenied, ConversationError

OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
TEAM = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")


def _job(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**{"failure_detail": None, "last_error": None, **values})


def test_failure_code_never_shows_free_text() -> None:
    assert failure_code(_job(failure_detail={"code": "provider_timeout"})) == "provider_timeout"
    assert failure_code(_job(last_error="conversation_local_phase_failed")) == (
        "conversation_local_phase_failed"
    )
    assert failure_code(_job(last_error="Traceback: secret prospect said X")) == "withheld"
    assert failure_code(_job(failure_detail={"code": "Has Spaces"}, last_error=None)) == (
        "not_recorded"
    )
    assert failure_code(_job()) == "not_recorded"


def test_failed_job_view_says_whether_the_admin_retry_may_run() -> None:
    stamp = datetime(2026, 10, 11, 3, 0, tzinfo=UTC)
    base = {
        "id": UUID(int=7),
        "attempt_count": 3,
        "created_at": stamp,
        "dead_lettered_at": stamp,
        "dispatch_started_at": None,
        "provider_receipt": None,
        "delivery_ambiguous_at": None,
        "last_error": "Prospect said something private",
    }
    view = failed_job_view(_job(**base), stage="C2", recording_id=UUID(int=9))
    assert view == {
        "job_id": str(UUID(int=7)),
        "stage": "C2",
        "recording_id": str(UUID(int=9)),
        "attempts": 3,
        "code": "withheld",
        "created_at": stamp.isoformat(),
        "failed_at": stamp.isoformat(),
        "retryable": True,
    }
    # Work that reached a provider is never offered for retry: it could charge twice.
    for reached in (
        {"dispatch_started_at": stamp},
        {"provider_receipt": {"id": "r"}},
        {"delivery_ambiguous_at": stamp},
    ):
        job = _job(**{**base, **reached})
        assert failed_job_view(job, stage="C2", recording_id=None)["retryable"] is False
    assert failed_job_view(_job(**base), stage="C1", recording_id=None)["recording_id"] is None


def _plan(identifier: int, state: str, prompt: str | None, model: str | None) -> SimpleNamespace:
    stages = [{"stage": "C5", "provider_id": "google", "model_id": model}] if model else []
    manifest = {"duration_ms": 120_000, "stages": stages}
    if prompt:
        manifest["coaching_prompt_revision"] = prompt
    return SimpleNamespace(id=UUID(int=identifier), state=state, manifest=manifest)


def test_version_rows_compare_prompt_versions_by_outcome_time_and_cost() -> None:
    start = datetime(2026, 10, 11, 3, 0, tzinfo=UTC)
    plans = {
        plan.id: plan
        for plan in (
            _plan(1, "completed", "coaching-v5", "gemini-3.8-pro"),
            _plan(2, "active", "coaching-v5", "gemini-3.8-pro"),
            _plan(3, "completed", "coaching-v4", "gemini-3.8-flash"),
            _plan(4, "cancelled", None, None),
        )
    }
    base = {
        "attempt_count": 1,
        "dispatch_started_at": None,
        "receipt_recorded_at": None,
        "provider_receipt": None,
        "status": "succeeded",
    }
    jobs = [
        # v5: one Report step took 40 s; one transcript step failed after a retry.
        _job(
            **{
                **base,
                "id": UUID(int=11),
                "dispatch_started_at": start,
                "receipt_recorded_at": start.replace(second=40),
            }
        ),
        _job(**{**base, "id": UUID(int=12), "status": "dead_letter", "attempt_count": 3}),
        _job(**{**base, "id": UUID(int=13)}),
        # A job with no plan link is left out, never guessed.
        _job(**{**base, "id": UUID(int=14), "status": "dead_letter"}),
    ]
    job_plan = {UUID(int=11): UUID(int=1), UUID(int=12): UUID(int=2), UUID(int=13): UUID(int=3)}
    stages = {UUID(int=11): "C5", UUID(int=12): "C2", UUID(int=13): "C5"}
    rows = version_rows(jobs, job_plan, plans, lambda job: stages.get(job.id, "C1"))  # type: ignore[arg-type]

    assert [(row["prompt_revision"], row["model"]) for row in rows] == [
        ("coaching-v5", "gemini-3.8-pro"),
        (None, None),
        ("coaching-v4", "gemini-3.8-flash"),
    ]
    v5 = rows[0]
    assert v5["analyses"] == 2 and v5["completed"] == 1 and v5["in_flight"] == 1
    assert v5["failed_steps"] == 1 and v5["retried_steps"] == 1
    assert v5["report_p50_ms"] == 40_000
    # No receipts, so no cost is claimed.
    assert v5["paise_per_minute"] is None and v5["priced_minutes"] == 0
    unknown = rows[1]
    assert unknown["analyses"] == 1 and unknown["completed"] == 0 and unknown["failed_steps"] == 0
    assert version_rows([], {}, {}, lambda job: "C1") == []


def test_percentile_is_bounded_and_empty_is_none() -> None:
    assert _percentile([], 0.9) is None
    assert _percentile([5.0], 0.9) == 5.0
    assert _percentile([float(value) for value in range(1, 11)], 0.9) == 9.0


@pytest.mark.asyncio
async def test_only_the_operations_workspace_and_a_bounded_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AdminAnalysisHealth(
        SimpleNamespace(database=None, clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)),  # type: ignore[arg-type]
        OPS,
        recording_tenant_ids=(TEAM, OPS),
    )
    assert service.recording_tenant_ids == (TEAM,)
    with pytest.raises(ConversationDenied):
        await service.summary(SimpleNamespace(tenant_id=TEAM))  # type: ignore[arg-type]

    async def admitted(_self: AdminAnalysisHealth, _actor: object) -> datetime:
        return datetime(2026, 10, 11, tzinfo=UTC)

    monkeypatch.setattr(AdminAnalysisHealth, "_admit", admitted)
    for days in (0, 31):
        with pytest.raises(ConversationError):
            await service.summary(SimpleNamespace(tenant_id=OPS), days=days)  # type: ignore[arg-type]
