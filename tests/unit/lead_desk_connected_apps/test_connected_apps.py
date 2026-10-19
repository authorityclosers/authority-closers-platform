"""Connected apps: how a test's progress reads, and the plain words of a report."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from ac_platform.lead_desk import connected_apps as apps


def message(status: str, **more: Any) -> Any:
    return SimpleNamespace(
        id=uuid4(), status=status, status_at=datetime.now(UTC), error_title=None, **more
    )


def test_a_whatsapp_test_passes_at_delivered_and_says_why_it_failed() -> None:
    sent = apps.whatsapp_view(message("sent"))
    assert sent.status == "waiting" and [s.state for s in sent.steps] == [
        "done",
        "waiting",
        "waiting",
    ]
    assert sent.test_id is not None and sent.test_id.startswith("wa-")
    delivered = apps.whatsapp_view(message("delivered"))
    assert delivered.status == "passed" and "Read shows" in delivered.words
    read = apps.whatsapp_view(message("read"))
    assert read.status == "passed" and [s.state for s in read.steps] == ["done"] * 3
    failed = apps.whatsapp_view(message("failed"))
    assert failed.status == "failed" and failed.words == "WhatsApp didn't send it: refused."


def test_test_ids_are_strict() -> None:
    assert apps._LEAD_TEST.fullmatch("lead-5550000000001-1760943600")
    for bad in ("lead-1-1760943600", "lead-abc-1760943600", "lead-5550000000001-x", "wa-1"):
        assert not apps._LEAD_TEST.fullmatch(bad) and not apps._WA_TEST.fullmatch(bad)


def test_a_report_is_its_health_in_words() -> None:
    health = apps.AppHealth(
        app="phone_calls",
        name=apps.NAMES["phone_calls"],
        state="problem",
        words="1 phone has call logging off.",
        configured=True,
        connections=[
            apps.Connection(id="a", label="Asha", detail="Call log on", state="ready"),
            apps.Connection(
                id="b", label="Ravi", state="problem", words="Call logging is off on this phone."
            ),
        ],
    )
    result = apps.report(health)
    assert result.status == "failed" and result.words == "1 phone has call logging off."
    assert [(s.label, s.state) for s in result.steps] == [("Asha", "done"), ("Ravi", "failed")]


def test_views_are_camel_case_and_name_no_amount() -> None:
    dumped = apps.TestResult(app="whatsapp", status="passed", words="Delivered.").model_dump(
        by_alias=True
    )
    assert "testId" in dumped and "leadId" in dumped
    assert all("₹" not in name for name in apps.NAMES.values())
