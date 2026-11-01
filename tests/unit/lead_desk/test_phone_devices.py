"""Each of a seller's phones, kept by install (phone personas ph1-55 and ph1-46, 1 Nov 2026:
one report per seller hid their second phone from Team and Connections)."""

from datetime import UTC, datetime, timedelta

from ac_platform.lead_desk.store import (
    PHONE_DEVICES_KEPT,
    PHONE_DEVICES_KEY,
    PHONES_KEY,
    keep_device,
    phone_devices,
)

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def report(device: str, at: datetime, **extra: object) -> dict[str, object]:
    return {"device_id": device, "reported_at": at.isoformat(), **extra}


def test_each_install_keeps_its_own_report_and_look():
    mine = keep_device(None, report("install-a", NOW, checks={"calls": True}), NOW)
    mine = keep_device(mine, report("install-b", NOW + timedelta(minutes=1)), NOW)
    assert set(mine) == {"install-a", "install-b"}
    # A call-history look keeps that install's checklist, and a checklist its look.
    looked = keep_device(mine, {"device_id": "install-a", "synced_at": NOW.isoformat()}, NOW)
    assert looked["install-a"]["checks"] == {"calls": True}
    assert looked["install-a"]["synced_at"] == NOW.isoformat()
    again = keep_device(looked, report("install-a", NOW, checks={"calls": False}), NOW)
    assert again["install-a"]["synced_at"] == NOW.isoformat()
    assert again["install-a"]["checks"] == {"calls": False}
    # Its newest recording is kept with it too.
    recorded = keep_device(
        again,
        {"device_id": "install-b", "recording_reported_at": NOW.isoformat()},
        NOW,
    )
    assert recorded["install-b"]["recording_reported_at"] == NOW.isoformat()


def test_old_installs_drop_out_and_at_most_five_stay():
    stale = report("install-old", NOW - timedelta(days=31))
    mine = keep_device({"install-old": stale}, report("install-new", NOW), NOW)
    assert set(mine) == {"install-new"}
    many: dict[str, object] = {}
    for minute in range(PHONE_DEVICES_KEPT + 2):
        many = keep_device(many, report(f"install-{minute}", NOW + timedelta(minutes=minute)), NOW)
    assert len(many) == PHONE_DEVICES_KEPT
    assert "install-0" not in many and f"install-{PHONE_DEVICES_KEPT + 1}" in many


def test_a_sellers_phones_newest_first_or_their_one_report_before():
    config = {
        PHONE_DEVICES_KEY: {
            "person": {
                "install-a": report("install-a", NOW - timedelta(hours=2)),
                "install-b": report("install-b", NOW - timedelta(hours=1)),
            }
        },
        PHONES_KEY: {"person": report("install-b", NOW), "other": report("install-c", NOW)},
    }
    assert [entry["device_id"] for entry in phone_devices(config, "person", NOW)] == [
        "install-b",
        "install-a",
    ]
    # A phone that hasn't reported since installs were kept apart: its one report.
    assert [entry["device_id"] for entry in phone_devices(config, "other", NOW)] == ["install-c"]
    assert phone_devices(config, "nobody", NOW) == []
