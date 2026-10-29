"""The improvement engine's lake fetch helper (orchestrator, 29 Oct 2026)."""

from __future__ import annotations

import datetime
import hashlib
import json
import runpy
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-improve-fetch"
DROP_IN = ROOT / "infra/application/systemd/ac-improve.service.d/50-fetch-lake.conf"
DAY = datetime.date(2026, 10, 28)


def load(tmp_path: Path, bucket: dict[str, bytes]) -> tuple[Callable[..., dict], list[str]]:
    """Return fetch(environment, table, day) over a fake bucket, and the downloads it made."""
    module = runpy.run_path(str(SCRIPT))
    calls: list[str] = []

    def fake_get(key: str, target: Path, env: dict[str, str]) -> bool:
        calls.append(key)
        if key not in bucket:
            return False
        target.write_bytes(bucket[key])
        return True

    globals_ = module["fetch_day"].__globals__
    globals_["get"] = fake_get
    globals_["DEST"] = tmp_path / "lake"
    manifests = {
        key: hashlib.md5(value, usedforsecurity=False).hexdigest()
        for key, value in bucket.items()
        if key.endswith("/manifest.json")
    }

    def fetch(environment: str, table: str, day: datetime.date) -> dict:
        return module["fetch_day"](environment, table, day, manifests, {}, None)

    return fetch, calls


def lake_day(
    environment: str, table: str, day: str, parquet: bytes, override: dict | None = None
) -> dict[str, bytes]:
    prefix = f"lake/{environment}/{table}/dt={day}/"
    part = {
        "key": prefix + "part-0001.parquet",
        "rows": 3,
        "sha256": hashlib.sha256(parquet).hexdigest(),
    }
    manifest = {
        "environment": environment,
        "table": table,
        "day": day,
        "rows": 3,
        "parts": [part],
        **(override or {}),
    }
    return {prefix + "manifest.json": json.dumps(manifest).encode(), part["key"]: parquet}


def test_default_window_is_the_engine_week_and_its_baseline() -> None:
    window = runpy.run_path(str(SCRIPT))["window"]
    environment, first, last = window(["production"], datetime.date(2026, 11, 2))
    assert environment == "production"
    assert (first, last) == (datetime.date(2026, 10, 18), datetime.date(2026, 11, 1))


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["prod"],
        ["dev", "2026-10-28"],
        ["dev", "2026-10-29", "2026-10-28"],
        ["dev", "2026-01-01", "2026-10-28"],
    ],
)
def test_refuses_unknown_environments_and_bad_windows(argv: list[str]) -> None:
    window = runpy.run_path(str(SCRIPT))["window"]
    with pytest.raises(SystemExit):
        window(argv, datetime.date(2026, 10, 29))


def test_copies_the_manifest_and_exactly_its_verified_parts(tmp_path: Path) -> None:
    bucket = lake_day("dev", "analytics_events", "2026-10-28", b"PAR1 rows")
    bucket["lake/dev/analytics_events/dt=2026-10-28/part-orphan.parquet"] = b"orphan"
    fetch, calls = load(tmp_path, bucket)
    result = fetch("dev", "analytics_events", DAY)
    folder = tmp_path / "lake/dev/analytics_events/dt=2026-10-28"
    assert result == {"table": "analytics_events", "day": "2026-10-28", "rows": 3, "parts": 1}
    assert sorted(p.name for p in folder.iterdir()) == ["manifest.json", "part-0001.parquet"]
    assert oct(folder.stat().st_mode & 0o777) == "0o750"
    assert oct((folder / "part-0001.parquet").stat().st_mode & 0o777) == "0o640"
    # A second run finds the same manifest and verified parts locally: no download at all.
    calls.clear()
    assert fetch("dev", "analytics_events", DAY) == result
    assert calls == []


def test_a_changed_manifest_is_downloaded_again(tmp_path: Path) -> None:
    bucket = lake_day("dev", "analytics_events", "2026-10-28", b"PAR1 rows")
    fetch, calls = load(tmp_path, bucket)
    fetch("dev", "analytics_events", DAY)
    folder = tmp_path / "lake/dev/analytics_events/dt=2026-10-28"
    (folder / "manifest.json").write_text("{}")
    calls.clear()
    fetch("dev", "analytics_events", DAY)
    assert calls == ["lake/dev/analytics_events/dt=2026-10-28/manifest.json"]


def test_a_missing_manifest_stays_unknown_and_leaves_no_file(tmp_path: Path) -> None:
    fetch, calls = load(tmp_path, {})
    result = fetch("production", "lead_desk_events", datetime.date(2026, 10, 29))
    assert result == {"table": "lead_desk_events", "day": "2026-10-29", "manifest": "missing"}
    assert not list((tmp_path / "lake/production/lead_desk_events/dt=2026-10-29").iterdir())
    assert calls == []


def test_refuses_a_part_whose_checksum_does_not_match(tmp_path: Path) -> None:
    bucket = lake_day("dev", "analytics_events", "2026-10-28", b"PAR1 rows")
    bucket["lake/dev/analytics_events/dt=2026-10-28/part-0001.parquet"] = b"tampered"
    fetch, _ = load(tmp_path, bucket)
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch("dev", "analytics_events", DAY)


@pytest.mark.parametrize(
    "override",
    [{"environment": "production"}, {"table": "lead_desk_events"}, {"day": "2026-10-27"}],
)
def test_refuses_a_manifest_for_another_environment_table_or_day(
    tmp_path: Path, override: dict
) -> None:
    fetch, _ = load(tmp_path, lake_day("dev", "analytics_events", "2026-10-28", b"PAR1", override))
    with pytest.raises(ValueError, match="manifest mismatch"):
        fetch("dev", "analytics_events", DAY)


def test_refuses_a_part_outside_its_day_folder(tmp_path: Path) -> None:
    bucket = lake_day("dev", "analytics_events", "2026-10-28", b"PAR1")
    manifest_key = "lake/dev/analytics_events/dt=2026-10-28/manifest.json"
    manifest = json.loads(bucket[manifest_key])
    manifest["parts"][0]["key"] = "lake/dev/analytics_events/dt=2026-10-28/../escape.parquet"
    bucket[manifest_key] = json.dumps(manifest).encode()
    fetch, _ = load(tmp_path, bucket)
    with pytest.raises(ValueError, match="invalid lake part path"):
        fetch("dev", "analytics_events", DAY)


def test_the_service_fetches_both_environments_as_root_before_the_engine() -> None:
    text = DROP_IN.read_text()
    assert "ExecStartPre=+/usr/local/sbin/ac-improve-fetch production" in text
    assert "ExecStartPre=+/usr/local/sbin/ac-improve-fetch dev" in text
    assert "TimeoutStartSec=30min" in text
