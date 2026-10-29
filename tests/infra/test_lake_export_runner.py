"""Exercise the production runner with fictional Parquet and a fake archive endpoint."""

from __future__ import annotations

import base64
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ac_platform.telemetry.lake import write_table

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "infra/application/scripts/ac-lake-export"


def runner():
    loader = importlib.machinery.SourceFileLoader("lake_runner", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def empty_export(tmp_path):
    from datetime import date

    for table in ("analytics_events", "lead_desk_events"):
        write_table(
            table,
            [],
            key=b"fictional-key-for-tests-only-12345",
            env="dev",
            day=date(2026, 10, 28),
            output=tmp_path,
        )


def test_default_off_and_invalid_environment_never_reads_credentials(monkeypatch, capsys):
    module = runner()
    monkeypatch.delenv("AC_LAKE_EXPORT_ENABLED", raising=False)
    credentials = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(module, "credentials", credentials)
    assert module.main(["production"]) == 0
    assert json.loads(capsys.readouterr().out)["disabled"]
    assert module.main(["not-an-environment"]) == 2
    credentials.assert_not_called()


def test_validates_every_table_before_upload_and_publishes_manifests_last(tmp_path, monkeypatch):
    module = runner()
    empty_export(tmp_path)
    uploaded = []
    monkeypatch.setattr(module, "upload", lambda path, key, env: uploaded.append(key))
    assert module.publish(tmp_path, "dev", "2026-10-28", {}) == 0
    assert len(uploaded) == 4
    assert all(key.endswith(".parquet") for key in uploaded[:2])
    assert all(key.endswith("/manifest.json") for key in uploaded[2:])
    # Content-addressed same keys on retry, with no deletion or listing.
    first = uploaded.copy()
    uploaded.clear()
    module.publish(tmp_path, "dev", "2026-10-28", {})
    assert uploaded == first
    uploaded.clear()
    next((tmp_path / "lead_desk_events").glob("*.parquet")).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        module.publish(tmp_path, "dev", "2026-10-28", {})
    assert uploaded == []


def test_failed_part_upload_never_publishes_a_manifest(tmp_path, monkeypatch):
    module = runner()
    empty_export(tmp_path)
    uploads = []

    def fail(path, key, env):
        uploads.append(key)
        raise RuntimeError("fictional upload failure")

    monkeypatch.setattr(module, "upload", fail)
    with pytest.raises(RuntimeError):
        module.publish(tmp_path, "dev", "2026-10-28", {})
    assert not any(key.endswith("manifest.json") for key in uploads)


def test_upload_verifies_s3_checksum_length_and_encryption(tmp_path, monkeypatch):
    module = runner()
    path = tmp_path / "part-fictional.parquet"
    path.write_bytes(b"fictional parquet bytes")
    checksum = base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode()
    metadata = {
        "ContentLength": path.stat().st_size,
        "ChecksumSHA256": checksum,
        "ServerSideEncryption": "AES256",
    }
    calls = []

    def aws(argv, env):
        calls.append(argv)
        return json.dumps(metadata) if "head-object" in argv else "{}"

    monkeypatch.setattr(module, "run", aws)
    module.upload(path, "lake/dev/example", {})
    assert "--checksum-sha256" in calls[0] and "AES256" in calls[0]
    assert "--checksum-mode" in calls[1]
    for name in metadata:
        original = metadata[name]
        metadata[name] = "wrong"
        with pytest.raises(ValueError):
            module.upload(path, "lake/dev/example", {})
        metadata[name] = original


def test_worker_errors_do_not_leak_credentials(monkeypatch, capsys):
    module = runner()
    monkeypatch.setenv("AC_LAKE_EXPORT_ENABLED", "1")
    monkeypatch.setattr(module, "credentials", Mock(side_effect=ValueError("FICTIONAL-SECRET")))
    status = Mock()
    monkeypatch.setattr(module, "reconciliation_status", status)
    assert module.main(["dev"]) == 1
    assert "FICTIONAL-SECRET" not in capsys.readouterr().err
    status.assert_called_once_with("dev", {"verified": False, "mismatch": True})


def test_timer_runs_nightly_low_priority_and_configuration_defaults_off():
    service = (ROOT / "infra/application/systemd/ac-lake-export@.service").read_text()
    timer = (ROOT / "infra/application/systemd/ac-lake-export@.timer").read_text()
    assert "Environment=AC_LAKE_EXPORT_ENABLED=0" in service
    assert "EnvironmentFile=-/etc/authority-closers/lake/%i.env" in service
    assert "Nice=19" in service and "IOSchedulingClass=idle" in service
    assert "OnCalendar=*-*-* 01:15:00 UTC" in timer
    assert "Persistent=true" in timer


def test_reconciliation_status_retains_counts_and_verification_time(tmp_path, monkeypatch):
    module = runner()
    real_path = Path
    monkeypatch.setattr(module, "Path", lambda _: real_path(tmp_path))
    (tmp_path / "production" / "telemetry" / "production").mkdir(parents=True)
    module.reconciliation_status(
        "production",
        {
            "postgres_rows": 2,
            "raw_rows": 8,
            "lake_rows": 2,
            "mismatch": True,
            "verified": True,
        },
    )
    status = json.loads(
        (tmp_path / "production" / "telemetry" / "production" / "reconciliation.json").read_text()
    )
    assert status["raw_rows"] == 8 and status["mismatch"]
    assert status["checked_at"] and status["verified"]
