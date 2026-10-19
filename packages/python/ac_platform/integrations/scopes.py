"""What an API key may do. A key holds one or more scopes; each route needs one."""

from __future__ import annotations

from collections.abc import Iterable

# Key -> the words the Integrations page shows.
SCOPES: dict[str, str] = {
    "calls:read": "Read calls and their status",
    "reports:read": "Read call reports and the facts found in calls",
    "leads:read": "Read leads",
    "leads:write": "Create and update leads",
    "webhooks:manage": "Manage the webhook",
}


class ScopeError(ValueError):
    pass


def validate(scopes: Iterable[object]) -> list[str]:
    """Known scopes only, at least one, sorted and without repeats."""
    chosen = list(scopes)
    if not chosen or any(not isinstance(scope, str) or scope not in SCOPES for scope in chosen):
        raise ScopeError("scopes")
    return sorted(set(chosen))  # type: ignore[arg-type]


def public() -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label in SCOPES.items()]
