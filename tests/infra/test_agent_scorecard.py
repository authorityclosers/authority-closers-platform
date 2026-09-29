import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("scorecard", ROOT / "scripts/agent_scorecard.py")
scorecard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorecard)
FIXTURE = ROOT / "tests/infra/fixtures/agent_scorecard/week.json"
BUILDER_FIXTURE = ROOT / "tests/infra/fixtures/agent_scorecard/builder_attribution.json"


def report(source=None):
    monday, start, end = scorecard.week_window("2026-09-21")
    return scorecard.build_report(source or json.loads(FIXTURE.read_text()), monday, start, end)


def test_real_activity_shapes_metrics_alerts_and_week_end():
    result = report()
    agent = dict(result["rows"])["Fictional Agent"]
    assert (agent["done"], agent["bounces"], agent["failed_pct"]) == (2, 3, 50)
    assert agent["median"] == pytest.approx(5.5, abs=1e-4) and agent["p90"] > 3
    assert (agent["tokens"], agent["unreported_runs"], agent["runs_per_task"]) == (209, 2, 2.5)
    assert dict(result["rows"])["Company"] == agent
    assert any("failed runs" in alert for alert in result["alerts"])
    assert any("cycle-time p90" in alert for alert in result["alerts"])
    rendered = scorecard.render_report(result)
    assert result["failures"][0] == ("Fictional Agent", "DEMO-2", "cancelled")
    assert result["failures"][1] == ("Fictional Agent", "DEMO-2", "failed")
    assert "209.00 (2 runs unreported)" in rendered and "n/a (AUT-57)" in rendered


def test_done_metrics_follow_builder_across_handoff_and_direct_completion():
    monday, start, end = scorecard.week_window("2026-09-21")
    source = json.loads(BUILDER_FIXTURE.read_text())
    rows = dict(scorecard.build_report(source, monday, start, end)["rows"])

    builder = rows["Fictional Builder A"]
    assert (builder["done"], builder["bounces"]) == (1, 1)
    assert (builder["tokens"], builder["unreported_runs"], builder["runs_per_task"]) == (400, 0, 2)
    assert builder["median"] == pytest.approx(6)
    assert rows["Fictional Reviewer B"]["done"] == 0
    assert rows["Fictional Reviewer B"]["bounces"] == 0
    assert rows["Fictional Approver C"]["done"] == 0
    assert rows["Fictional Approver C"]["bounces"] == 0
    assert rows["Fictional Direct Builder D"]["done"] == 1
    assert (rows["Company"]["done"], rows["Company"]["bounces"]) == (3, 1)


def test_reopen_after_first_done_does_not_change_builder():
    monday, start, end = scorecard.week_window("2026-09-21")
    source = json.loads(BUILDER_FIXTURE.read_text())
    rows = dict(scorecard.build_report(source, monday, start, end)["rows"])

    assert rows["Fictional Builder E"]["done"] == 1
    assert rows["Fictional Approver C"]["done"] == 0
    assert rows["Fictional Builder A"]["median"] == pytest.approx(6)


def test_monday_boundary_non_monday_and_no_usage():
    with pytest.raises(ValueError, match="Monday"):
        scorecard.week_window("2026-09-22")
    source = json.loads(FIXTURE.read_text())
    source["activity"]["task-b"][-1]["createdAt"] = "2026-09-28T00:00:00Z"
    assert dict(report(source)["rows"])["Company"]["done"] == 1
    source["runs"] = [{**run, "usageJson": None} for run in source["runs"]]
    assert dict(report(source)["rows"])["Company"]["tokens"] is None
    assert "n/a (no usage)" in scorecard.render_report(report(source))


def test_cycle_metrics_use_recorded_cycles_when_some_starts_are_missing():
    source = json.loads(FIXTURE.read_text())
    source["issues"][0].pop("startedAt")
    source["activity"]["task-a"] = [
        event for event in source["activity"]["task-a"] if event["type"] != "issue.checked_out"
    ]
    source["activity"]["task-a"][-1]["details"]["changes"]["status"].pop("from")
    agent = dict(report(source)["rows"])["Fictional Agent"]
    assert agent["median"] == pytest.approx(6, abs=1e-3)
    assert agent["p90"] == agent["median"] and agent["cycle_missing"] == 1


def test_issue_pagination_and_activity_filter(monkeypatch):
    calls = []
    old = [{"id": str(i), "updatedAt": "2026-09-20T00:00:00Z"} for i in range(1000)]
    fresh = {"id": "fresh", "updatedAt": "2026-09-21T00:00:00Z"}
    stale = {"id": "old", "updatedAt": "2026-09-20T23:59:59Z"}
    pages = [old, [fresh, stale]]

    def fake_fetch(path):
        calls.append(path)
        return pages[int("offset=1000" in path)] if "/issues?" in path else []

    monkeypatch.setattr(scorecard, "fetch_json", fake_fetch)
    _, start, _ = scorecard.week_window("2026-09-21")
    data = scorecard.fetch_report_data("company", start)
    assert len(data["issues"]) == 1002 and calls[1].endswith("offset=1000")
    assert calls[-1] == "/api/issues/fresh/activity"


def test_get_only_and_missing_env_names_only(monkeypatch, capsys):
    monkeypatch.setenv("PAPERCLIP_API_URL", "URL-SENTINEL")
    monkeypatch.setenv("PAPERCLIP_API_KEY", "KEY-SENTINEL")
    with pytest.raises(ValueError, match="GET"):
        scorecard.fetch_json("/api/anything", method="POST")
    monkeypatch.delenv("PAPERCLIP_COMPANY_ID", raising=False)
    assert scorecard.main(["--week", "2026-09-21"]) == 2
    error = capsys.readouterr().err
    assert error == "Missing required environment variable(s): PAPERCLIP_COMPANY_ID\n"
    assert "SENTINEL" not in error
