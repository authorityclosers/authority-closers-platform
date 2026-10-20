"""The Admin call map's main analysis, one node per stage (C3 to C6). Pure: rows as dicts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ac_platform.call_data.call_map import _analysis_stages
from ac_platform.call_data.detail import EDGES

T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def task(state: str, start: float, end: float | None, tokens: tuple[int, int] = (1000, 200)):
    return {
        "state": state,
        "created_at": at(start),
        "saved_at": at(end) if end is not None and state == "completed" else None,
        "receipt_recorded_at": at(end) if end is not None else None,
        "provider_receipt": {
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "usage": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1]},
        },
    }


def checkpoint(seconds: float):
    return {"created_at": at(seconds), "media_ms": None}


def by_key(stages):
    return {item["key"]: item for item in stages}


def test_a_finished_call_has_every_stage_with_its_own_time_tokens_and_cost() -> None:
    checkpoints = {name: checkpoint(s) for name, s in [("C1", 4), ("C2", 40), ("C3", 41)]}
    checkpoints |= {"C5": checkpoint(95), "C6": checkpoint(96)}
    tasks = {
        "C4": [task("completed", 42, 60), task("failed", 42, 50), task("completed", 51, 70)],
        "C5": [task("completed", 71, 95, (3000, 900))],
    }
    stages = by_key(_analysis_stages(tasks, checkpoints, 210_000))
    assert [s["key"] for s in _analysis_stages(tasks, checkpoints, 210_000)] == [
        "alignment",
        "facts",
        "coaching",
        "published",
    ]
    assert [s["code"] for s in stages.values()] == ["C3", "C4", "C5", "C6"]
    assert stages["alignment"]["status"] == "done"
    assert stages["alignment"]["duration_ms"] == 1000  # from the later parent, C2
    facts = stages["facts"]
    assert facts["status"] == "done" and facts["duration_ms"] == 28_000  # 42 s to the last save
    assert facts["counts"] == {
        "attempts": 3,
        "completed": 2,
        "failed": 1,
        "tokens_in": 3000,
        "tokens_out": 600,
    }
    assert facts["model"] == "gemini-3.8-flash" and facts["cost_inr"] is not None
    assert facts["detail"] == "3 tasks · 1 failed or unsure"
    assert stages["coaching"]["counts"]["tokens_in"] == 3000
    assert stages["published"]["status"] == "done"
    assert stages["published"]["duration_ms"] == 1000


def test_a_running_call_shows_where_it_is_and_what_waits() -> None:
    checkpoints = {"C1": checkpoint(4), "C2": checkpoint(40), "C3": checkpoint(41)}
    tasks = {"C4": [task("completed", 42, 60), task("running", 42, None)]}
    stages = by_key(_analysis_stages(tasks, checkpoints, None))
    assert stages["facts"]["status"] == "running"
    assert stages["facts"]["finished_at"] is None
    assert stages["coaching"]["status"] == "waiting"
    assert stages["published"]["status"] == "waiting"


def test_a_stage_that_ended_badly_is_failed_until_a_later_stage_moves_on() -> None:
    checkpoints = {"C1": checkpoint(4), "C2": checkpoint(40), "C3": checkpoint(41)}
    failed = {"C4": [task("completed", 42, 60)], "C5": [task("uncertain", 61, 80)]}
    assert by_key(_analysis_stages(failed, checkpoints, None))["coaching"]["status"] == "failed"
    retried = {"C4": failed["C4"], "C5": [*failed["C5"], task("completed", 81, 99)]}
    saved = checkpoints | {"C5": checkpoint(99)}
    coaching = by_key(_analysis_stages(retried, saved, None))["coaching"]
    assert coaching["status"] == "done" and coaching["counts"]["attempts"] == 2


def test_nothing_started_waits_and_an_unpriced_model_costs_nothing_shown() -> None:
    stages = _analysis_stages({}, {}, None)
    assert {s["status"] for s in stages} == {"waiting"}
    odd = task("completed", 0, 5)
    odd["provider_receipt"] = {"provider": "nobody", "model": "unknown", "usage": {}}
    facts = by_key(_analysis_stages({"C4": [odd]}, {}, None))["facts"]
    assert facts["cost_inr"] is None and facts["counts"]["tokens_in"] is None
    assert by_key(_analysis_stages({"C4": [odd]}, {}, None))["alignment"]["status"] == "skipped"


def test_the_graph_links_every_new_stage_along_the_checkpoint_lineage() -> None:
    links = {(source, target) for source, target, _ in EDGES}
    for pair in [
        ("audio_check", "alignment"),
        ("transcription", "alignment"),
        ("alignment", "facts"),
        ("facts", "coaching"),
        ("coaching", "published"),
        ("published", "pointer_review"),
        ("coaching", "review"),
    ]:
        assert pair in links
    assert not any("report" in pair for pair in links)
