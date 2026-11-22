"""Pulse's addresses (issue 235, owner 22 Nov 2026: the Pulse button opened
pulse.estateautopilots.com, not the Vitals OS app).

Production's Pulse is the Vitals OS app at ``PULSE_PRODUCTION_ISSUER``: the
default issuer when ``AC_PULSE_ISSUER`` is not set there, and so where "Sign in
with Pulse" and "Connect your Pulse org" go. The same Pulse (the same accounts and
subjects) answered at the old address, so a sign-in or org link saved under either
address is the same one (``PULSE_ISSUER_ALIASES``).
"""

from __future__ import annotations

from typing import Final

PULSE_PRODUCTION_ISSUER: Final = "https://app.vitalsos.ai"
PULSE_LEGACY_ISSUER: Final = "https://pulse.estateautopilots.com"
PULSE_ISSUER_ALIASES: Final = (PULSE_PRODUCTION_ISSUER, PULSE_LEGACY_ISSUER)


def pulse_issuer_values(issuer: str) -> tuple[str, ...]:
    """Every address one Pulse issuer has answered at (itself when it has no other)."""
    value = issuer.rstrip("/")
    return PULSE_ISSUER_ALIASES if value in PULSE_ISSUER_ALIASES else (value,)
