"""The standing consent's words are the owner's, verbatim, and bound to their version."""

import pytest

from ac_platform.call_ai import auto_consent

# Owner, 26 Oct 2026: "approve standing consent for auto-analysis: …". A change of these
# words is a new NOTICE_VERSION, never an edit: everyone who agreed is asked again.
APPROVED = (
    "When I record a sales call with Sales X-Ray in {organisation}, the customer knows the "
    "call is recorded. Sales X-Ray may analyse each call I record here as soon as it "
    "arrives, at my organisation's AI setting. I can turn this off in Settings, Privacy, "
    "at any time."
)


def test_the_words_are_the_owners_and_their_hash_is_stable() -> None:
    shown = auto_consent.notice("en")
    assert shown["text"] == APPROVED
    assert shown["title"] == "Analyse my calls automatically"
    assert shown["version"] == "auto-analysis-2026-10-26"
    assert shown["policy_sha256"] == auto_consent.notice("en")["policy_sha256"]
    assert len(shown["policy_sha256"]) == 64


def test_translations_wait_for_review() -> None:
    assert auto_consent.PENDING_LANGUAGES == ("hi", "mr")
    for language in auto_consent.PENDING_LANGUAGES:
        with pytest.raises(auto_consent.ConsentError):
            auto_consent.notice(language)
