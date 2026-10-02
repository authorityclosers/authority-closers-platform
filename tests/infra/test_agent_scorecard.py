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
GITHUB_FIXTURE = ROOT / "tests/infra/fixtures/agent_scorecard/github.json"
SESSION_FIXTURE = ROOT / "tests/infra/fixtures/agent_scorecard/session_usage.json"


def report(source=None):
    monday, start, end = scorecard.week_window("2026-09-21")
    return scorecard.build_report(source or json.loads(FIXTURE.read_text()), monday, start, end)


def session_source(adapter):
    source = json.loads(SESSION_FIXTURE.read_text())
    source["agents"][0]["adapterType"] = adapter
    if adapter == "claude_local":
        source["runs"][0]["usageJson"]["inputTokens"] = 60
        source["runs"][2]["usageJson"]["inputTokens"] = 40
    return source


@pytest.mark.parametrize("adapter", ["codex_local", "claude_local"])
def test_reused_sessions_and_cross_task_history(adapter):
    source = session_source(adapter)
    source["runs"][2]["usageJson"] = json.dumps(source["runs"][2]["usageJson"])
    normalized = scorecard.normalize_runs(source["runs"], source["agents"])
    assert [r["_tokens"] for r in normalized][::2] == [65, 110]
    rows = dict(report(source)["rows"])
    assert rows["Fictional Builder"] == rows["Company"]
    assert (rows["Company"]["tokens"], rows["Company"]["runs_per_task"]) == (175, 2)
    assert "175.00" in scorecard.render_report(report(source))
    source["runs"][2]["contextSnapshot"]["issueId"] = "unfinished"
    rows = dict(report(source)["rows"])
    assert rows["Fictional Builder"] == rows["Company"]
    assert (rows["Company"]["tokens"], rows["Company"]["runs_per_task"]) == (65, 1)
    assert "65.00" in scorecard.render_report(report(source))


@pytest.mark.parametrize(
    "adapter,rotation,reset,cache_reset",
    [
        ("codex_local", 22, 4, 175),
        ("claude_local", 27, 6, 77),
    ],
)
def test_session_rotation_and_counter_resets(adapter, rotation, reset, cache_reset):
    source = session_source(adapter)
    usage = source["runs"][0]["usageJson"]
    for counters, session, expected in [
        ((20, 2, 5), "fictional-new", rotation),
        ((3, 1, 2), "fictional-shared", reset),
        ((usage["inputTokens"], 15, 2), "fictional-shared", cache_reset),
    ]:
        keys = ("inputTokens", "outputTokens", "cachedInputTokens")
        usage.update(zip(keys, counters, strict=True))
        usage["persistedSessionId"] = session
        assert scorecard.normalize_runs(source["runs"], source["agents"])[0]["_tokens"] == expected


@pytest.mark.parametrize(
    "adapter,delta,session,expected",
    [
        ("codex_local", True, "fictional-shared", 285),
        ("claude_local", True, "fictional-shared", 285),
        ("gemini_local", True, "fictional-shared", 63),
        ("codex_local", False, None, 285),
        ("claude_local", False, None, 285),
        ("unknown", False, "fictional-shared", 285),
    ],
)
def test_raw_usage_and_run_adapter_precedence(adapter, delta, session, expected):
    source = session_source(adapter)
    source["agents"][0]["adapterType"] = "claude_local"
    for run, counters in zip(source["runs"][::2], [(35, 5, 12), (20, 3, 7)], strict=True):
        run["adapterType"] = adapter
        usage = run["usageJson"]
        usage["persistedSessionId"] = session
        usage["usageSource"] = "session_delta" if delta else "per_run"
        if adapter == "gemini_local":
            keys = ("inputTokens", "outputTokens", "cachedInputTokens")
            usage.update(zip(keys, counters, strict=True))
    assert dict(report(source)["rows"])["Company"]["tokens"] == expected


@pytest.mark.parametrize("bad", [None, "{", [], {}, {"inputTokens": "bad", "outputTokens": 1}])
def test_invalid_snapshot_keeps_baseline_and_missing_cache_defaults_to_zero(bad):
    source = session_source("codex_local")
    for run in source["runs"]:
        run["usageJson"].pop("cachedInputTokens")
    source["runs"].insert(
        1,
        {
            **source["runs"][0],
            "id": "invalid",
            "startedAt": "2026-09-21T12:00:00Z",
            "usageJson": bad,
        },
    )
    row = dict(report(source)["rows"])["Company"]
    assert (row["tokens"], row["unreported_runs"]) == (175, 1)


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
    assert "209.00 (2 runs unreported)" in rendered and "n/a (GitHub unavailable)" in rendered


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
    calls = []
    monkeypatch.setattr(
        scorecard.subprocess,
        "run",
        lambda c, **_: calls.append(c) or type("R", (), {"returncode": 0, "stdout": "[]"})(),
    )
    assert scorecard.gh_api("repos/example/project/pulls", paginate=True) == [] and calls[0][
        2:4
    ] == ["--method", "GET"]


