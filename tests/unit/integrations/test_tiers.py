"""The plan table (tier_policy) and what people read about it (tiers)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.economics import policy as economics
from ac_platform.integrations import tier_policy, tiers
from ac_platform.integrations.scopes import APP_SCOPES, SCOPES


def test_defaults_keep_todays_access_and_nobody_gets_less_than_120_a_minute() -> None:
    table = tier_policy.validate({})
    assert table["advertise_writes"] is False and table["overrides"] == {}
    unbilled = table["tiers"]["unbilled"]
    assert unbilled["scopes"] == sorted({*SCOPES, *APP_SCOPES})
    assert unbilled["api_keys"] is True and unbilled["webhooks"] == 1
    for row in table["tiers"].values():
        assert row["per_minute"] >= 120 and row["workspace_per_minute"] >= row["per_minute"]
    trial = table["tiers"]["trial"]
    assert trial["scopes"] == ["calls:read", "leads:read", "reports:read"]
    assert trial["api_keys"] is False and trial["enforce_existing"] is False
    assert table["tiers"]["organisation"]["api_keys"] is True
    assert table["tiers"]["enterprise"]["per_minute"] == 300


def test_the_table_lives_in_the_economics_settings() -> None:
    assert economics.validate({})["developer_platform"] == tier_policy.validate({})
    changed = economics.validate(
        {
            "developer_platform": {
                "tiers": {"trial": {"per_minute": 200, "workspace_per_minute": 400}}
            }
        }
    )
    assert changed["developer_platform"]["tiers"]["trial"]["per_minute"] == 200
    with pytest.raises(economics.SettingsError) as raised:
        economics.validate({"developer_platform": {"tiers": {"trial": {"scopes": ["root"]}}}})
    assert raised.value.code == "trial_scopes"


@pytest.mark.parametrize(
    ("section", "code"),
    [
        ({"surprise": 1}, "developer_platform"),
        ({"advertise_writes": "yes"}, "advertise_writes"),
        ({"tiers": {"gold": {}}}, "tiers"),
        ({"tiers": {"trial": {"price": 1}}}, "trial_field"),
        ({"tiers": {"trial": {"per_minute": 0}}}, "trial_per_minute"),
        ({"tiers": {"trial": {"per_minute": 500}}}, "trial_per_minute"),
        ({"tiers": {"trial": {"api_keys": 1}}}, "trial_api_keys"),
        ({"tiers": {"trial": {"monthly_requests": -1}}}, "trial_monthly_requests"),
        ({"overrides": {"not-a-uuid": "trial"}}, "overrides"),
        ({"overrides": {str(uuid4()): "gold"}}, "overrides"),
    ],
)
def test_a_bad_table_is_refused_naming_what(section: dict[str, object], code: str) -> None:
    with pytest.raises(tier_policy.TierSettingsError) as raised:
        tier_policy.validate(section)
    assert raised.value.code == code


def test_refusals_are_plain_and_name_a_plan_never_a_price() -> None:
    platform = tiers.DEFAULT_PLATFORM
    assert tiers.not_included(platform, "leads:notes") == (
        "This plan doesn't include “Add notes to leads”. It comes with the Organisation plan."
    )
    assert tiers.not_included(platform, "calls:write").endswith("the Personal plan.")
    assert tiers.keys_not_included(platform) == "API keys come with the Organisation plan."
    trial = platform.tier("trial")
    assert tiers.split(trial, ["leads:notes", "calls:read", "calls:read"]) == (
        ["calls:read"],
        ["leads:notes"],
    )
    rows = {row["key"]: row for row in tiers.includes(platform, trial)}
    assert rows["connector_read"]["included"] and rows["connector_read"]["comes_with"] is None
    assert rows["connector_writes"]["comes_with"] == "Organisation"
    assert rows["api_keys"] == {
        "key": "api_keys",
        "label": "API keys and the sx command line",
        "included": False,
        "comes_with": "Organisation",
    }
    for row in tiers.includes(platform, trial):
        assert "₹" not in row["label"] and "price" not in row["label"].lower()


def test_tiers_follow_the_owners_table() -> None:
    platform = tiers.platform_from(
        {"tiers": {"organisation": {"label": "Team", "per_minute": 150}}}
    )
    assert platform.tier("organisation").label == "Team"
    assert tiers.comes_with(platform, "leads:notes") == "Team"
    assert tiers.per_key_rule(platform.tier("organisation")).capacity == 150
    assert tiers.per_workspace_rule(platform.tier("organisation")).capacity == 600
