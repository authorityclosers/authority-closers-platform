from __future__ import annotations

import pytest

from ac_platform.community.application import (
    InvalidLeaderboardCursor,
    LeaderboardCursor,
    UsernameInvalid,
    UsernameReserved,
    decode_cursor,
    encode_cursor,
    normalize_username,
)


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("  Learner_7  ", "learner_7"),
        (f"  {'a' * 30}  ", "a" * 30),
        ("alex", "alex"),
        ("a1_b2", "a1_b2"),
    ],
)
def test_normalize_username_returns_one_stable_public_key(raw: str, normalized: str) -> None:
    assert normalize_username(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "ab",
        "1learner",
        "learner-7",
        "learner__7",
        "learner_",
        "learner@example.test",
        "a" * 31,
    ],
)
def test_normalize_username_rejects_ambiguous_or_email_shaped_values(raw: str) -> None:
    with pytest.raises(UsernameInvalid):
        normalize_username(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "admin",
        "AuthorityClosers",
        "dipak_vishwakarma",
        "official_learner",
        "learner_official",
        "support",
        "authority_closers_team",
        "dipak_sales",
        "learner_support",
    ],
)
def test_normalize_username_rejects_reserved_impersonation_keys(raw: str) -> None:
    with pytest.raises(UsernameReserved):
        normalize_username(raw)


def test_leaderboard_cursor_round_trips_only_stable_non_private_order_fields() -> None:
    expected = LeaderboardCursor(xp=90, username="learner_7")

    encoded = encode_cursor(expected)

    assert decode_cursor(encoded) == expected
    assert "@" not in encoded


def test_leaderboard_cursor_accepts_legacy_reserved_display_names() -> None:
    expected = LeaderboardCursor(xp=90, username="admin")

    assert decode_cursor(encode_cursor(expected)) == expected


@pytest.mark.parametrize(
    "cursor",
    [
        "not-json",
        "e30",
        "",
        "eyJ2IjoyfQ",
        encode_cursor(LeaderboardCursor(xp=1, username="learner_7")) + "!",
        encode_cursor(LeaderboardCursor(xp=1, username="learner_7")) + "tampered",
        encode_cursor(LeaderboardCursor(xp=2**63, username="learner_7")),
        "eyJ1IjpudWxsLCJ2IjoxLCJ4cCI6MX0",
        "eyJ1Ijp7fSwidiI6MSwieHAiOjF9",
        "eyJ1IjoibGVhcm5lcl83IiwidiI6dHJ1ZSwieHAiOjF9",
        "eyJ1IjoibGVhcm5lcl83IiwidiI6MSwieHAiOnRydWV9",
    ],
)
def test_leaderboard_cursor_fails_closed(cursor: str) -> None:
    with pytest.raises(InvalidLeaderboardCursor):
        decode_cursor(cursor)
