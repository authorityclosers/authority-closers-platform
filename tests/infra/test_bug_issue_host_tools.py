"""v0.93 host tools: the release timer pairs each "live on production" line with the hold line
before it, and the Pulse alert's task carries the screen, count and link, never words."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[2] / "infra/application/scripts"


def load(name: str) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(SCRIPTS / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_each_live_release_takes_the_hold_line_before_it() -> None:
    release = load("ac-bugs-release")
    lines = [
        "2026-10-25T08:55:03Z hold 6815dc2b2c79b18af0be145df3972a9bbf932f86"
        " (workbench 2e1970d86 over main 153b1aa2e)",
        "2026-10-25T10:24:57Z v0.90.0 is live on production and its canary passed: https://x",
        "2026-10-25T10:24:57Z v0.90.0 is live on production and its canary passed: https://x",
        "2026-10-25T15:00:05Z hold c197101f1d68afa0e280ded1c39758b5979c3a6b"
        " (workbench 3ba4464ba over main d279b04ad)",
        "2026-10-25T16:00:00Z something else",
        "2026-10-25T16:38:38Z v0.91.0 is live on production and its canary passed: https://x",
    ]
    assert release.releases(lines) == [("v0.90.0", "2e1970d86"), ("v0.91.0", "3ba4464ba")]
    assert release.releases(["2026-10-25T16:38:38Z v0.91.0 is live on production"]) == []


def test_a_pulse_task_names_the_screen_and_count_never_the_words() -> None:
    alerts = load("ac-bug-alerts")
    title, notes = alerts.task_text(
        "production",
        {
            "id": "6d1c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a",
            "number": 4,
            "screen": "/leads",
            "area": "leads",
            "status": "new",
            "count": 3,
            "came_back": True,
            "first_seen": "2026-10-25T13:15:00+00:00",
            "last_seen": "2026-10-26T04:30:00+00:00",
            "orgs": 1,
            "devices": {"CPH2793": 2, "IV2201": 1},
            "android": {"Android 16": 2},
        },
    )
    assert title == "Bug 4: /leads · 3 reports · came back after the fix"
    assert "https://admin.authorityclosers.com/bugs?issue=4" in notes
    assert "Marker: bug:6d1c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a" in notes
    assert "CPH2793 (2)" in notes
