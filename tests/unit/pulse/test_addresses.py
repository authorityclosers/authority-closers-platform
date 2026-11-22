"""Pulse's addresses (issue 235, 22 Nov 2026): production's Pulse is the Vitals OS app,
and a sign-in or org link saved under the old address is the same one."""

from __future__ import annotations

from ac_platform.identity.services import provider_issuer_lookup_values
from ac_platform.identity.sign_in_methods import PROVIDER_ISSUERS
from ac_platform.integrations import first_party
from ac_platform.pulse.addresses import (
    PULSE_LEGACY_ISSUER,
    PULSE_PRODUCTION_ISSUER,
    pulse_issuer_values,
)


def test_production_pulse_is_the_vitals_os_app() -> None:
    assert PULSE_PRODUCTION_ISSUER == "https://app.vitalsos.ai"
    assert PULSE_PRODUCTION_ISSUER in PROVIDER_ISSUERS["pulse"]
    assert first_party.verified(
        "Pulse", ["https://app.vitalsos.ai/api/v0/sales-xray/callback"], "production"
    )


def test_both_addresses_find_the_same_identities_and_links() -> None:
    both = {PULSE_PRODUCTION_ISSUER, PULSE_LEGACY_ISSUER}
    assert set(pulse_issuer_values(PULSE_PRODUCTION_ISSUER)) == both
    assert set(pulse_issuer_values(PULSE_LEGACY_ISSUER + "/")) == both
    assert set(provider_issuer_lookup_values(PULSE_PRODUCTION_ISSUER)) == both
    assert set(provider_issuer_lookup_values(PULSE_LEGACY_ISSUER)) == both
    # Any other Pulse (staging, dev, a test one) is only itself.
    assert pulse_issuer_values("https://pulse-dev.estateautopilots.com") == (
        "https://pulse-dev.estateautopilots.com",
    )
    assert provider_issuer_lookup_values("https://accounts.google.com") == (
        "https://accounts.google.com",
        "accounts.google.com",
    )
