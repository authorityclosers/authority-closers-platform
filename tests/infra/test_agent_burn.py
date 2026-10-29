"""ac-agent-burn (30 Oct 2026): agent work per product and the server's CPU shares, counts
only, read back by Admin -> Economics."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

from ac_platform.economics import burn

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/metrics/ac-agent-burn"


def runner():
    loader = importlib.machinery.SourceFileLoader("ac_agent_burn", str(SCRIPT))
    spec = importlib.util.spec_from_loader("ac_agent_burn", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _claude(folder: Path, name: str, cwd: str, paths: list[str], output: int) -> Path:
    lines = [{"type": "user", "cwd": cwd, "message": {"content": "fictional prompt"}}]
    for path in paths:
        lines.append(
            {"type": "assistant", "message": {"content": [{"input": {"file_path": path}}]}}
        )
    lines.append(
        {
            "type": "assistant",
            "message": {
                "model": "fictional",
                "usage": {
                    "input_tokens": 100,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 1000,
                    "output_tokens": output,
                },
            },
        }
    )
    file = folder / f"{name}.jsonl"
    file.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return file


def _codex(folder: Path, name: str, cwd: str, path: str) -> Path:
    lines = [
        {"type": "session_meta", "payload": {"cwd": cwd}},
        {
            "type": "response_item",
            "payload": {"type": "custom_tool_call", "input": f"*** Update File: {path}"},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 2000,
                        "cached_input_tokens": 1000,
                        "output_tokens": 100,
                    }
                },
            },
        },
    ]
    file = folder / f"{name}.jsonl"
    file.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return file


def test_sessions_are_weighed_and_placed_by_what_they_touched(tmp_path: Path) -> None:
    job = runner()
    claude = tmp_path / "claude"
    claude.mkdir()
    _claude(claude, "a", "/home/acdev/src/x", ["apps/sales-xray-web/app/leads/page.tsx"], 10)
    _claude(
        claude,
        "b",
        "/home/acdev/src/x",
        ["infra/metrics/install.sh", "apps/admin-web/app/economics/view.tsx"],
        10,
    )
    _claude(claude, "c", "/home/acdev/work/pulse", ["apps/web/app/page.tsx"], 10)
    old = _claude(claude, "d", "/x", ["apps/sales-xray-web/a.tsx"], 10_000)
    stale = time.time() - 40 * 86_400
    os.utime(old, (stale, stale))
    areas = job.scan([str(claude)], "claude", days=30, now=time.time())
    weight = 100 + 0.1 * 1000 + 5 * 10  # each session
    assert areas == pytest.approx(
        {"sales_xray": 1.5 * weight, "ops": 0.5 * weight, "pulse_ea": weight}, abs=0.1
    )
    codex = tmp_path / "codex"
    codex.mkdir()
    _codex(codex, "e", "/home/acdev/src/x", "apps/learner-web/app/page.tsx")
    assert job.scan([str(codex)], "codex", days=30, now=time.time()) == {
        "learner": pytest.approx(1000 + 0.1 * 1000 + 8 * 100)
    }
    assert job.classify([], "/home/acdev/research") == {"unattributed": 1.0}


def test_cpu_shares_since_the_last_run(tmp_path: Path) -> None:
    job = runner()
    for name, usage in (
        (".", 1000),
        ("system.slice", 600),
        ("ac.slice", 50),
        ("user.slice", 250),
    ):
        folder = tmp_path / name
        folder.mkdir(exist_ok=True)
        (folder / "cpu.stat").write_text(f"usage_usec {usage}\nuser_usec 1\n", encoding="utf-8")
    now = job.cpu_now(tmp_path)
    assert now == {"total": 1000, "apps": 600, "agents": 300}
    assert job.cpu_shares(None, now) == {"apps": 0.6, "agents": 0.3, "other": 0.1}
    before = {"total": 500, "apps": 400, "agents": 50}
    assert job.cpu_shares(before, now) == {"apps": 0.4, "agents": 0.5, "other": 0.1}
    # A reboot resets the counters: count since boot.
    assert job.cpu_shares({"total": 5000, "apps": 1, "agents": 1}, now)["apps"] == 0.6
    assert job.cpu_shares(None, {"total": 0, "apps": 0, "agents": 0}) is None


def test_the_document_reads_back_and_holds_counts_only(tmp_path: Path) -> None:
    job = runner()
    extra = tmp_path / "agent-burn.d"
    extra.mkdir()
    (extra / "laptop.json").write_text(
        json.dumps(
            {"tool": "claude", "source": "laptop", "generated_at": "t", "areas": {"ops": 5}}
        ),
        encoding="utf-8",
    )
    (extra / "junk.json").write_text("{", encoding="utf-8")
    found = job.summaries(extra, now=time.time())
    assert [item["source"] for item in found] == ["laptop"]
    document = job.document(
        {"claude": {"sales_xray": 10.0, "ops": 5.0}, "codex": {}},
        {"claude": {"ac": "t", "laptop": "t"}},
        {"apps": 0.6, "agents": 0.3, "other": 0.1},
        days=30,
        generated="2026-10-30T00:00:00Z",
    )
    job.write_atomic(tmp_path / burn.FILE, document)
    assert oct((tmp_path / burn.FILE).stat().st_mode & 0o777) == oct(0o644)
    keys = burn.read(str(tmp_path))
    assert keys is not None
    assert keys["tokens"] == {"claude": {"sales_xray": 10.0, "ops": 5.0}}
    assert keys["sources"] == {"claude": {"ac": "t", "laptop": "t"}}
    assert keys["cpu"] == {"apps": 0.6, "agents": 0.3, "other": 0.1}
    text = (tmp_path / burn.FILE).read_text(encoding="utf-8")
    assert "fictional prompt" not in text and "apps/" not in text
