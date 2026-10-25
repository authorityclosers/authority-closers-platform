"""Bug issues' fingerprints (v0.93): the screen without ids, the newest error when there is
one, else the report's key words; the app version is not part of it."""

from __future__ import annotations

from ac_platform.bug_reports.issues import error_signature, fingerprint, key_words, route_template


def test_the_screen_keeps_its_shape_without_ids_or_query() -> None:
    assert route_template("/leads/5f0c2a1e-3b4d-4c5e-8f6a-7b8c9d0e1f2a?tab=notes#x") == "/leads/:id"
    assert route_template("/analysis/calls/1234") == "/analysis/calls/:id"
    assert route_template("") == "/"


def test_errors_match_whatever_their_numbers() -> None:
    first = [{"kind": "http", "status": 500, "path": "/v1/lead-desk/leads/42"}]
    second = [{"kind": "http", "status": 500, "path": "/v1/lead-desk/leads/97"}]
    assert error_signature(first) == error_signature(second)
    assert error_signature([{"kind": "console", "message": "x"}]) is None
    assert error_signature("nope") is None


def test_one_problem_one_fingerprint() -> None:
    same_error = [{"kind": "error", "message": "Cannot read properties of undefined (id 77)"}]
    other_error = [{"kind": "error", "message": "Network request failed"}]
    a = fingerprint("/leads/1", "leads", same_error, "It crashed")
    b = fingerprint("/leads/2?x=1", "leads", same_error, "Totally different words")
    c = fingerprint("/leads/2", "leads", other_error, "It crashed")
    assert a[0] == b[0] and a[0] != c[0]
    assert a[1] == "/leads/:id" and a[2] is not None
    # Without errors: the same complaint in another order is one issue; another is not.
    d = fingerprint("/leads", "leads", [], "The taking leads switch needs a better icon")
    e = fingerprint("/leads", "leads", [], "Better icon needed for the taking leads switch!")
    f = fingerprint("/leads", "leads", [], "Pipelines sit on the left, right side empty")
    assert d[0] == e[0] and d[0] != f[0]
    assert len(d[0]) == 64
    assert "this" not in key_words("this screen is broken").split()
