import base64
import hashlib
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "infra/application/scripts/ac-telemetry-raw"


def journal(root):
    path = root / "2026-10-28T20-api-001.ndjson"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "occurred_at": "2026-10-28T20:00:00Z",
                        "event_id": "fixed-event",
                        "tenant_id": "tenant",
                    }
                ]
            }
        )
        + "\n"
    )
    return path


def test_ship_verifies_before_delete_and_leaves_count_receipt(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    path = journal(tmp_path)
    visited = []

    def upload(compressed, key, env):
        assert path.exists()
        assert compressed.exists()
        assert key == "lake/raw/production/analytics/dt=2026-10-28/20-api-001.ndjson.gz"
        visited.append(key)

    monkeypatch.setitem(module["ship"].__globals__, "upload", upload)
    assert module["ship"](tmp_path, "production", {}, now=datetime(2026, 10, 29, tzinfo=UTC)) == 1
    assert visited
    assert not path.exists()
    assert not list(tmp_path.glob("*.gz"))
    assert json.loads(path.with_suffix(".receipt").read_text())["days"] == {
        "2026-10-28": ["tenant:fixed-event"]
    }


def test_failure_keeps_original(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    path = journal(tmp_path)

    def fail(*_):
        raise RuntimeError("remote mismatch")

    monkeypatch.setitem(module["ship"].__globals__, "upload", fail)
    with pytest.raises(RuntimeError):
        module["ship"](tmp_path, "production", {})
    assert path.exists()
    assert not list(tmp_path.glob("*.receipt"))


@pytest.mark.parametrize("wrong", ["size", "checksum"])
def test_upload_requires_remote_size_and_checksum(tmp_path, monkeypatch, wrong):
    module = runpy.run_path(str(SCRIPT))
    path = tmp_path / "closed.gz"
    path.write_bytes(b"archive")
    digest = base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode()

    def run(argv, env):
        return json.dumps(
            {
                "ContentLength": 0 if wrong == "size" else path.stat().st_size,
                "ChecksumSHA256": "wrong" if wrong == "checksum" else digest,
                "ServerSideEncryption": "AES256",
            }
        )

    monkeypatch.setitem(module["upload"].__globals__, "run", run)
    with pytest.raises(RuntimeError):
        module["upload"](path, "lake/raw/key", {})
    assert path.exists()


def test_hour_rotation_recovers_only_an_unacknowledged_fragment(tmp_path, monkeypatch):
    module = runpy.run_path(str(SCRIPT))
    original = journal(tmp_path)
    opened = original.with_suffix(".open")
    original.rename(opened)
    with opened.open("ab") as handle:
        handle.write(b'{"unacknowledged":')
    verified = []

    def upload(path, key, env):
        import gzip

        with gzip.open(path, "rt") as handle:
            verified.extend(json.loads(line) for line in handle)

    monkeypatch.setitem(module["ship"].__globals__, "upload", upload)
    module["ship"](tmp_path, "production", {}, now=datetime(2026, 10, 29, tzinfo=UTC))
    assert len(verified) == 1
    assert verified[0]["events"][0]["event_id"] == "fixed-event"


def test_shipper_cannot_create_a_root_owned_journal_before_api_initializes_it(tmp_path):
    module = runpy.run_path(str(SCRIPT))
    missing = tmp_path / "not-initialized"
    assert module["ship"](missing, "production", {}) == 0
    assert not missing.exists()
