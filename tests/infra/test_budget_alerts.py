"""AI budget alerts (19 Oct 2026): levels, one task per environment, Telegram only when worse."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "metrics" / "ac-budget-alerts"


def _alerts() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("ac_budget_alerts", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_budget_alerts", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_the_worst_level_that_applies_wins() -> None:
    alerts = _alerts()
    assert alerts.level_of(0.5, 0) is None
    assert alerts.level_of(0.8, 0) == "80"
    assert alerts.level_of(0.95, 0) == "90"
    assert alerts.level_of(1.0, 0) == "out"
    assert alerts.level_of(0.2, 3) == "waiting"


def test_an_alert_opens_once_gets_worse_with_one_line_and_closes_itself() -> None:
    alerts = _alerts()
    low = {"cap": 1_000_000, "used": 820_000, "share": 0.82, "waiting": 0}
    plan, lines, state = alerts.plan_alerts({}, {"production": low})
    assert [item["marker"] for item in plan["create"]] == ["ac-budget-alerts/production/80"]
    assert plan["move"] == [] and len(lines) == 1 and state == {"production": "80"}
    assert "82% used (production)" in plan["create"][0]["title"]
    assert "admin.authorityclosers.com/sales-xray/execution" in plan["create"][0]["notes"]

    # Unchanged: nothing to do, no second line.
    again, lines, _ = alerts.plan_alerts({"alerts": state}, {"production": low})
    assert again == {"create": [], "move": []} and lines == []

    # Worse: calls waiting. The old task closes, a new one opens, one line.
    waiting = {**low, "waiting": 2}
    plan, lines, state = alerts.plan_alerts({"alerts": state}, {"production": waiting})
    assert plan["move"][0]["marker"] == "ac-budget-alerts/production/80"
    assert plan["create"][0]["title"].startswith("2 Sales X-Ray calls are waiting")
    assert len(lines) == 1 and state == {"production": "waiting"}

    # Raised: back under 80% and nothing waits; the task closes, no line.
    fine = {"cap": 2_000_000, "used": 820_000, "share": 0.41, "waiting": 0}
    plan, lines, state = alerts.plan_alerts({"alerts": state}, {"production": fine})
    assert plan["create"] == [] and lines == [] and state == {}
    assert plan["move"] == [
        {
            "marker": "ac-budget-alerts/production/waiting",
            "note": "Back under 80% with no call waiting.",
        }
    ]


def test_it_reads_the_store(tmp_path: Path, monkeypatch) -> None:
    alerts = _alerts()
    (tmp_path / "production").mkdir()
    (tmp_path / "production" / "usage.json").write_text(
        json.dumps(
            {
                "budgets": [{"scope": "s", "cap_paise": 1_000_000, "committed_paise": 900_000}],
                "waiting_calls": 1,
                "ceiling_requests": [{"id": "r1", "requested_paise": 2_000_000}],
            }
        )
    )
    monkeypatch.setattr(alerts, "STORE", tmp_path)
    figures = alerts.read_env("production")
    assert figures["share"] == 0.9 and figures["waiting"] == 1
    assert [row["id"] for row in figures["requests"]] == ["r1"]
    assert alerts.read_env("staging") is None
