"""ac-bug-radar: radar groups become AC Pulse cards, close when fixed, never carry names."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-bug-radar"
SERVICE = ROOT / "infra/application/systemd/ac-bug-radar.service"
TIMER = ROOT / "infra/application/systemd/ac-bug-radar.timer"

# A fake ac-pulse-tasks: logs every request, answers ensure with a task per marker.
PULSE = """
import json, sys
request = json.loads(sys.stdin.read())
with open(sys.argv[0] + ".log", "a") as log:
    log.write(json.dumps(request) + "\\n")
results = []
for op in request["ops"]:
    if op["op"] == "ensure":
        results.append({"r": {"id": "task-" + op["marker"], "created": True, "parentId": None}})
    else:
        results.append({"r": {"ok": True}})
print(json.dumps({"results": results}))
"""


def _fake(path: Path, body: str) -> str:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    pulse = _fake(tmp_path / "pulse", PULSE)
    monkeypatch.setenv("AC_BUG_RADAR_PULSE", pulse)
    monkeypatch.setenv("AC_BUG_RADAR_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("AC_BUG_RADAR_SHIP_LOG", str(tmp_path / "ac-ship.log"))
    monkeypatch.setenv("AC_BUG_RADAR_GATE", str(tmp_path / "gate.json"))
    monkeypatch.setenv("AC_BUG_RADAR_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("AC_BUG_RADAR_AS_IS", "1")
    loader = importlib.machinery.SourceFileLoader("ac_bug_radar", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_bug_radar", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _requests(tmp_path: Path) -> list[dict]:
    log = tmp_path / "pulse.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _ops(tmp_path: Path, name: str) -> list[dict]:
    return [op for request in _requests(tmp_path) for op in request["ops"] if op["op"] == name]


def _group(
    gid: str, severity: str, check: str = "clipped-label", pages: tuple[str, ...] = ("leads-all",)
) -> dict:
    return {
        "id": gid,
        "key": f"{check} | div.leads-desk__tabs … button[role=tab]#{gid}",
        "check": check,
        "severity": severity,
        "pages": list(pages),
        "states": 3,
        "crop": f"crops/{gid}.jpg",
        "findings": [f"{check} | {pages[0]} | button#{gid}"],
    }


def _finding(gid: str, check: str = "clipped-label", page: str = "leads-all") -> dict:
    return {
        "key": f"{check} | {page} | button#{gid}",
        "check": check,
        "page": page,
        "path": "/review-fixture/leads?tab=all",
        "label": "Edit Asha Fictional's lead rules",
        "detail": '"All leads" ends in …: 38 of 61 px shown, plan ₹4,999',
        "where": ["320x640 130% text light", "360x800 130% text light"],
        "context": 'tap "Asha Fictional"',
    }


def _page(key: str, *, failed: bool = False, crawled: bool = True) -> dict:
    return {
        "key": key,
        "path": f"/review-fixture/{key}",
        "loads": 14,
        "failed": ["x"] if failed else [],
        "crawled": crawled,
    }


def _run(tmp_path: Path, name: str, groups: list[dict], pages: list[dict] | None = None) -> Path:
    folder = tmp_path / "runs" / name
    folder.mkdir(parents=True)
    findings = [_finding(g["id"], g["check"], g["pages"][0]) for g in groups]
    radar = {
        "schema": "wb-radar/1",
        "source_sha": "0123456789abcdef",
        "pages": pages or [_page("leads-all"), _page("leads-desk")],
        "findings": findings,
        "groups": groups,
    }
    (folder / "radar.json").write_text(json.dumps(radar))
    (folder / "report.md").write_text("### Bug radar\n")
    return folder


def test_units_run_nightly_on_development_only() -> None:
    assert "ExecStart=/usr/local/sbin/ac-bug-radar nightly" in SERVICE.read_text()
    assert "TimeoutStartSec=7h" in SERVICE.read_text()
    timer = TIMER.read_text()
    assert "OnCalendar=*-*-* 22:30:00 UTC" in timer and "Persistent=true" in timer
    assert os.access(SCRIPT, os.X_OK) or os.name == "nt"


def test_names_and_amounts_never_reach_a_card(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    radar = _load(monkeypatch, tmp_path)
    assert radar.names_out("Edit Asha Fictional's lead rules") == "Edit [name] lead rules"
    assert radar.names_out("All leads · Pro ₹4,999") == "All leads · Pro [amount]"
    group = _group("g1", "high")
    run = {
        "dir": "/var/lib/ac-bug-radar/runs/20261026T2230Z",
        "stamp": "20261026T2230Z",
        "sha": "0123456789abcdef",
    }
    title, notes = radar.card_text(
        group, {f["key"]: f for f in [_finding("g1")]}, {**run, "url": None}
    )
    assert title == "[dev] Radar: label cut short · leads-desk__tabs / button · 1 page"
    assert "Asha" not in notes and "Fictional" not in notes and "4,999" not in notes
    assert "Example: Edit [name] lead rules" in notes
    assert (
        "Fixture on dev: https://salesxray-dev.authorityclosers.com/review-fixture/leads?tab=all"
        in notes
    )
    assert "Crop on ac: /var/lib/ac-bug-radar/runs/20261026T2230Z/crops/g1.jpg" in notes
    assert notes.endswith("Marker: radar:g1")


def test_a_baseline_records_every_group_and_cards_only_the_first_to_fix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    radar = _load(monkeypatch, tmp_path)
    groups = [_group("a", "high"), _group("b", "medium"), _group("c", "medium"), _group("d", "low")]
    radar.ingest(_run(tmp_path, "20261026T2230Z", groups), baseline=True, cards=2, dry=False)
    ensured = [op["marker"] for op in _ops(tmp_path, "ensure")]
    assert ensured == ["radar:parent", "radar:a", "radar:b"]
    # The parent sits under HQ; each card under the parent.
    saves = {op["id"]: op["fields"].get("parentId") for op in _ops(tmp_path, "save")}
    assert saves["task-radar:parent"] == radar.HQ
    assert saves["task-radar:a"] == "task-radar:parent"
    state = json.loads((tmp_path / "state/state.json").read_text())
    assert {gid: g["status"] for gid, g in state["groups"].items()} == {
        "a": "open",
        "b": "open",
        "c": "known",
        "d": "known",
    }
    assert state["groups"]["a"]["task"] == "task-radar:a"
    assert state["runs"][-1]["cards"] == 2 and state["runs"][-1]["baseline"] is True


def test_a_later_run_cards_new_groups_and_closes_fixed_ones_only_where_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    radar = _load(monkeypatch, tmp_path)
    first = [
        _group("a", "high"),
        _group("b", "medium", pages=("leads-desk",)),
        _group("c", "medium"),
        _group("t", "high", check="tab-no-switch", pages=("hub-leads",)),
    ]
    pages = [_page("leads-all"), _page("leads-desk"), _page("hub-leads")]
    radar.ingest(_run(tmp_path, "r1", first, pages), baseline=True, cards=2, dry=False)
    (tmp_path / "pulse.log").unlink()
    # Night 2: a (carded) and c (known) are gone with their page checked; b's page failed; t's
    # page was not crawled; n is new and serious, l is new and low.
    later = [_group("n", "high", pages=("leads-all",)), _group("l", "low")]
    night = [
        _page("leads-all"),
        _page("leads-desk", failed=True),
        _page("hub-leads", crawled=False),
    ]
    summary = radar.ingest(_run(tmp_path, "r2", later, night), baseline=False, cards=10, dry=False)
    assert [op["marker"] for op in _ops(tmp_path, "close")] == ["radar:a"]
    assert [op["marker"] for op in _ops(tmp_path, "ensure")] == ["radar:n"]
    state = json.loads((tmp_path / "state/state.json").read_text())["groups"]
    assert state["a"]["status"] == "fixed" and state["c"]["status"] == "fixed"
    assert state["b"]["status"] == "open"  # its page failed: not known to be fixed
    assert state["t"]["status"] == "known"  # a tap check, page not crawled
    assert state["n"]["status"] == "open" and state["l"]["status"] == "known"
    assert summary["closed"] == 1 and summary["fixed_without_card"] == 1 and summary["cards"] == 1
    # Night 3: a comes back: its card reopens.
    (tmp_path / "pulse.log").unlink()
    radar.ingest(
        _run(tmp_path, "r3", [_group("a", "high"), *later], pages),
        baseline=False,
        cards=10,
        dry=False,
    )
    moves = _ops(tmp_path, "move")
    assert moves == [
        {"op": "move", "id": "task-radar:a", "status": "open", "note": "Came back in radar run r3."}
    ]
    assert json.loads((tmp_path / "state/state.json").read_text())["groups"]["a"]["came_back"] == 1


def test_a_night_cards_at_most_its_cap_and_the_rest_follow_later(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    radar = _load(monkeypatch, tmp_path)
    groups = [_group(f"g{i:02}", "medium") for i in range(12)]
    radar.ingest(_run(tmp_path, "r1", groups), baseline=False, cards=10, dry=False)
    assert len([op for op in _ops(tmp_path, "ensure") if op["marker"] != "radar:parent"]) == 10
    [comment] = _ops(tmp_path, "comment")
    assert comment["taskId"] == "task-radar:parent"
    assert "2 more new groups wait for a card" in comment["body"] and "radar:g10" in comment["body"]
    state = json.loads((tmp_path / "state/state.json").read_text())["groups"]
    assert state["g11"]["status"] == "waiting"
    (tmp_path / "pulse.log").unlink()
    radar.ingest(_run(tmp_path, "r2", groups), baseline=False, cards=10, dry=False)
    assert [op["marker"] for op in _ops(tmp_path, "ensure")] == ["radar:g10", "radar:g11"]


def test_a_dry_run_changes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    radar = _load(monkeypatch, tmp_path)
    radar.ingest(_run(tmp_path, "r1", [_group("a", "high")]), baseline=False, cards=10, dry=True)
    assert all(request["dry"] for request in _requests(tmp_path))
    assert not (tmp_path / "state/state.json").exists()
    assert '"card": "radar:a"' in capsys.readouterr().out


def test_waits_while_a_release_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    radar = _load(monkeypatch, tmp_path)
    log = tmp_path / "ac-ship.log"
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    started = f"{at} === ship v0.99.0 (the lead sheet)\n"
    log.write_text(f"2026-10-26T16:10:21Z === cut v0.98.0 from workbench x\n{started}")
    assert "still open" in (radar.ship_busy() or "")
    log.write_text(f"{started}{at} === ship v0.99.0 done\n")
    assert radar.ship_busy() is None
    log.write_text("2026-10-01T10:00:00Z === ship v0.40.0 (old, never finished)\n")
    assert radar.ship_busy() is None


def test_a_release_hold_lists_groups_the_baseline_does_not_know(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    radar = _load(monkeypatch, tmp_path)
    radar.ingest(_run(tmp_path, "r1", [_group("a", "high")]), baseline=True, cards=1, dry=False)
    # The release's run: a is known, n is new and high.
    built = _run(tmp_path, "built", [_group("a", "high"), _group("n", "high")])
    wb_ci = _fake(
        tmp_path / "wb-ci", "print('wb-ci: run https://github.com/o/r/actions/runs/4242')"
    )
    gh = _fake(
        tmp_path / "gh",
        f"import shutil, sys\nshutil.copytree({str(built)!r}, sys.argv[sys.argv.index('-D') + 1])",
    )
    monkeypatch.setattr(radar, "WB_CI", wb_ci)
    monkeypatch.setattr(radar, "GH", gh)
    capsys.readouterr()
    assert radar.main(["check", "--sha", "0123456789abcdef"]) == 1
    out = capsys.readouterr().out
    assert "1 not in the nightly baseline" in out
    assert "radar:n" in out and "radar:a" not in out
    # No cards and no state from a hold.
    assert [op["marker"] for op in _ops(tmp_path, "ensure")] == ["radar:parent", "radar:a"]


def test_the_ai_review_needs_the_subscription_gate_and_files_findings_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    radar = _load(monkeypatch, tmp_path)
    run = _run(tmp_path, "r1", [_group("a", "high")])
    (run / "pages").mkdir()
    for key in ("home", "leads-all", "settings"):
        (run / "pages" / f"{key}.jpg").write_bytes(b"jpg")
    calls = tmp_path / "claude.log"
    answer = {
        "findings": [
            {
                "problem": "Asha Fictional row crowds the chips",
                "where": "list",
                "severity": "medium",
                "rule": "rows",
            }
        ]
    }
    claude = _fake(
        tmp_path / "claude",
        f"import sys\nopen({str(calls)!r}, 'a').write(sys.argv[-1] + '\\n')\n"
        f"print('Here: ' + {json.dumps(answer)!r})",
    )
    monkeypatch.setattr(radar, "CLAUDE", claude)
    state = {"parent": "task-radar:parent"}
    closed = {"claude_ok": False, "reason": "weekly ahead of pace"}
    (tmp_path / "gate.json").write_text(json.dumps(closed))
    assert radar.ai_review(run, 2, state, dry=False) == []
    assert "gate is closed (weekly ahead of pace)" in capsys.readouterr().out and not calls.exists()
    (tmp_path / "gate.json").write_text(json.dumps({"claude_ok": True}))
    found = radar.ai_review(run, 2, state, dry=False)
    assert [f["page"] for f in found] == ["home", "leads-all"]
    assert found[0]["problem"] == "[name] row crowds the chips"
    assert "sales-xray-ux/SKILL.md" in calls.read_text()
    assert state["ai_cursor"] == 2
    assert "#### AI review (Claude subscription, 2 pages" in (run / "report.md").read_text()
    [comment] = _ops(tmp_path, "comment")
    assert "findings only, no cards" in comment["body"] and "Asha" not in comment["body"]
