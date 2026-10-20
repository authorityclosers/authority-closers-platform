"""Report settings versions (owner order, 19 Oct 2026): schema, version 1, resolution."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence.report_settings import (
    INDUSTRY_PROFILES,
    PARAMETERS,
    POINTER_IDS,
    SCHEMA,
    VERSION_1,
    Choice,
    ReportSettings,
    changes,
    effective_version,
    flatten,
    industry_of,
    settings_from_document,
    valid_industry,
)

WEB_MODEL = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "sales-xray-web"
    / "app"
    / "xray-report"
    / "model.ts"
)
AT = datetime(2026, 10, 19, tzinfo=UTC)


def test_version_1_is_todays_report_with_everything_on() -> None:
    flat = flatten(VERSION_1)
    assert flat["report.style"] == "guided" and flat["report.complexity"] == "standard"
    assert flat["report.pointers"] == list(POINTER_IDS) and flat["report.max_pointers"] == 27
    assert all(value for key, value in flat.items() if key.endswith(("enabled", "show_scores")))
    assert all(flat[f"report.parts.{part}"] for part in ("overview", "analysis", "outcome"))
    assert settings_from_document(VERSION_1.document()) == VERSION_1


def test_every_parameter_names_a_real_setting_and_back() -> None:
    keys = {parameter.key for parameter in PARAMETERS}
    assert keys == set(flatten(VERSION_1))
    for parameter in PARAMETERS:
        assert parameter.kind in {"choice", "toggle", "number", "pointers"}
        if parameter.kind == "choice":
            assert flatten(VERSION_1)[parameter.key] in {value for value, _ in parameter.choices}
        if parameter.tunable:
            assert parameter.signals, parameter.key  # a tuner needs something to learn from
    # The app follows every display setting; tone changes how the AI writes.
    in_app = {parameter.key for parameter in PARAMETERS if parameter.in_app}
    assert in_app == {parameter.key for parameter in PARAMETERS if parameter.applies == "display"}
    assert "coaching.tone" not in in_app
    assert {"report.style", "report.pointers", "report.show_scores"} <= in_app


def test_the_pointer_list_matches_the_app() -> None:
    source = WEB_MODEL.read_text(encoding="utf-8")
    block = source[source.index("export const POINTERS") :]
    assert tuple(re.findall(r'id: "([a-z_]+)"', block)[: len(POINTER_IDS)]) == POINTER_IDS


def test_settings_are_bounded_and_strict() -> None:
    custom = ReportSettings.model_validate(
        {
            "report": {
                "style": "compact",
                "parts": {"overview": True, "analysis": True, "outcome": False},
                "pointers": ["call_opening", "pricing"],
                "max_pointers": 5,
            },
            "coaching": {"tone": "direct", "max_moments": 3},
        },
        strict=False,
    )
    assert [item["key"] for item in changes(VERSION_1, custom)] == [
        "report.style",
        "report.parts.outcome",
        "report.pointers",
        "report.max_pointers",
        "coaching.max_moments",
        "coaching.tone",
    ]
    for broken in (
        {"report": {"style": "neon"}},
        {"report": {"pointers": []}},
        {"report": {"pointers": ["call_opening", "call_opening"]}},
        {"report": {"pointers": ["made_up"]}},
        {"report": {"max_pointers": 2}},
        {"report": {"parts": {"overview": False, "analysis": False, "outcome": False}}},
        {"coaching": {"max_moments": 11}},
        {"prospect": {"sections": {"astrology": True}}},
        {"extra": True},
    ):
        with pytest.raises(ValidationError):
            ReportSettings.model_validate(broken, strict=False)
    with pytest.raises(ValueError):
        settings_from_document({"schema": "other/1"})
    assert custom.document()["schema"] == SCHEMA and len(custom.digest()) == 64


def test_an_organisation_gets_its_own_then_its_industry_then_the_general_version() -> None:
    own, industry, general = Choice(4, AT), Choice(3, AT), Choice(2, AT)
    assert effective_version(organisation=own, industry=industry, general=general) == (
        4,
        "organisation",
    )
    assert effective_version(organisation=None, industry=industry, general=general) == (
        3,
        "industry",
    )
    # A cleared choice (None) inherits again.
    assert effective_version(organisation=Choice(None, AT), industry=None, general=general) == (
        2,
        "general",
    )
    assert effective_version(organisation=None, industry=None, general=None) == (1, "built_in")


def test_industries_are_the_lead_stage_profiles() -> None:
    assert INDUSTRY_PROFILES["real_estate"] == "Real estate"
    assert "simple" not in INDUSTRY_PROFILES  # "Any business" is the general default
    assert valid_industry(" Real_Estate ") == "real_estate" and valid_industry(None) is None
    for wrong in ("62011", "J62", "simple", "retail & more"):
        with pytest.raises(ValueError, match="lead-stage profiles"):
            valid_industry(wrong)
    assert industry_of("home_services") == "home_services"
    assert industry_of("simple") is None  # an organisation on "Any business" has none
    assert industry_of("not a profile") is None
    assert industry_of(None) is None
