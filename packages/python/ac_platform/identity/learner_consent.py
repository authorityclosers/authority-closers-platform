"""Published learner consent acknowledgements, one per consent version.

A consent version names the exact words a person accepted: the accept audit
event stores only the version. Add a new entry for every new wording and never
edit an old one, so every recorded acceptance can still be traced to its text
(supersede audit history, never overwrite it). The Terms and Privacy copy of a
version is the learner app's `learner-policy.ts` at the commit that introduced
it. The release profiles in `infra/application/environments` must pin
`CURRENT_LEARNER_CONSENT_VERSION` (tests/unit/identity/test_learner_consent_documents.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

CURRENT_LEARNER_CONSENT_VERSION = "ac-learner-terms-privacy-2026-10-18-v2"

LEARNER_CONSENT_ACKNOWLEDGEMENTS: Mapping[str, str] = MappingProxyType(
    {
        "ac-learner-terms-privacy-2026-09-30-v1": (
            "I confirm that I am 18 or older and accept the current Authority Closers "
            "Terms and Privacy notice for my learner account."
        ),
        CURRENT_LEARNER_CONSENT_VERSION: (
            "I confirm that I am 18 or older and accept the current Authority Closers "
            "Terms and Privacy notice for my Authority Closers account."
        ),
    }
)


def learner_consent_acknowledgement(version: str) -> str:
    """Return the words a person accepts for ``version``.

    A version without an entry is a test or development placeholder (released
    profiles are pinned to registered versions by the installer), so it shows
    the current words.
    """

    return (
        LEARNER_CONSENT_ACKNOWLEDGEMENTS.get(version)
        or LEARNER_CONSENT_ACKNOWLEDGEMENTS[CURRENT_LEARNER_CONSENT_VERSION]
    )
