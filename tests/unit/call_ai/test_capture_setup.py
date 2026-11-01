"""Call capture setup: the newest word wins, each phone keeps its newest finish, and a no is
asked again the next day (owner, 30 Oct 2026)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.call_ai import capture_setup

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


def _row(minutes: int, **payload: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), payload=payload, occurred_at=NOW + timedelta(minutes=minutes)
    )


def _newest_first(*rows: SimpleNamespace) -> list[SimpleNamespace]:
    return sorted(rows, key=lambda row: row.occurred_at, reverse=True)


def test_each_phone_keeps_its_newest_finish_and_nothing_else() -> None:
    found = capture_setup._fold(
        _newest_first(
            _row(1, outcome="completed", device="install-a", model="Redmi 13", uploads=False),
            _row(5, outcome="completed", device="install-b", model="Note 8 Pro", uploads=True),
            _row(9, outcome="completed", device="install-a", model="Redmi 13", uploads=True),
        )
    )
    assert [(phone.device, phone.uploads) for phone in found.phones] == [
        ("install-a", True),
        ("install-b", True),
    ]
    assert found.declined_at is None
    assert set(found.phones[0].view()) == {
        "device",
        "model",
        "app_version",
        "at",
        "recordings",
        "background",
        "uploads",
    }


def test_a_no_counts_only_while_it_is_the_last_word() -> None:
    said_no = _row(3, outcome="declined", idempotency_key="tap-2")
    found = capture_setup._fold(_newest_first(_row(1, outcome="declined"), said_no))
    assert found.declined_at == said_no.occurred_at
    assert (found.key, found.event_id) == ("tap-2", said_no.id)
    finished_after = capture_setup._fold(
        _newest_first(said_no, _row(4, outcome="completed", device="install-a"))
    )
    assert finished_after.declined_at is None
    assert len(finished_after.phones) == 1


def test_a_no_or_turning_consent_off_is_asked_again_a_day_later() -> None:
    found = capture_setup.Setup(declined_at=NOW)
    assert capture_setup.last_no(found, "ask", None) == NOW
    later = NOW + timedelta(hours=5)
    assert capture_setup.last_no(found, "off", later) == later
    # The consent's own time only counts when it is off.
    assert capture_setup.last_no(capture_setup.Setup(), "on", later) is None
    assert capture_setup.ask_again_at(NOW) == NOW + timedelta(days=1)
    assert capture_setup.ask_again_at(None) is None


@pytest.mark.parametrize(
    ("phones", "declined", "consent", "state"),
    [
        (1, False, "on", "set_up"),
        (0, False, "on", "phone_pending"),
        (1, False, "off", "turned_off"),
        (0, True, "ask", "declined"),
        (1, False, "ask", "consent_changed"),
        (0, False, "ask", "not_started"),
    ],
)
def test_team_says_set_up_or_why_not(phones: int, declined: bool, consent: str, state: str) -> None:
    phone = capture_setup.Phone("install-a", "Redmi 13", "xiaomi", "1.0.50", NOW, True, True, True)
    found = capture_setup.Setup(phones=(phone,) * phones, declined_at=NOW if declined else None)
    assert capture_setup.team_state(found, consent) == state


def test_a_finished_phone_keeps_no_number_and_needs_its_install_id() -> None:
    kept = capture_setup.phone_payload(
        {
            "device": " install-a ",
            "model": "Redmi 13",
            "family": "xiaomi",
            "app_version": "1.0.50",
            "recordings": True,
            "background": "yes",
            "uploads": True,
            "phone_number": "+15550100000",
        }
    )
    assert kept == {
        "device": "install-a",
        "model": "Redmi 13",
        "family": "xiaomi",
        "app_version": "1.0.50",
        "recordings": True,
        "background": False,
        "uploads": True,
    }
    with pytest.raises(capture_setup.SetupError) as refused:
        capture_setup.phone_payload({"device": "  "})
    assert refused.value.status == 422


def test_only_people_who_sell_go_through_it() -> None:
    assert {"owner", "admin", "manager", "member"} == capture_setup.REQUIRED_ROLES


def test_team_names_a_phone_as_people_know_it() -> None:
    # Phone personas, v1.21, 1 Nov 2026: Team listed the Redmi 13 as "2406ERN9CI".
    assert capture_setup.phone_name("2406ERN9CI", "xiaomi") == "Redmi 13 5G"
    assert capture_setup.phone_name("m1906g7g", "xiaomi") == "Redmi Note 8 Pro"
    # A model that already says what it is stays as it is.
    assert capture_setup.phone_name("Redmi 13", "xiaomi") == "Redmi 13"
    assert capture_setup.phone_name("Galaxy A15", "samsung") == "Galaxy A15"
    # Any other maker's code gets the maker before it.
    assert capture_setup.phone_name("SM-A155F", "samsung") == "Samsung SM-A155F"
    assert capture_setup.phone_name("V2318", "vivo") == "Vivo V2318"
    assert capture_setup.phone_name("Pixel 8", "other") == "Pixel 8"
    assert capture_setup.phone_name("  ", "xiaomi") is None


def test_a_finished_install_counts_once_newest_first_and_a_no_never() -> None:
    # Persona QA ph2-15, 1 Nov 2026: a workspace switch ran the phone's steps again.
    assert capture_setup.devices_of(
        [
            {"outcome": "completed", "device": "install-b"},
            {"outcome": "declined", "device": "install-c"},
            {"outcome": "completed", "device": " install-a "},
            {"outcome": "completed", "device": "install-b"},
            {"outcome": "completed", "device": ""},
            "not a payload",
        ]
    ) == ["install-b", "install-a"]


def test_call_logging_is_off_only_on_a_phone_that_says_so() -> None:
    # Phone personas ph1-23, 1 Nov 2026: a Play build (no call history) showed as "off".
    reported = "2026-11-01T09:00:00+00:00"
    assert capture_setup.call_log_off({"reported_at": reported, "checks": {"callLog": False}})
    assert not capture_setup.call_log_off({"reported_at": reported, "checks": {"callLog": True}})
    assert not capture_setup.call_log_off({"reported_at": reported, "checks": {"calls": True}})
    assert not capture_setup.call_log_off({"checks": {"callLog": False}})  # never reported
    assert not capture_setup.call_log_off(None)


def test_a_phone_is_named_by_its_finished_setup_else_its_maker() -> None:
    found = capture_setup._fold(
        [_row(1, outcome="completed", device="install-a", model="2406ERN9CI", family="xiaomi")]
    )
    assert capture_setup.phone_label("install-a", "xiaomi", found) == "Redmi 13 5G"
    assert capture_setup.phone_label("install-b", "xiaomi", found) == "Xiaomi phone"
    assert capture_setup.phone_label(None, None, None) == "phone"


def test_team_says_whether_a_phone_records_and_the_fix() -> None:
    # Competitor teardown #7, 1 Nov 2026: a dot and a line per seller on Team.
    now = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    ok = {"checks": {"recordings": True, "recorder": True}}
    recent = {"newest_at": (now - timedelta(minutes=12)).isoformat()}
    old = {"newest_at": (now - timedelta(days=5)).isoformat()}
    assert capture_setup.recording_state(ok, recent, now) == {
        "state": "ok",
        "last_at": (now - timedelta(minutes=12)).isoformat(),
        "fix": None,
    }
    assert capture_setup.recording_state(ok, old, now)["state"] == "late"  # type: ignore[index]
    assert capture_setup.recording_state(ok, {"newest_at": None}, now) == {
        "state": "late",
        "last_at": None,
        "fix": "test",
    }
    no_folder = {"checks": {"recordings": False, "recorder": True}}
    assert capture_setup.recording_state(no_folder, recent, now)["fix"] == "folder"  # type: ignore[index]
    off = {"checks": {"recordings": True, "recorder": False}}
    assert capture_setup.recording_state(off, recent, now)["fix"] == "recorder"  # type: ignore[index]
    assert capture_setup.recording_state(None, None, now) is None
