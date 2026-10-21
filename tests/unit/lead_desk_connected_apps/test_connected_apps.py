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


def test_meta_lead_ads_say_honestly_where_meta_review_stands() -> None:
    review = apps.meta_review()
    assert review.state == "pending" and review.since.isoformat() == "2026-10-19"
    assert "testers" in review.works_now and review.after
    dumped = review.model_dump(by_alias=True)
    assert "worksNow" in dumped and dumped["state"] == "pending"


def test_the_lead_stages_card_says_where_stages_go_and_what_waits() -> None:
    from ac_platform.lead_desk.journey import mapping
    from ac_platform.lead_desk.journey.model import default_journey

    journey = default_journey()
    nothing: dict[str, Any] = {"waiting_on": {}, "last_delivered_at": {}}
    off = apps._card(apps.lead_stages_card(journey, {}, nothing))
    assert (off.state, off.group, off.page, off.connect) == (
        "not_connected",
        "ads",
        "/leads?tab=stages",
        None,
    )
    assert off.words == (
        "Tell your ad platforms which of your leads become customers, so your ads find more"
        " people like them."
    )  # five platforms now; two would be named
    assert apps._platforms(["Meta", "Google Ads"]) == "Meta and Google Ads"
    assert off.connections == [] and not off.can_test

    events = mapping.suggestions("meta", journey)
    meta_on = {
        "destination": {"id": "1234567890", "name": "Fictional Homes dataset"},
        "on": True,
        "events": events,
    }
    sent = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)
    ready = apps.lead_stages_card(
        journey,
        {"ad_sync": {"providers": {"meta": meta_on}}},
        {"waiting_on": {}, "last_delivered_at": {"meta": sent, "google_ads": None}},
    )
    assert ready.state == "ready"
    assert ready.words == f"{len(journey.live)} stages · sent to Meta."
    [meta] = ready.connections
    assert (meta.id, meta.label, meta.detail, meta.state) == (
        "meta",
        "Meta",
        "Fictional Homes dataset",
        "ready",
    )
    assert meta.words == f"Sending {sum(1 for name in events.values() if name)} stages."
    assert ready.last_event is not None
    assert (ready.last_event.at, ready.last_event.words) == (sent, "Lead stage sent to Meta")

    # A stage added later, with a suggestion, waits for the manager before it's sent.
    added = next(key for key, name in events.items() if name)
    later = {**meta_on, "events": {k: v for k, v in events.items() if k != added}}
    check = apps.lead_stages_card(journey, {"ad_sync": {"providers": {"meta": later}}}, nothing)
    assert check.state == "problem"
    assert check.words == "1 new stage to confirm before Meta hears about it."

    # A stage Meta hasn't taken yet is tried again; the card says so.
    retrying = apps.lead_stages_card(
        journey,
        {"ad_sync": {"providers": {"meta": meta_on}}},
        {"waiting_on": {"meta": "190"}, "last_delivered_at": {}},
    )
    assert retrying.state == "problem" and retrying.last_error is not None
    assert retrying.words == "A stage didn't reach Meta yet. Sales Xray tries again."
    assert retrying.last_error.words == "A stage didn't reach Meta yet."

    switched = apps.lead_stages_card(
        journey,
        {"ad_sync": {"providers": {"meta": {**meta_on, "on": False}}}},
        nothing,
    )
    assert switched.state == "not_connected"
    assert [(c.state, c.words) for c in switched.connections] == [("off", "Switched off.")]


def test_the_last_comment_says_what_became_of_it() -> None:
    from datetime import timedelta

    from ac_platform.lead_desk.social import inbox

    at = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)

    def comment(state: str, **more: Any) -> Any:
        values = {"error_title": None, "error_code": None, "meta_time": None, **more}
        return SimpleNamespace(reply_state=state, created_at=at, **values)

    page = SimpleNamespace(config={})
    assert apps._comment_step(None, page, "messenger").words == "None yet."
    done = apps._comment_step(comment("replied"), page, "messenger")
    assert (done.state, done.words) == ("done", "Answered with a private message.")
    old = apps._comment_step(comment("skipped", error_code="too_old"), page, "messenger")
    assert old.state == "skipped" and "7 days" in (old.words or "")
    refused = apps._comment_step(
        comment(
            "failed",
            error_title="Meta doesn't allow a private reply to this comment."
            + inbox.META_MARK
            + "(#100) Invalid",
        ),
        page,
        "messenger",
    )
    assert refused.state == "failed"
    assert refused.words == (
        "Its private message didn't go: Meta doesn't allow a private reply to this comment."
        " Meta says: \u201c(#100) Invalid\u201d"
    )
    # A newer comment written as the Page itself shows instead, with how to test.
    later = (at + timedelta(minutes=1)).isoformat()
    page_itself = SimpleNamespace(
        config={inbox.SKIP_KEY: {"at": later, "channel": "messenger", "why": "from_page"}}
    )
    shown = apps._comment_step(comment("replied"), page_itself, "messenger")
    assert shown.state == "skipped" and "comment from a personal profile" in (shown.words or "")
    # On Instagram, the Page's skip isn't its own.
    assert apps._comment_step(None, page_itself, "instagram").words == "None yet."
