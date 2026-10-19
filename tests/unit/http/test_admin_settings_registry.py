"""The Admin settings registry (Phase 6): one manifest, checked against the real areas.

Each change body the registry describes must pass that area's own request model and
validation, every route it names must be served by the real application, and every
bound and option must match the area's model, so the registry cannot drift.
"""

from __future__ import annotations

import json
import typing

import pytest
from pydantic import ValidationError

import ac_platform.http.app as app_module
from ac_platform.admin_settings.registry import (
    AREAS,
    SETTINGS,
    find,
    manifest,
    pointer,
    request_body,
)
from ac_platform.call_data.settings import DEFAULTS, SettingsError, public, validate
from ac_platform.conversation_intelligence.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    AnalysisSettings,
)
from ac_platform.http.conversation_admin import AnalysisSettingsIntent
from ac_platform.http.conversation_execution_control import (
    BudgetCapIntent,
    ExecutionControlIntent,
)
from tests.unit.http.test_conversation_learner_acquisition import _settings

ANALYSIS_ANSWER = {
    "revision": 4,
    "created_at": "2026-10-19T08:00:00+00:00",
    "settings": DEFAULT_ANALYSIS_SETTINGS.effective_values(),
}
CALL_DATA_ANSWER = public(validate({}), revision=7)


def test_ids_are_unique_and_every_setting_belongs_to_an_area() -> None:
    ids = [item.id for item in SETTINGS]
    assert len(ids) == len(set(ids))
    areas = {area["key"] for area in AREAS}
    assert {item.area for item in SETTINGS} <= areas
    assert all(item.write or item.why_not for item in SETTINGS)
    body = json.loads(json.dumps(manifest()))
    assert body["schema"] == "ac.admin-settings/1"
    assert len(body["settings"]) == len(SETTINGS)


def test_the_real_application_serves_every_route_the_registry_names(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "settings", _settings())
    monkeypatch.setattr(app_module, "compose_hosted_intake", lambda _settings: None)
    monkeypatch.setattr(app_module, "compose_acquisition", lambda _settings, _intake: None)
    paths = app_module.create_app().openapi()["paths"]
    assert "get" in paths["/v1/admin/settings"]
    for item in SETTINGS:
        assert "get" in paths[item.read.path], item.id
        if item.write:
            assert item.write.method.lower() in paths[item.write.path], item.id


def test_analysis_bounds_and_options_match_the_model() -> None:
    fields = AnalysisSettings.model_fields
    for item in SETTINGS:
        if item.area != "analysis":
            continue
        assert item.write and item.write.merge
        key = item.write.merge.key[0]
        info = fields[key]
        if item.kind == "int":
            low = next(rule.ge for rule in info.metadata if hasattr(rule, "ge"))
            high = next(rule.le for rule in info.metadata if hasattr(rule, "le"))
            assert (item.minimum, item.maximum) == (low, high), item.id
        else:
            assert [value for value, _ in item.options] == list(typing.get_args(info.annotation))


@pytest.mark.parametrize("item", [item for item in SETTINGS if item.area == "analysis"])
def test_analysis_changes_pass_the_areas_own_request_model(item) -> None:
    assert item.write is not None
    value = item.maximum if item.kind == "int" else item.options[-1][0]
    body = request_body(item, ANALYSIS_ANSWER, value)
    if item.id == "analysis.report_language":
        # A language other than English needs a versioned prompt: the area refuses it.
        with pytest.raises(ValidationError):
            AnalysisSettingsIntent.model_validate(body)
        body["settings"]["c5_coaching_prompt_revision"] = "coaching-v6"
    intent = AnalysisSettingsIntent.model_validate(body)
    assert intent.expected_revision == 4
    key = item.write.merge.key[0] if item.write.merge else ""
    assert getattr(intent.settings, key) == value
    # Only that one field changed.
    others = {k: v for k, v in intent.settings.effective_values().items() if k != key}
    before = {k: v for k, v in ANALYSIS_ANSWER["settings"].items() if k != key}
    if item.id != "analysis.report_language":
        assert others == before


@pytest.mark.parametrize("item", [item for item in SETTINGS if item.area == "call-data"])
def test_call_data_changes_pass_the_engines_validation_at_their_bounds(item) -> None:
    assert item.write is not None
    if item.kind == "int":
        for good in (item.minimum, item.maximum):
            body = request_body(item, CALL_DATA_ANSWER, good)
            assert body["expected_revision"] == 7
            validate(body["config"])
        for bad in (item.minimum - 1, item.maximum + 1):
            with pytest.raises(SettingsError):
                validate(request_body(item, CALL_DATA_ANSWER, bad)["config"])
    elif item.kind == "bool":
        assert validate(request_body(item, CALL_DATA_ANSWER, False)["config"])
    else:
        assert item.options_from is not None
        menu = pointer(CALL_DATA_ANSWER, item.options_from[0])
        values = [entry[item.options_from[1]] for entry in menu]
        assert values
        for value in values:
            validate(request_body(item, CALL_DATA_ANSWER, value)["config"])
    pipeline = item.id.split(".")[1]
    assert set(DEFAULTS[pipeline]) >= {item.id.split(".")[2]}


def test_running_and_budget_changes_pass_their_request_models() -> None:
    paused = find("execution.paused")
    assert paused is not None
    answer = {"control": {"paused": False, "revision": 3, "changed_at": None}}
    assert pointer(answer, paused.read.value) is False
    intent = ExecutionControlIntent.model_validate(request_body(paused, answer, True))
    assert (intent.paused, intent.expected_revision) == (True, 3)

    cap = find("budget.cap_paise")
    assert cap is not None and cap.write and cap.write.needs_reason
    budget = {"revision": 9, "approved_cap_paise": 1_000_000, "budget": {"cap_paise": 30_000}}
    with pytest.raises(ValueError, match="reason"):
        request_body(cap, budget, 40_000)
    intent_cap = BudgetCapIntent.model_validate(
        request_body(cap, budget, 40_000, reason=" Owner asked to raise it ")
    )
    assert (intent_cap.new_cap_paise, intent_cap.reason, intent_cap.expected_revision) == (
        40_000,
        "Owner asked to raise it",
        9,
    )
    ceiling = find("budget.ceiling_paise")
    assert ceiling is not None and ceiling.write is None
    with pytest.raises(ValueError, match="owner"):
        request_body(ceiling, budget, 1)


def test_pointer_reads_rfc_6901_paths_and_misses_softly() -> None:
    document = {"a": {"b/c": [10, {"d~e": 5}]}}
    assert pointer(document, "/a/b~1c/0") == 10
    assert pointer(document, "/a/b~1c/1/d~0e") == 5
    assert pointer(document, "/a/missing") is None
    assert pointer(document, "/a/b~1c/9") is None
    assert pointer(document, "") == document
