"""Which calls the fast pipeline reads (owner, 21 Oct 2026): in production, only calls whose
report's one-pass read does not fill their lead details."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.call_ai import store as call_ai
from ac_platform.call_data import engine, runner
from ac_platform.call_data.settings import SettingsError, fast_calls, public, validate
from ac_platform.one_pass import plan_publish


def test_production_leaves_one_pass_calls_and_other_environments_read_every_call() -> None:
    config = validate({})
    assert config["fast"]["calls"] == "auto"
    assert fast_calls(config, "production") == "not_one_pass"
    for environment in ("staging", "development", None):
        assert fast_calls(config, environment) == "all"
    # Admin may choose either way in any environment.
    assert fast_calls(validate({"fast": {"calls": "all"}}), "production") == "all"
    assert fast_calls(validate({"fast": {"calls": "not_one_pass"}}), "staging") == "not_one_pass"
    with pytest.raises(SettingsError):
        validate({"fast": {"calls": "some"}})
    with pytest.raises(SettingsError):
        validate({"deep": {"calls": "all"}})
    menu = [item["value"] for item in public(config, revision=None)["fast_calls"]]
    assert menu == ["auto", "all", "not_one_pass"]


class _Connection:
    def __init__(self, c4_started: set) -> None:
        self.c4_started = c4_started

    def scalar(self, statement, values):
        assert "conversation_inference_tasks" in str(statement)
        return values["recording"] in self.c4_started


def _call() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=uuid4(), recording_id=uuid4())


def test_stopped_and_todays_c4_calls_are_read_and_one_pass_calls_are_left(monkeypatch) -> None:
    short, data_only, classic, one_pass, deciding = (_call() for _ in range(5))
    planned = {short.recording_id, data_only.recording_id, one_pass.recording_id}
    planned.add(deciding.recording_id)
    stopped = {short.recording_id, data_only.recording_id}
    monkeypatch.setattr(plan_publish, "one_pass_plans", lambda connection, ids: planned & set(ids))
    monkeypatch.setattr(
        call_ai,
        "runs_beyond_transcript",
        lambda connection, tenant, recording: recording not in stopped,
    )
    connection = _Connection({one_pass.recording_id, short.recording_id})
    read, left = runner.one_pass_split(connection, [short, data_only, classic, one_pass, deciding])
    # Short and Data only calls get the fast lead details; today's C4 has no one-pass read.
    assert read == [short, data_only, classic]
    # One pass fills the full call; a plan not yet past the short-call decision waits.
    assert left == [one_pass]


def test_a_call_left_to_one_pass_is_recorded_once_as_a_skipped_run(monkeypatch) -> None:
    saved: list[dict] = []
    monkeypatch.setattr(engine, "load", lambda connection, call: call)
    monkeypatch.setattr(engine, "skip_run", lambda connection, call, **values: saved.append(values))

    class _Session:
        def connection(self):
            return object()

        @contextmanager
        def begin(self):
            yield

    @contextmanager
    def sessions():
        yield _Session()

    call = _call()
    dry = runner.leave_to_one_pass(
        sessions, call, apply=False, trigger="auto", created_by=runner.AUTOMATIC
    )
    assert dry == {"recording": str(call.recording_id), "skipped": "one_pass_fills"}
    assert saved == []
    runner.leave_to_one_pass(
        sessions, call, apply=True, trigger="auto", created_by=runner.AUTOMATIC
    )
    assert [(item["reason"], item["pipeline"]) for item in saved] == [("one_pass_fills", "fast")]