def github_report(monkeypatch, owner=True):
    source = json.loads(FIXTURE.read_text())
    responses = json.loads(GITHUB_FIXTURE.read_text())

    def fake_gh_api(path, paginate=False):
        assert path in responses, f"unexpected GitHub request: {path}"
        return responses[path] if paginate else responses[path][0]

    monkeypatch.setattr(scorecard, "gh_api", fake_gh_api)
    monday, start, end = scorecard.week_window("2026-09-21")
    source["github"] = scorecard.github_data(
        "example/project", start, end, "fictional-owner" if owner else None
    )
    return scorecard.build_report(source, monday, start, end)


def test_github_metrics_use_raw_api_data_and_task_branch_attribution(monkeypatch):
    result = github_report(monkeypatch)
    labels = [label for label, _ in result["rows"]]
    assert len(labels) == len(set(labels))
    rows = dict(result["rows"])
    assert rows["Software Engineer"]["done"] == 0
    admin, lead, platform, company = (
        rows[x]["github"]
        for x in ("Software Engineer", "Lead Engineer", "Platform Engineer", "Company")
    )

    assert [admin["cycles"], lead["cycles"], platform["cycles"], company["cycles"]] == [
        [2],
        [],
        [3],
        [2, 3],
    ]
    assert (
        admin["pass"],
        admin["total"],
        lead["pass"],
        lead["total"],
        company["pass"],
        company["total"],
    ) == (0, 1, 1, 1, 2, 5)
    assert (admin["rework"], lead["rework"], platform["rework"], company["rework"]) == (2, 1, 0, 7)
    assert (admin["owner"], platform["owner"], company["owner"]) == (2, 1, 4)
    assert (admin["scope"], platform["scope"], admin["evidence"], admin["gate"]) == (1, 0, 1, 1)
    assert (admin["bugs"], platform["bugs"], company["bugs"]) == (1, 1, 3)
    assert "UI Engineer" not in rows
    assert scorecard.github_cells(company)[:3] == ["2.50d", "3.00d", "40.0% (2/5)"]
    assert "PR cycle median" in scorecard.render_report(result)
    assert any("first-try CI" in alert and "<70%" in alert for alert in result["alerts"])
    assert "n/a (owner unset)" in scorecard.render_report(github_report(monkeypatch, owner=False))


def test_github_failures_list_first_ci_owner_request_and_post_merge_bugs(monkeypatch):
    failures = github_report(monkeypatch)["failures"]
    assert ("Software Engineer", "PR #101", "first-try CI failure") in failures
    assert ("Platform Engineer", "PR #103", "first-try CI failure") in failures
    assert ("Company", "PR #105", "first-try CI timed_out") in failures
    assert ("Software Engineer", "PR #101", "owner changes requested") in failures
    assert ("Software Engineer", "Issue #501", "post-merge bug: Fictional linked bug") in failures
    assert (
        "Platform Engineer",
        "Issue #503",
        "post-merge bug: Fictional hash-linked bug",
    ) in failures
    assert ("Company", "Commit abc1234", "post-merge bug: Revert fictional change") in failures
    assert not any("#502" in item[1] or "old1234" in item[1] for item in failures)
    assert not any(item[1] == "PR #107" for item in failures)


@pytest.mark.parametrize(
    "agent_name",
    [
        "Dev Environment Lead",
        "Dev Environment Lead · Claude (Opus 5.5)",
        "Dev Environment Lead · Sol",
    ],
)
def test_devenv_pr_metrics_use_real_agent_row_across_model_suffixes(agent_name):
    source = {
        "issues": [],
        "agents": [{"id": "fictional-devenv-agent", "name": agent_name}],
        "runs": [],
        "activity": {},
        "github": {
            "pull_requests": [
                {
                    "number": 108,
                    "branch": "task/devenv/108-fictional-fix",
                    "created_at": "2026-09-21T00:00:00Z",
                    "merged_at": "2026-09-23T00:00:00Z",
                    "first_try_ci": "failure",
                    "rework_pushes": 1,
                }
            ],
            "bugs": [],
            "reverts": [],
        },
    }
    result = report(source)
    rows = dict(result["rows"])
    assert [label for label, _ in result["rows"]] == [agent_name, "Company"]
    metrics = rows[agent_name]["github"]
    assert (metrics["cycles"], metrics["pass"], metrics["total"], metrics["rework"]) == (
        [2],
        0,
        1,
        1,
    )
    assert metrics == rows["Company"]["github"]
    assert result["failures"] == [("Dev Environment Lead", "PR #108", "first-try CI failure")]


def test_github_get_guard_rejects_write_methods_and_bodies():
    for flags in (
        ("-X", "POST"),
        ("--method", "PATCH"),
        ("--method=DELETE",),
        ("-f", "state=closed"),
        ("-F", "body=@file"),
        ("--field", "state=closed"),
        ("--field=state",),
        ("--raw-field", "body=@file"),
        ("--raw-field=body",),
        ("--input", "body.json"),
    ):
        with pytest.raises(ValueError):
            scorecard.validate_gh_command(["gh", "api", *flags, "repos/example/project/pulls"])
