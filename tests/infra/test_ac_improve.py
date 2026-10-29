"""Fictional metrics, missing coverage, privacy and HQ idempotency."""

import datetime as dt
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra/application/scripts/ac-improve"
loader = importlib.machinery.SourceFileLoader("ac_improve", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
NOW = dt.datetime(2026, 10, 29, tzinfo=dt.UTC)


def row(event, **fields):
    return {
        "event_name": event,
        "occurred_at": NOW,
        "retention_expires_at": NOW + dt.timedelta(days=10),
        "tenant_ref": "tenant",
        "subject_ref": "subject",
        **fields,
    }


def measure(rows):
    return m.metrics(rows, NOW, NOW + dt.timedelta(days=1), NOW)


def test_percentile_interpolation_and_band_discrete():
    assert m.percentile([0, 100, 200, 300], 0.5) == 150
    assert m.percentile([0, 100], 0.95) == 95
    assert m.percentile([0, 100], 0.99) == 99
    assert m.discrete([0, 100], 0.95) == 100
    assert m.percentile([], 0.95) is None
    assert m.ratio(1, 0) is None
    assert m.ratio(3, 200, 1000) == 15


def test_privacy_expiry_group_suppression_and_correct_denominators():
    rows = [
        row("sx.route_timing", ms=100 * i, screen="home", subject_ref=str(i)) for i in range(1, 4)
    ]
    rows += [row("sx.route_timing", ms=99999, screen="report")]
    rows += [
        row("sx.api_timing", status=status, band="100_300", screen="home", subject_ref=str(i))
        for i, status in enumerate(["2xx", "2xx", "5xx"])
    ]
    rows += [
        row("sx.screen_viewed"),
        row("sx.js_error"),
        row("sx.js_error", retention_expires_at=NOW),
    ]
    result = measure(rows)
    assert result["sx.route_timing:home:route:p50_ms"] == 200
    assert result["sx.route_timing:home:route:p95_ms"] == 290
    assert result["api_band_lower:home:p95_ms"] == 100
    assert result["api_errors_per_1000_observed_requests"] == pytest.approx(1000 / 3)
    assert result["js_errors_per_1000_screen_views"] == 1000
    assert not any("report" in k for k in result)
    assert "subject" not in json.dumps(result)
    with pytest.raises(ValueError, match="enum"):
        measure([row("sx.route_timing", screen="a personal name", ms=1)])
    with pytest.raises(ValueError, match="number"):
        measure([row("sx.route_timing", screen="home", ms=float("nan"))])


def test_delta_zero_baseline_is_not_infinite():
    result = m.deltas({"x": 10, "missing": None}, {"x": 0, "missing": 2})
    assert result["x"] == {"before": 0, "after": 10, "delta": 10, "percent": None}
    assert result["missing"]["delta"] is None


def test_recovery_requires_measured_samples_and_material_gain():
    key = "api_route:/v1/calls:p95_ms"
    assert (
        m.recovered(
            {key: 800, "api_route:/v1/calls:n": 20}, {key: 2000, "api_route:/v1/calls:n": 30}, "dev"
        )[0]["after_ms"]
        == 800
    )
    assert m.recovered({key: None}, {key: 2000}, "dev") == []
    assert m.recovered({key: 800}, {key: 2000}, "dev") == []


def test_cost_and_prune_evidence_and_release_regressions(tmp_path):
    path = tmp_path / "aggregate.json"
    path.write_text(
        json.dumps(
            {
                "start": "2026-10-28",
                "end_exclusive": "2026-10-30",
                "spend_inr": 120,
                "analysed_minutes": 40,
                "active_sellers": 3,
                "cpu_ms": 500,
                "requests": 100,
                "errors": 2,
                "features": [{"screen": "coaching", "uses": 0, "exposures": 100}],
                "api_routes": [{"route": "/v1/calls/{id}", "latency_ms": [100, 2000]}],
                "release_comparisons": [
                    {"release": "v1.6.0", "metric": "api_pxx_ms", "before": 100, "after": 150}
                ],
            }
        )
    )
    values, _ = m.supplemental(path, dt.date(2026, 10, 28), dt.date(2026, 10, 30))
    assert values["inr_per_analysed_minute"] == 3
    assert values["inr_per_active_seller"] == 40
    assert values["cpu_ms_per_request"] == 5
    assert values["server_errors_per_1000_requests"] == 20
    findings = m.rank_findings(values, {}, "production")
    assert {"prune", "speed", "quality"} <= {f["tag"] for f in findings}
    assert m.rank_findings({"feature_used_events": 0}, {}, "dev") == []
    assert findings == sorted(findings, key=lambda f: (-f["rank"], f["key"]))


def test_manifest_missing_is_not_empty_and_orphans_are_not_read(tmp_path):
    pytest.importorskip("duckdb")
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    folder = tmp_path / "dev/analytics_events/dt=2026-10-28"
    folder.mkdir(parents=True)
    pq.write_table(pa.table({"event_name": ["sx.tap"]}), folder / "part.parquet")
    (folder / "orphan.parquet").write_bytes(b"not parquet")
    digest = hashlib.sha256((folder / "part.parquet").read_bytes()).hexdigest()
    manifest = {
        "schema": "ac-lake-manifest/1",
        "environment": "dev",
        "table": "analytics_events",
        "day": "2026-10-28",
        "rows": 1,
        "parts": [{"key": "lake/dev/part.parquet", "sha256": digest}],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    rows, coverage = m.load_lake(tmp_path, "dev", dt.date(2026, 10, 28), dt.date(2026, 10, 29))
    assert len(rows) == 1
    assert coverage[0]["available"] is True
    assert coverage[1]["available"] is False
    (folder / "part.parquet").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        m.load_lake(tmp_path, "dev", dt.date(2026, 10, 28), dt.date(2026, 10, 29))


def test_hq_updates_existing_task_parent_and_records_ids(tmp_path, monkeypatch):
    calls = []

    def fake(command, op, args):
        calls.append((op, args))
        return [{"id": "mp16"}] if op == "find" else {"id": "existing", "created": False}

    monkeypatch.setattr(m, "hq", fake)
    path = tmp_path / "state.json"
    f = m.finding("dev:test", "quality", "Test", 1, 0.5, 2, {"now": 3}, "Reduce errors")
    for _ in range(2):
        m.sync_hq(
            "unused", [f], path, [{"key": "dev:recovered", "before_ms": 2000, "after_ms": 500}]
        )
    assert json.loads(path.read_text())["orch:improve:dev:test"] == {
        "id": "existing",
        "parentId": "mp16",
    }
    assert all(a["fields"]["parentId"] == "mp16" for op, a in calls if op == "save")
    assert sum(op == "ensure" for op, _ in calls) == 2
    assert "before_ms" in next(a for op, a in calls if op == "close")["note"]


def test_route_bands_are_not_exact_latencies_and_never_auto_close():
    result = measure(
        [
            row("sx.route_timing", screen="home", band="1000_3000", subject_ref=str(i))
            for i in range(3)
        ]
    )
    assert result["screen_route_band_lower:home:p95_ms"] == 1000
    assert "sx.route_timing:home:route:p95_ms" not in result
    key = "screen_route_band_lower:home:p95_ms"
    assert (
        m.recovered(
            {key: 300, "screen_route_band_lower:home:n": 100},
            {key: 3000, "screen_route_band_lower:home:n": 100},
            "dev",
        )
        == []
    )


def test_journeys_pair_in_order_and_cancel_does_not_complete():
    rows = []
    for i in range(3):
        rows += [
            row("sx.flow", flow="onboarding", outcome="start", subject_ref=str(i), session_ref="s"),
            row(
                "sx.flow",
                flow="onboarding",
                outcome="done",
                subject_ref=str(i),
                session_ref="s",
                occurred_at=NOW + dt.timedelta(seconds=i + 1),
            ),
        ]
    rows += [
        row("sx.flow", flow="add_lead", outcome="start", session_ref="s"),
        row(
            "sx.flow",
            flow="add_lead",
            outcome="abandon",
            session_ref="s",
            occurred_at=NOW + dt.timedelta(seconds=1),
        ),
        row(
            "sx.flow",
            flow="add_lead",
            outcome="done",
            session_ref="s",
            occurred_at=NOW + dt.timedelta(seconds=2),
        ),
    ]
    result = measure(rows)
    assert result["journey:onboarding:p50_ms"] == 2000
    assert result["journey:onboarding:p95_ms"] == 2900
    assert result["flow:add_lead:explicit_abandons"] == 1
    assert "journey:add_lead:p50_ms" not in result


def test_ideas_requires_subscription_auth_before_any_exec(monkeypatch):
    class Result:
        returncode = 0
        stdout = b"Logged in using API key"
        stderr = b""

    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: Result())
    with pytest.raises(RuntimeError, match="subscription"):
        m.ideas_step([])


def test_missing_lake_cli_writes_unknowns_and_seed_is_labelled(tmp_path, monkeypatch):
    pytest.importorskip("duckdb")
    output = tmp_path / "out"
    monkeypatch.setattr(
        m.os.sys,
        "argv",
        [
            str(SCRIPT),
            "--lake-dir",
            str(tmp_path / "missing"),
            "--env",
            "production",
            "--start",
            "2026-10-28",
            "--end-exclusive",
            "2026-10-30",
            "--output",
            str(output),
            "--seed-api-freeze",
        ],
    )
    m.main()
    report = json.loads((output / "production-2026-10-28-2026-10-30.json").read_text())
    assert report["current_complete"] is False
    assert report["baseline_complete"] is False
    assert all(v is None for v in report["metrics"].values())
    assert all(v["delta"] is None for v in report["deltas"].values())
    assert report["findings"][0]["evidence"]["approx_blocked_ms"] == 5000
    assert "not lake measurement" in report["findings"][0]["evidence"]["source"]
    assert len(report["coverage"]) == 8  # two tables, two days, two disjoint windows
    assert report["improved"] == []
