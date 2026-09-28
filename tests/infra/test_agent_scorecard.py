import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("scorecard", ROOT / "scripts/agent_scorecard.py")
scorecard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorecard)
FIXTURE = ROOT / "tests/infra/fixtures/agent_scorecard/week.json"


def report(source=None):
    monday, start, end = scorecard.week_window("2026-09-21")
    return scorecard.build_report(source or json.loads(FIXTURE.read_text()), monday, start, end)


def test_week_window_and_invalid_monday():
    monday, start, end = scorecard.week_window("2026-09-21")
    assert monday.isoformat() == "2026-09-21"
    assert scorecard.in_window(end - 1, start, end) and not scorecard.in_window(end, start, end)
    with pytest.raises(ValueError, match="Monday"):
        scorecard.week_window("2026-09-22")


def test_metrics_alerts_failures_and_markdown():
    result = report()
    agent = dict(result["rows"])["Fictional Agent"]
    assert (agent["done"], agent["bounces"], agent["failed_pct"]) == (2, 1, 50)
    assert agent["median"] == pytest.approx(5.5, abs=1e-4) and agent["p90"] > 3
    assert (agent["tokens"], agent["runs_per_task"]) == (209, 1.5)
    assert dict(result["rows"])["Company"] == agent
    assert any("failed runs" in a for a in result["alerts"])
    assert any("cycle-time p90" in a for a in result["alerts"])
    assert result["failures"] == [("Fictional Agent", "DEMO-2", "failed")]
    rendered = scorecard.render_report(result)
    assert "| Company | 2 |" in rendered and "DEMO-2" in rendered
    assert rendered.count("n/a (AUT-57)") == len(scorecard.GITHUB_COLUMNS) * len(result["rows"])


def test_monday_completion_is_excluded():
    source = json.loads(FIXTURE.read_text())
    source["activity"]["task-b"][-1]["createdAt"] = "2026-09-28T00:00:00Z"
    assert dict(report(source)["rows"])["Company"]["done"] == 1


def test_missing_usage_is_not_zero():
    source = json.loads(FIXTURE.read_text())
    source["runs"][0].pop("usageJson")
    assert dict(report(source)["rows"])["Company"]["tokens"] is None


def test_fetch_is_get_only(monkeypatch):
    monkeypatch.setenv("PAPERCLIP_API_URL", "https://paperclip.invalid")
    monkeypatch.setenv("PAPERCLIP_API_KEY", "fictional")
    with pytest.raises(ValueError, match="GET"):
        scorecard.fetch_json("/api/anything", method="POST")


def test_missing_env_names_only(monkeypatch, capsys):
    for key in ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY", "PAPERCLIP_COMPANY_ID"):
        monkeypatch.delenv(key, raising=False)
    assert scorecard.main(["--week", "2026-09-21"]) == 2
    error = capsys.readouterr().err
    assert all(key in error for key in (
        "PAPERCLIP_API_URL", "PAPERCLIP_API_KEY", "PAPERCLIP_COMPANY_ID"
    ))
    assert "fictional" not in error
