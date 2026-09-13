from __future__ import annotations

from ac_platform.http.rate_limits import DEFAULT_RATE_LIMIT_RULES


def test_community_discovery_and_connection_routes_have_bounded_rules() -> None:
    rules = {
        rule.name: rule
        for rule in DEFAULT_RATE_LIMIT_RULES
        if rule.name.startswith("community-")
    }

    assert set(rules) == {
        "community-profile-search",
        "community-connection-actions",
        "community-discovery-update",
        "community-connection-remove",
        "community-report",
    }
    assert rules["community-profile-search"].capacity == 60
    assert rules["community-discovery-update"].capacity == 20
    assert rules["community-report"].capacity == 10
    assert rules["community-profile-search"].path.fullmatch("/v1/community/search")
    assert rules["community-profile-search"].path.fullmatch("/v1/community/connections")
    assert rules["community-profile-search"].path.fullmatch("/v1/community/public/learner_7")
    assert rules["community-connection-actions"].path.fullmatch(
        "/v1/community/connections/learner_7/accept"
    )
