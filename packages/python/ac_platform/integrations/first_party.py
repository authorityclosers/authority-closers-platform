"""First-party apps: our own sister products that connect to Sales X-Ray.

A first-party app registers itself like any other app (RFC 7591), so no secret is
set by hand anywhere. Sales X-Ray marks it as checked on the consent screen only
when its name matches and every return address is on that app's own host for this
environment, so a copy on another host shows as an unchecked app.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class FirstPartyApp:
    name: str
    maker: str
    hosts: dict[str, tuple[str, ...]]  # environment -> exact host names


LOCAL = ("127.0.0.1", "localhost")

APPS: tuple[FirstPartyApp, ...] = (
    FirstPartyApp(
        name="Pulse",
        maker="Estate Autopilots",
        hosts={
            "production": ("pulse.estateautopilots.com",),
            "staging": ("pulse-staging.estateautopilots.com",),
            "development": ("pulse-dev.estateautopilots.com",),
            "local": LOCAL,
            "test": ("pulse.example.test", *LOCAL),
        },
    ),
)

# Names only a first-party app may use with the checked mark.
NAMES = frozenset(app.name.casefold() for app in APPS)


def verified(name: str, redirect_uris: Iterable[str], environment: str) -> FirstPartyApp | None:
    """The first-party app this client is, or None."""
    for app in APPS:
        if name.casefold() != app.name.casefold():
            continue
        allowed = app.hosts.get(environment, ())
        hosts = [urlsplit(uri).hostname for uri in redirect_uris]
        if hosts and all(host in allowed for host in hosts):
            return app
    return None
