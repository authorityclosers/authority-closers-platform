"""The authorization gate fails on missing rows, drift and unproven outcomes."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ci import authorization_gate as gate  # noqa: E402
from scripts.ci.authorization_fixtures import (  # noqa: E402
    CONTEXTS,
    command_uuid,
    resolve_path,
    synthesize,
)


def _row(method: str, path: str, actor: str, context: str, outcome: str, status: int) -> gate.Row:
    return gate.Row(method, path, actor, context, outcome, status, "academy")


def _table(*rows: gate.Row) -> gate.Table:
    return gate.Table(list(rows))


ALLOWED = _row("GET", "/v1/me", "learner", "academy", "allowed", 200)
DENIED = _row("GET", "/v1/me", "guest", "anonymous", "denied", 401)


def test_classification_only_trusts_proving_responses() -> None:
    assert gate.classify(200, {}, foreign=False, owner_allowed=None)[0] == "allowed"
    assert gate.classify(302, None, foreign=False, owner_allowed=None)[0] == "allowed"
    assert (
        gate.classify(401, {"code": "authentication_required"}, foreign=False, owner_allowed=None)[
            0
        ]
        == "denied"
    )
    assert (
        gate.classify(
            403, {"code": "admin_authorization_denied"}, foreign=False, owner_allowed=None
        )[0]
        == "denied"
    )
    for status in (404, 422, 429, 500, 503):
        assert (
            gate.classify(status, {"code": "x"}, foreign=False, owner_allowed=True)[0] == "unproven"
        )
    # A surface or origin rejection says nothing about the caller's authority.
    assert (
        gate.classify(403, {"code": "admin_surface_required"}, foreign=False, owner_allowed=None)[0]
        == "unproven"
    )
    # A hidden foreign resource is a denial only once the owner's context proved it exists.
    assert gate.classify(404, {}, foreign=True, owner_allowed=True) == (
        "denied",
        "foreign resource hidden (owner context allowed)",
    )
    assert gate.classify(404, {}, foreign=True, owner_allowed=False)[0] == "unproven"


def test_route_without_a_row_fails() -> None:
    expected = _table(ALLOWED, DENIED)
    actual = _table(ALLOWED, DENIED, _row("GET", "/v1/new", "guest", "anonymous", "denied", 401))
    problems = gate.compare(expected, actual)
    assert problems == ["route without a row: GET /v1/new"]
    assert gate.summary(actual, problems).startswith("authorization-gate: FAIL (2 routes")


def test_row_for_a_removed_route_fails() -> None:
    expected = _table(ALLOWED, DENIED, _row("GET", "/v1/old", "guest", "anonymous", "denied", 401))
    assert gate.compare(expected, _table(ALLOWED, DENIED)) == [
        "row for a route that no longer exists: GET /v1/old"
    ]


def test_row_that_disagrees_with_the_real_outcome_fails() -> None:
    expected = _table(ALLOWED, DENIED)
    actual = _table(_row("GET", "/v1/me", "learner", "academy", "denied", 403), DENIED)
    problems = gate.compare(expected, actual)
    assert len(problems) == 1 and problems[0].startswith(
        "drift: GET /v1/me as learner/academy: allowed (200) -> denied (403)"
    )


def test_unproven_outcome_fails_even_when_committed() -> None:
    unproven = gate.Row("GET", "/v1/me", "staff", "platform", "unproven", 404, "academy", "404")
    problems = gate.compare(_table(ALLOWED, DENIED, unproven), _table(ALLOWED, DENIED, unproven))
    assert problems == ["unproven: GET /v1/me as staff/platform: 404"]


def test_exact_table_passes_with_one_summary_line() -> None:
    table = _table(ALLOWED, DENIED)
    assert gate.compare(table, table) == []
    assert gate.summary(table, []) == "authorization-gate: PASS (1 routes, 0 drift)"


def test_render_is_sorted_stable_and_round_trips(tmp_path: Path) -> None:
    table = _table(
        ALLOWED, DENIED, _row("DELETE", "/v1/a", "owner", "organisation", "allowed", 204)
    )
    rendered = table.render()
    assert rendered == _table(*reversed(table.rows)).render()
    path = tmp_path / "expectations.json"
    path.write_text(rendered, encoding="utf-8")
    assert gate.Table.load(path).render() == rendered
    document = json.loads(rendered)
    assert document["schema"] == gate.SCHEMA
    assert [row["path"] for row in document["rows"]] == ["/v1/a", "/v1/me", "/v1/me"]


def test_findings_survive_regeneration_only_for_existing_rows() -> None:
    noted = gate.Row(*ALLOWED.__dict__.values())
    noted = gate.Row(**{**noted.__dict__, "finding": "looks too wide"})
    gone = gate.Row("GET", "/v1/gone", "owner", "academy", "allowed", 200, "academy", finding="x")
    carried = gate.carry_findings(_table(noted, gone), _table(ALLOWED, DENIED))
    assert {row.key: row.finding for row in carried.rows} == {
        ALLOWED.key: "looks too wide",
        DENIED.key: "",
    }


def test_synthesised_bodies_are_deterministic_and_use_fixture_ids() -> None:
    schema = {
        "type": "object",
        "required": ["program_id", "title", "count", "kind", "nested"],
        "properties": {
            "program_id": {"type": "string", "format": "uuid"},
            "title": {"type": "string", "minLength": 20, "maxLength": 24},
            "count": {"type": "integer", "minimum": 3},
            "kind": {"enum": ["video", "text"]},
            "nested": {"$ref": "#/$defs/Nested"},
            "optional": {"type": "string"},
        },
    }
    defs = {
        "Nested": {
            "type": "object",
            "required": ["flag"],
            "properties": {"flag": {"type": "boolean"}},
        }
    }
    resources = {"program_id": "11111111-1111-4111-8111-111111111111"}
    first = synthesize(schema, defs, resources)
    assert first == synthesize(schema, defs, resources)
    assert first["program_id"] == resources["program_id"]
    assert 20 <= len(first["title"]) <= 24
    assert first["count"] == 3 and first["kind"] == "video" and first["nested"] == {"flag": True}
    assert "optional" not in first


def test_path_parameters_resolve_from_the_fixture_world() -> None:
    assert resolve_path("/v1/x/{a}/{b}", {"a": 1, "b": "two"}) == ("/v1/x/1/two", "")
    assert resolve_path("/v1/x/{a}/{b}", {"a": 1}) == ("/v1/x/1/{b}", "b")
    assert command_uuid("one") == command_uuid("one") and command_uuid("one") != command_uuid("two")


def test_every_actor_has_a_context() -> None:
    assert {actor for actor, _ in CONTEXTS} == {
        "guest",
        "learner",
        "member",
        "admin",
        "owner",
        "staff",
    }


@pytest.mark.skipif(
    not os.environ.get("AC_TEST_DATABASE_URL"), reason="loopback PostgreSQL is required"
)
def test_generator_output_is_byte_stable_across_two_runs() -> None:
    prefixes = ("/health", "/v1/context", "/v1/platform/tenants")
    first = gate.generate(prefixes=prefixes)
    second = gate.generate(prefixes=prefixes)
    assert first.render() == second.render()
    assert {row.actor for row in first.rows} >= {
        "guest",
        "learner",
        "member",
        "admin",
        "owner",
        "staff",
    }
    assert [row for row in first.rows if row.outcome == "unproven"] == []
