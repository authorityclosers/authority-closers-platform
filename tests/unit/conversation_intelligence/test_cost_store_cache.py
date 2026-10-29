"""Snapshots invalidate with source changes and never retain a live admin's names."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ac_platform.conversation_intelligence import cost_metrics as metrics


def write(root: Path, name: str = "exported") -> Path:
    path = root / "production" / "usage.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": metrics.SCHEMA,
                "companies": [{"id": "co", "name": name}],
                "calls": [{"id": "call", "at": "2026-10-29T00:00:00Z"}],
            }
        )
    )
    return path


def test_reuses_frozen_rows_but_never_admin_names(tmp_path, monkeypatch):
    metrics.clear_store_cache()
    write(tmp_path)
    original = metrics.parse_export
    calls = []

    def parse(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(metrics, "parse_export", parse)
    first, _ = metrics.read_store(str(tmp_path))
    first[0].companies["co"]["name"] = "private live name"
    first[0].people["person"] = "private person"
    second, _ = metrics.read_store(str(tmp_path))
    assert len(calls) == 1
    assert second[0].companies["co"]["name"] == "exported"
    assert second[0].people == {}
    assert first[0].calls is not second[0].calls
    assert first[0].calls[0] is second[0].calls[0]
    first[0].calls.clear()
    assert len(metrics.read_store(str(tmp_path))[0][0].calls) == 1


def test_invalidates_edit_replace_remove_and_repair(tmp_path):
    metrics.clear_store_cache()
    path = write(tmp_path)
    assert metrics.read_store(str(tmp_path))[0][0].companies["co"]["name"] == "exported"
    write(tmp_path, "updated")
    assert metrics.read_store(str(tmp_path))[0][0].companies["co"]["name"] == "updated"
    replacement = path.with_suffix(".new")
    replacement.write_text(path.read_text().replace("updated", "renamed"))
    replacement.replace(path)
    assert metrics.read_store(str(tmp_path))[0][0].companies["co"]["name"] == "renamed"
    path.unlink()
    assert metrics.read_store(str(tmp_path)) == ([], [])
    path.write_text("{")
    assert metrics.read_store(str(tmp_path))[1] == [
        {"environment": "production", "problem": "unreadable"}
    ]
    write(tmp_path)
    assert len(metrics.read_store(str(tmp_path))[0]) == 1


def test_concurrent_reads_parse_once_and_cache_is_bounded(tmp_path, monkeypatch):
    metrics.clear_store_cache()
    write(tmp_path)
    original = metrics.parse_export
    calls = []

    def parse(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(metrics, "parse_export", parse)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(metrics.read_store, [str(tmp_path)] * 20))
    assert len(calls) == 1
    assert all(len(exports) == 1 for exports, _ in results)
    for index in range(6):
        metrics.read_store(str(tmp_path / str(index)))
    assert len(metrics._STORE_CACHE) <= 4
