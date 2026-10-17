from __future__ import annotations

from pathlib import Path

import pytest

from ac_platform.identity.learner_consent import (
    CURRENT_LEARNER_CONSENT_VERSION,
    LEARNER_CONSENT_ACKNOWLEDGEMENTS,
    learner_consent_acknowledgement,
)

ROOT = Path(__file__).resolve().parents[3]
V1 = "ac-learner-terms-privacy-2026-09-30-v1"
V2 = "ac-learner-terms-privacy-2026-10-18-v2"
V1_WORDS = (
    "I confirm that I am 18 or older and accept the current Authority Closers "
    "Terms and Privacy notice for my learner account."
)
V2_WORDS = (
    "I confirm that I am 18 or older and accept the current Authority Closers "
    "Terms and Privacy notice for my Authority Closers account."
)


def test_the_words_accepted_under_v1_stay_recoverable_and_unchanged() -> None:
    assert learner_consent_acknowledgement(V1) == V1_WORDS


def test_v2_names_the_authority_closers_account() -> None:
    assert CURRENT_LEARNER_CONSENT_VERSION == V2
    assert learner_consent_acknowledgement(V2) == V2_WORDS


def test_a_version_without_an_entry_shows_the_current_words() -> None:
    for placeholder in ("staging-test-document-v1", "synthetic-consent-v1", ""):
        assert learner_consent_acknowledgement(placeholder) == V2_WORDS


def test_the_registry_cannot_be_edited_at_run_time() -> None:
    assert set(LEARNER_CONSENT_ACKNOWLEDGEMENTS) == {V1, V2}
    with pytest.raises(TypeError):
        LEARNER_CONSENT_ACKNOWLEDGEMENTS[V1] = "changed"  # type: ignore[index]


@pytest.mark.parametrize("environment", ("staging", "production"))
def test_release_profiles_pin_the_current_consent_version(environment: str) -> None:
    profile = (ROOT / "infra/application/environments" / f"{environment}.env").read_text(
        encoding="utf-8"
    )
    assert (
        profile.splitlines().count(f"AC_LEARNER_CONSENT_VERSION={CURRENT_LEARNER_CONSENT_VERSION}")
        == 1
    )


def test_learner_policy_and_sales_xray_sign_in_follow_the_registry() -> None:
    policy = (ROOT / "apps/learner-web/app/lib/learner-policy.ts").read_text(encoding="utf-8")
    assert f'export const LEARNER_POLICY_VERSION = "{CURRENT_LEARNER_CONSENT_VERSION}";' in policy
    sign_in = (ROOT / "apps/sales-xray-web/app/account-auth.tsx").read_text(encoding="utf-8")
    ending = learner_consent_acknowledgement(CURRENT_LEARNER_CONSENT_VERSION).rsplit(
        "Privacy notice ", 1
    )[1]
    assert f"                      {ending}\n" in sign_in
    assert "for my learner account" not in sign_in
