from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.processing_plan import _retained_progress
from ac_platform.conversation_intelligence.submission_progress import (
    STAGES,
    StageCheckpoint,
    StageExecution,
    project_stage_progress,
)

NOW = datetime(2026, 10, 10, tzinfo=UTC)


def execution(stage="C2", state="queued", *, started=None, finished=None, checkpoint_id=None):
    return StageExecution(
        SimpleNamespace(run_id=uuid4(), stage=stage, state=state, checkpoint_id=checkpoint_id),
        SimpleNamespace(dispatch_started_at=started),
        SimpleNamespace(completed_at=finished),
    )


def project(items=(), *, current="C2", state="active", checkpoints=(), **kwargs):
    return project_stage_progress(
        plan=SimpleNamespace(
            state=state,
            progress={
                "current_stage": current,
                "stage_run_ids": [str(i.task.run_id) for i in items],
            },
        ),
        local_run=None,
        local_job=None,
        executions=list(items),
        checkpoints=list(checkpoints),
        has_report=kwargs.get("has_report", False),
        run_state=kwargs.get("run_state", "queued"),
        report_finished_at=kwargs.get("report_finished_at"),
    )


def row(result, stage):
    return next(r for r in result["stage_progress"] if r["stage"] == stage)


@pytest.mark.parametrize("stage", STAGES)
def test_current_stage_is_the_plan_fact_not_a_poll_clock(stage):
    result = project(current=stage)
    assert result["current_stage"] == stage
    assert result["terminal_state"] is None
    assert [r["stage"] for r in result["stage_progress"]] == list(STAGES)
    assert all(
        r["started_at"] is None and r["finished_at"] is None for r in result["stage_progress"]
    )


def test_dispatch_start_is_distinct_from_queued_and_running_without_a_dispatch():
    queued = execution()
    assert row(project([queued]), "C2")["started_at"] is None
    running = execution(state="running")
    assert row(project([running]), "C2")["started_at"] is None
    running.job.dispatch_started_at = NOW
    result = row(project([running]), "C2")
    assert result == {
        "stage": "C2",
        "state": "running",
        "started_at": NOW.isoformat(),
        "finished_at": None,
    }


def test_chunked_stage_finishes_only_after_all_selected_chunks():
    done = execution("C4", "completed", started=NOW, finished=NOW + timedelta(seconds=2))
    next_chunk = execution("C4")
    result = project([done, next_chunk], current="C4")
    assert row(result, "C4")["finished_at"] is None
    assert row(result, "C4")["started_at"] == NOW.isoformat()
    next_chunk.task.state = "completed"
    next_chunk.run.completed_at = NOW + timedelta(seconds=4)
    assert (
        row(project([done, next_chunk]), "C4")["finished_at"]
        == (NOW + timedelta(seconds=4)).isoformat()
    )


def test_retry_excludes_old_failure_and_old_downstream_lineage():
    old_checkpoint, new_checkpoint = uuid4(), uuid4()
    old = execution(state="uncertain", started=NOW, finished=NOW, checkpoint_id=old_checkpoint)
    fresh = execution(
        state="completed", checkpoint_id=new_checkpoint, finished=NOW + timedelta(seconds=2)
    )
    checkpoints = [
        StageCheckpoint(old_checkpoint, "C2", "a" * 64, (), NOW),
        StageCheckpoint(new_checkpoint, "C2", "b" * 64, (), NOW),
        StageCheckpoint(uuid4(), "C3", "c" * 64, (("C2", "a" * 64),), NOW),
    ]
    plan = SimpleNamespace(
        state="active", progress={"current_stage": "C4", "stage_run_ids": [str(fresh.task.run_id)]}
    )
    result = project_stage_progress(
        plan=plan,
        local_run=None,
        local_job=None,
        executions=[old, fresh],
        checkpoints=checkpoints,
        has_report=False,
        run_state="retrying",
        report_finished_at=None,
    )
    assert row(result, "C2")["state"] == "completed"
    assert row(result, "C2")["started_at"] is None
    assert row(result, "C3")["state"] == "waiting"
    checkpoints.append(StageCheckpoint(uuid4(), "C3", "d" * 64, (("C2", "b" * 64),), NOW))
    result = project([fresh], checkpoints=checkpoints)
    assert row(result, "C3")["finished_at"] == NOW.isoformat()
    assert row(result, "C3")["started_at"] is None


def test_terminal_failure_keeps_stage_and_does_not_invent_a_worker_finish():
    live = execution(state="running", started=NOW)
    result = project([live], state="held", run_state="failed")
    assert result["terminal_state"] == "failed"
    assert result["current_stage"] == "C2"
    assert row(result, "C2")["finished_at"] is None
    result = project(
        [live], current=None, has_report=True, run_state="done", report_finished_at=NOW
    )
    assert result["terminal_state"] == "done" and result["current_stage"] == "C6"
    assert row(result, "C6")["finished_at"] == NOW.isoformat()


def test_quoted_retry_and_local_retry_cannot_replay_provider_failure():
    old = execution(state="uncertain", started=NOW, finished=NOW)
    assert row(project([old], state="quoted"), "C2")["state"] == "waiting"
    result = project_stage_progress(
        plan=None,
        local_run=SimpleNamespace(state="running"),
        local_job=SimpleNamespace(dispatch_started_at=NOW),
        executions=[old],
        checkpoints=[StageCheckpoint(uuid4(), "C0", "a" * 64, (), NOW)],
        has_report=False,
        run_state="working",
        report_finished_at=None,
        local_retry=True,
    )
    assert result["current_stage"] == "C1"
    assert row(result, "C2")["state"] == "waiting"
    assert row(result, "C1")["started_at"] == NOW.isoformat()


def test_legacy_per_stage_execution_without_a_plan_still_has_a_live_timeline():
    task = execution(state="running", started=NOW)
    result = project_stage_progress(
        plan=None,
        local_run=None,
        local_job=None,
        executions=[task],
        checkpoints=[],
        has_report=False,
        run_state="working",
        report_finished_at=None,
    )
    assert result["current_stage"] == "C2"
    assert result["plan_state"] is None
    assert row(result, "C2")["started_at"] == NOW.isoformat()


def test_cached_local_checkpoint_does_not_use_a_later_retry_dispatch_as_its_start():
    result = project_stage_progress(
        plan=None,
        local_run=None,
        local_job=SimpleNamespace(dispatch_started_at=NOW + timedelta(seconds=2)),
        executions=[],
        checkpoints=[StageCheckpoint(uuid4(), "C1", "a" * 64, (), NOW)],
        has_report=False,
        run_state="queued",
        report_finished_at=None,
    )
    assert row(result, "C1")["finished_at"] == NOW.isoformat()
    assert row(result, "C1")["started_at"] is None


def test_terminal_coordinator_retains_only_known_content_free_execution_evidence():
    plan = SimpleNamespace(
        progress={
            "current_stage": "C4",
            "stage_run_ids": [str(uuid4())],
            "speaker_roles_frozen": True,
            "diagnostic_code": "old",
            "arbitrary": "withheld",
        }
    )
    assert _retained_progress(plan) == {
        key: plan.progress[key]
        for key in ("current_stage", "stage_run_ids", "speaker_roles_frozen")
    }
    plan.progress = {"current_stage": [], "stage_run_ids": [None]}
    assert _retained_progress(plan) == {}
