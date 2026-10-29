from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.telemetry import durable


def event() -> SimpleNamespace:
    values = dict.fromkeys(durable.FIELDS)
    values.update(
        event_id=str(uuid4()),
        occurred_at=datetime.now(UTC),
        event_name="sx.section_read",
        tenant_id=uuid4(),
        actor_person_id=uuid4(),
        subject_person_id=uuid4(),
        payload={"section": "analysis", "read_band": "5_30s"},
    )
    return SimpleNamespace(
        **values, name="never serialize", email="never@example.test", typed_text="private content"
    )


def test_append_fsync_hour_rotation_and_fixed_fields(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(UTC).replace(minute=0)
    seen = []
    real = durable.os.fsync
    monkeypatch.setattr(durable.os, "fsync", lambda fd: (seen.append(fd), real(fd))[1])
    first = durable.append(tmp_path, [event()], now=now)
    second = durable.append(tmp_path, [event()], now=now + timedelta(hours=1))
    assert first != second
    assert len(list(tmp_path.glob("*.ndjson"))) == 1
    assert len(list(tmp_path.glob("*.open"))) == 1
    assert len(seen) >= 6
    text = "".join(p.read_text() for p in tmp_path.glob("*.ndjson"))
    assert "private content" not in text and "never@example" not in text and '"name"' not in text
    import json

    assert set(json.loads(text)["events"][0]) == set(durable.FIELDS)


def test_capacity_is_true_intake_outage_and_preserves_previous_data(tmp_path: Path) -> None:
    durable.append(tmp_path, [event()])
    original = next(tmp_path.glob("*.open")).read_bytes()
    with pytest.raises(durable.SpoolUnavailable):
        durable.append(tmp_path, [event()], max_bytes=2)
    assert next(tmp_path.glob("*.open")).read_bytes() == original


def test_partial_append_is_removed_before_retry(tmp_path: Path, monkeypatch) -> None:
    durable.append(tmp_path, [event()])
    path = next(tmp_path.glob("*.open"))
    original = path.read_bytes()
    real = durable.os.write
    calls = 0

    def failing(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real(fd, data[:10])
        raise OSError("disk failure")

    monkeypatch.setattr(durable.os, "write", failing)
    with pytest.raises(durable.SpoolUnavailable):
        durable.append(tmp_path, [event()])
    assert path.read_bytes() == original


def test_day_inventory_deduplicates_retries_and_archive_receipts(tmp_path: Path) -> None:
    import json

    row = event()
    durable.append(tmp_path, [row])
    durable.append(tmp_path, [row])
    day = row.occurred_at.date().isoformat()
    (tmp_path / "uploaded.receipt").write_text(
        json.dumps({"days": {day: [f"{row.tenant_id}:{row.event_id}"]}})
    )
    assert durable.day_inventory(tmp_path, day)["events"] == 1


def test_payload_cannot_smuggle_a_personal_field(tmp_path: Path) -> None:
    row = event()
    row.payload["name"] = "private"
    with pytest.raises(durable.SpoolUnavailable):
        durable.append(tmp_path, [row])
    assert not list(tmp_path.glob("*.open"))


def test_killed_writer_tail_does_not_poison_acknowledged_rows(tmp_path: Path) -> None:
    import json

    durable.append(tmp_path, [event()])
    path = next(tmp_path.glob("*.open"))
    with path.open("ab") as handle:
        handle.write(b'{"partial":')
    durable.append(tmp_path, [event()])
    assert len([json.loads(line) for line in path.read_text().splitlines()]) == 2
