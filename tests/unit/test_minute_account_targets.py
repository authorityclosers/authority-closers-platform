from __future__ import annotations

from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.minute_account_targets import (
    MAX_MINUTE_ACCOUNT_LOOKUP_LENGTH,
    MinuteAccountLookupInvalid,
    _display_name,
    _normalize_query,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("  LEARNER.ONE@EXAMPLE.TEST ", ("email", "learner.one@example.test")),
        (" Public_Learner ", ("public_username", "public_learner")),
    ],
)
def test_minute_account_query_uses_exact_canonical_identity_forms(
    query: str,
    expected: tuple[str, str],
) -> None:
    assert _normalize_query(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        str(uuid4()),
        "+1 (555) 010-1212",
        "A Person Name",
        "missing-at-domain",
        "x" * (MAX_MINUTE_ACCOUNT_LOOKUP_LENGTH + 1),
    ],
)
def test_minute_account_query_rejects_nonexact_or_oversized_identity_forms(query: str) -> None:
    with pytest.raises(MinuteAccountLookupInvalid):
        _normalize_query(query)


def test_minute_account_display_name_does_not_echo_an_email_address() -> None:
    assert _display_name("learner@example.test", "Learner") == "Learner"
    assert _display_name("learner@example.test", "person@example.test") == "Learner"
    assert _display_name("Learner One", "Learner") == "Learner One"
