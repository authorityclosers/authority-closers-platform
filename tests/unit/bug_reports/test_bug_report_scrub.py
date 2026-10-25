"""What a bug report may keep about the screen, device and errors (scrub.py)."""

from __future__ import annotations

from ac_platform.bug_reports.scrub import (
    area_for,
    clean_context,
    clean_errors,
    scrub_route,
    scrub_text,
)


def test_text_loses_tokens_keys_contacts_and_long_opaque_strings() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlLXZhbHVl"
    text = (
        f"{jwt} Bearer abc.def-123456 ac_live_0123456789abcdef password: hunter22 "
        "mail asha@example.test call +91 98765-43210 sig " + "A" * 48 + " status 500 in 2 s"
    )
    assert scrub_text(text, 500) == (
        "[token] Bearer [token] [key] [secret] mail [email] call [phone] sig [long]"
        " status 500 in 2 s"
    )
    assert scrub_text("a\n\n  b", 10) == "a b"
    assert scrub_text("one two three", 7) == "one two"
    assert scrub_text(None, 5) == ""


def test_routes_keep_the_screen_and_drop_secret_values_and_fragments() -> None:
    assert scrub_route("/leads?lead=8f0e&tab=stages#top") == "/leads?lead=8f0e&tab=stages"
    assert scrub_route("/auth/complete?code=987654&state=xyz") == "/auth/complete?code=&state="
    assert scrub_route("https://evil.example/x?phone=98765") == "/x?phone="
    assert scrub_route("") == "/"
    assert scrub_route(None) == "/"


def test_area_comes_from_the_route_first() -> None:
    assert area_for("/leads?lead=1") == "leads"
    assert area_for("/analysis/calls/2b1f") == "report"
    assert area_for("/analysis/calls") == "calls"
    assert area_for("/analysis/new") == "calls"
    assert area_for("/settings/team") == "settings"
    assert area_for("/") == "home"
    assert area_for("/somewhere-new", "chats") == "chats"
    assert area_for("/somewhere-new", "made-up") == "other"


def test_context_keeps_only_listed_fields() -> None:
    kept = clean_context(
        {
            "app": {"channel": "android", "version": "0.85.0", "build": 7, "x": "y"},
            "device": {
                "os": "Android 14",
                "theme": "dark",
                "connection": "fibre",
                "touch": "yes",
                "online": True,
                "pixel_ratio": 2.625,
                "memory_gb": 10_000,
                "email": "asha@example.test",
            },
            "person": {"name": "Asha"},
        }
    )
    assert kept == {
        "app": {"channel": "android", "version": "0.85.0"},
        "device": {"os": "Android 14", "theme": "dark", "online": True, "pixel_ratio": 2.62},
    }
    assert clean_context("nonsense") == {"app": {}, "device": {}}


def test_errors_are_bounded_and_scrubbed() -> None:
    many = [{"kind": "error", "message": f"boom {n}"} for n in range(30)]
    kept = clean_errors(many)
    assert len(kept) == 20 and kept[-1]["message"] == "boom 29"
    one = clean_errors(
        [
            {
                "kind": "http",
                "at": "2026-10-23T10:00:00.000Z",
                "status": 502,
                "method": "get",
                "path": "/v1/x?token=abc",
                "reference": "bad reference with spaces",
                "body": "never kept",
            }
        ]
    )
    assert one == [
        {"kind": "http", "at": "2026-10-23T10:00:00.000Z", "status": 502, "path": "/v1/x?token="}
    ]
    assert clean_errors("nope") == []


def test_the_trail_keeps_twenty_named_steps_and_nothing_else() -> None:
    """Demo P0 (26 Oct 2026): the last app steps travel with a report, names and times only."""
    from ac_platform.bug_reports.scrub import clean_context

    steps = [
        {"event": f"step_{n}", "at": "2026-10-26T04:30:00.000Z", "route": "/leads?token=x"}
        for n in range(25)
    ]
    steps += [
        {"event": "Has Spaces"},
        {"event": "call_logged", "at": "not a time", "words": "a lead's name"},
        "text",
    ]
    context = clean_context({"app": {}, "device": {}, "trail": steps})
    trail = context["trail"]
    assert len(trail) == 18  # the last twenty items, two of them dropped as malformed
    assert trail[0] == {
        "event": "step_8",
        "at": "2026-10-26T04:30:00.000Z",
        "route": "/leads?token=",
    }
    assert trail[-1] == {"event": "call_logged"}
    assert "trail" not in clean_context({"trail": "nope"})
